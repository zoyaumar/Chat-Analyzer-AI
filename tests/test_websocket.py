"""Socket tests: handshake, frames, fan-out and deletion broadcasts (S1, S8, B1).

`TestClient` is synchronous and drives the app in its own event loop, so these
tests use the `ws_client` fixture: a `NullPool` engine over the same test
database, with the socket handler's session factory swapped to match.
"""

from contextlib import contextmanager
from datetime import timedelta

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from chat_backend.auth_utils import create_access_token
from chat_backend.realtime import manager
from chat_backend.routes import websocket as websocket_module

PASSWORD = "pw123456"
#: Said by the socket when text fails the schema the REST route also uses.
BAD_TEXT = "text must be a string of at most 4000 characters"
#: Said by the socket when the handshake itself did not produce a user.
BAD_HANDSHAKE = "authentication failed"


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _register_and_login(client: TestClient, username: str) -> tuple[int, str]:
    """Register and log in over HTTP; return `(user id, token)`."""
    registered = client.post(
        "/users/register", json={"username": username, "password": PASSWORD}
    )
    assert registered.status_code == 200
    logged_in = client.post("/users/login", data={"username": username, "password": PASSWORD})
    assert logged_in.status_code == 200
    token = logged_in.json()["access_token"]
    return client.get("/users/me", headers=_auth(token)).json()["id"], token


@contextmanager
def _authenticated_socket(client: TestClient, token: str):
    """Open `/ws/chat`, complete the handshake, and hand over the live socket."""
    with client.websocket_connect("/ws/chat") as websocket:
        websocket.send_json({"type": "auth", "token": token})
        handshake = websocket.receive_json()
        assert handshake["type"] == "auth_ok"
        yield websocket, handshake["user_id"]


def _assert_nothing_pending(websocket) -> None:
    """Prove no earlier frame is waiting: the pong is the next thing sent.

    A socket receives frames in the order the server sends them, so answering a
    ping and reading the pong first is an assertion that the queue was empty.
    """
    websocket.send_json({"type": "ping"})
    assert websocket.receive_json() == {"type": "pong"}


def _fail_handshake(websocket, frame: dict, detail: str) -> None:
    """Send a first frame, expect the reason, then the 1008 close."""
    websocket.send_json(frame)
    assert websocket.receive_json() == {"type": "error", "detail": detail}
    with pytest.raises(WebSocketDisconnect) as closed:
        websocket.receive_json()
    assert closed.value.code == 1008


def test_first_frame_must_be_auth(ws_client):
    _, token = _register_and_login(ws_client, "alice")

    with ws_client.websocket_connect("/ws/chat") as websocket:
        _fail_handshake(websocket, {"type": "message", "text": "before auth"}, BAD_HANDSHAKE)

    # The refused frame left nothing behind: it was never a message to store.
    assert ws_client.get("/messages/", headers=_auth(token)).json() == []


def test_handshake_rejects_an_unreadable_token(ws_client):
    _register_and_login(ws_client, "alice")
    with ws_client.websocket_connect("/ws/chat") as websocket:
        _fail_handshake(websocket, {"type": "auth", "token": "garbage"}, BAD_HANDSHAKE)


def test_handshake_rejects_an_expired_token(ws_client):
    user_id, _ = _register_and_login(ws_client, "alice")
    expired = create_access_token({"sub": str(user_id)}, expires_delta=timedelta(minutes=-1))

    with ws_client.websocket_connect("/ws/chat") as websocket:
        _fail_handshake(websocket, {"type": "auth", "token": expired}, BAD_HANDSHAKE)


def test_handshake_rejects_a_token_for_a_user_that_does_not_exist(ws_client):
    _register_and_login(ws_client, "alice")
    ghost = create_access_token({"sub": "999999"})

    with ws_client.websocket_connect("/ws/chat") as websocket:
        _fail_handshake(websocket, {"type": "auth", "token": ghost}, BAD_HANDSHAKE)


def test_handshake_rejects_junk_and_non_object_json(ws_client):
    for raw in ("not json", "[1, 2]"):
        with ws_client.websocket_connect("/ws/chat") as websocket:
            websocket.send_text(raw)
            assert websocket.receive_json() == {
                "type": "error",
                "detail": "frames must be JSON objects",
            }
            with pytest.raises(WebSocketDisconnect) as closed:
                websocket.receive_json()
            assert closed.value.code == 1008


def test_handshake_times_out_without_a_first_frame(ws_client, monkeypatch):
    monkeypatch.setattr(websocket_module, "AUTH_TIMEOUT_SECONDS", 0.05)

    with ws_client.websocket_connect("/ws/chat") as websocket:
        assert websocket.receive_json() == {
            "type": "error",
            "detail": "authentication timed out",
        }
        with pytest.raises(WebSocketDisconnect) as closed:
            websocket.receive_json()
        assert closed.value.code == 1008


def test_authenticated_socket_joins_and_leaves_the_registry(ws_client):
    user_id, token = _register_and_login(ws_client, "alice")
    assert manager.connection_count() == 0

    with _authenticated_socket(ws_client, token) as (_, reported_user_id):
        assert reported_user_id == user_id
        assert manager.connection_count(user_id) == 1

    # Leaving the context closes the socket, and the handler unregisters it.
    assert manager.connection_count() == 0


def test_socket_stores_echoes_and_correlates_a_message(ws_client):
    user_id, token = _register_and_login(ws_client, "alice")

    with _authenticated_socket(ws_client, token) as (websocket, _):
        websocket.send_json(
            {"type": "message", "text": "hello over the wire", "client_id": "c1"}
        )
        frame = websocket.receive_json()

    assert frame["type"] == "message"
    assert frame["client_id"] == "c1"
    assert frame["message"]["text"] == "hello over the wire"
    assert frame["message"]["user_id"] == user_id

    stored = ws_client.get("/messages/", headers=_auth(token)).json()
    assert [row["text"] for row in stored] == ["hello over the wire"]
    # One row, one representation: the frame and the REST resource agree on the
    # id and on the serialized timestamp, both built on `MessageOut` (Q38).
    assert frame["message"] == stored[0]


def test_a_frame_without_a_client_id_has_no_correlation_field(ws_client):
    _, token = _register_and_login(ws_client, "alice")

    with _authenticated_socket(ws_client, token) as (websocket, _):
        websocket.send_json({"type": "message", "text": "no correlation"})
        assert "client_id" not in websocket.receive_json()


def test_ping_answers_with_the_pinned_pong_wire_form(ws_client):
    _, token = _register_and_login(ws_client, "alice")

    with _authenticated_socket(ws_client, token) as (websocket, _):
        websocket.send_json({"type": "ping"})
        # The exact wire form is pinned: liveness reads this string, so changing
        # it should be a deliberate, visible edit.
        assert websocket.receive_text() == '{"type":"pong"}'


def test_socket_fans_out_to_every_socket_of_the_same_user(ws_client):
    user_id, token = _register_and_login(ws_client, "alice")

    with _authenticated_socket(ws_client, token) as (first, _), _authenticated_socket(
        ws_client, token
    ) as (second, _):
        assert manager.connection_count(user_id) == 2
        first.send_json({"type": "message", "text": "to both tabs"})
        assert first.receive_json()["message"]["text"] == "to both tabs"
        assert second.receive_json()["message"]["text"] == "to both tabs"


def test_socket_never_delivers_another_users_message(ws_client):
    _, alice_token = _register_and_login(ws_client, "alice")
    _, bob_token = _register_and_login(ws_client, "bob")

    with _authenticated_socket(ws_client, alice_token) as (alice, _), _authenticated_socket(
        ws_client, bob_token
    ) as (bob, _):
        alice.send_json({"type": "message", "text": "for alice only"})
        assert alice.receive_json()["message"]["text"] == "for alice only"
        _assert_nothing_pending(bob)


def test_message_created_over_rest_reaches_an_open_socket(ws_client):
    _, token = _register_and_login(ws_client, "alice")

    with _authenticated_socket(ws_client, token) as (websocket, _):
        created = ws_client.post(
            "/messages/", json={"text": "over http"}, headers=_auth(token)
        ).json()
        # The same frame a socket-sent message produces: the transport is
        # invisible to the client, which is what makes the REST fallback safe.
        assert websocket.receive_json() == {"type": "message", "message": created}


def test_deleting_a_message_is_broadcast_to_the_open_sockets(ws_client):
    _, token = _register_and_login(ws_client, "alice")
    created = ws_client.post("/messages/", json={"text": "bye"}, headers=_auth(token)).json()

    with _authenticated_socket(ws_client, token) as (websocket, user_id):
        deleted = ws_client.delete(f"/messages/{created['id']}", headers=_auth(token))
        assert deleted.status_code == 200
        assert websocket.receive_json() == {
            "type": "message_deleted",
            "message_id": created["id"],
            "user_id": user_id,
        }


def test_delete_that_changed_nothing_broadcasts_nothing(ws_client):
    _, token = _register_and_login(ws_client, "alice")

    with _authenticated_socket(ws_client, token) as (websocket, _):
        assert ws_client.delete("/messages/424242", headers=_auth(token)).status_code == 404
        _assert_nothing_pending(websocket)


def test_deleting_someone_elses_message_broadcasts_nothing(ws_client):
    _, owner_token = _register_and_login(ws_client, "alice")
    _, other_token = _register_and_login(ws_client, "mallory")
    created = ws_client.post(
        "/messages/", json={"text": "not yours"}, headers=_auth(owner_token)
    ).json()

    with _authenticated_socket(ws_client, owner_token) as (owner_socket, _), (
        _authenticated_socket(ws_client, other_token)
    ) as (other_socket, _):
        refused = ws_client.delete(f"/messages/{created['id']}", headers=_auth(other_token))
        assert refused.status_code == 404
        _assert_nothing_pending(other_socket)
        # The owner still has the message, so nothing is announced to them either.
        _assert_nothing_pending(owner_socket)


@pytest.mark.parametrize(
    ("frame", "detail"),
    [
        ({"type": "nonsense"}, "unsupported frame type: 'nonsense'"),
        ({"type": "message"}, BAD_TEXT),
        ({"type": "message", "text": {"not": "text"}}, BAD_TEXT),
        ({"type": "message", "text": "x" * 4001}, BAD_TEXT),
    ],
)
def test_a_frame_that_fails_validation_is_answered_and_survived(ws_client, frame, detail):
    _, token = _register_and_login(ws_client, "alice")

    with _authenticated_socket(ws_client, token) as (websocket, _):
        websocket.send_json(frame)
        assert websocket.receive_json() == {"type": "error", "detail": detail}
        # Still usable: one rejected frame does not cost the connection.
        _assert_nothing_pending(websocket)


def test_binary_frames_are_answered_with_an_error(ws_client):
    _, token = _register_and_login(ws_client, "alice")

    with _authenticated_socket(ws_client, token) as (websocket, _):
        websocket.send_bytes(b'{"type": "ping"}')
        assert websocket.receive_json() == {
            "type": "error",
            "detail": "binary frames are not supported",
        }
        _assert_nothing_pending(websocket)

