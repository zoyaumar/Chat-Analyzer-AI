"""`/ws/chat` — the realtime channel (gaps S1, S8, B1/F11).

The socket is a transport, not a second implementation of the API: frames are
validated with the schemas the REST routes use, written through `crud`, and
answered with frames built by `realtime`. A rule that changes for HTTP changes
here too (Q38).

Authentication happens in the **first frame** — `{"type": "auth", "token": …}` —
rather than in the query string (gap S8): a URL leaks into logs, proxy caches
and browser history, a frame does not. A socket that has not authenticated
within `AUTH_TIMEOUT_SECONDS` is closed with 1008 and never joins the fan-out, so
`send_to_user` can never target an unauthenticated connection (gaps S1/B3).

A database session is opened per operation, not per connection: an idle socket
holds no pool connection while it waits.
"""

import asyncio
import contextlib
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from chat_backend import crud, models, realtime, schemas
from chat_backend.auth_utils import user_id_from_token
from chat_backend.database import SessionLocal
from chat_backend.realtime import manager

router = APIRouter()

#: How long a freshly accepted socket may take to send its auth frame.
AUTH_TIMEOUT_SECONDS = 10.0

#: RFC 6455 "policy violation": the handshake or a frame was unacceptable. The
#: client must not silently re-authenticate on it (gap B4).
POLICY_VIOLATION = 1008


class FrameError(Exception):
    """A frame that cannot be handled. The socket stays open and is told why."""


async def _receive_text(websocket: WebSocket) -> str:
    """Read one text frame, raising `FrameError` for a binary one.

    `WebSocket.receive_text` raises `KeyError` on binary frames; a client that
    sends one deserves an error frame, not a crashed connection.
    """
    message = await websocket.receive()
    if message["type"] == "websocket.disconnect":
        raise WebSocketDisconnect(message["code"])
    if message.get("text") is None:
        raise FrameError("binary frames are not supported")
    return message["text"]


def _decode_frame(raw: str) -> dict:
    """Parse a frame into an object, or explain why it is not one."""
    try:
        frame = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FrameError("frames must be JSON objects") from exc
    if not isinstance(frame, dict):
        raise FrameError("frames must be JSON objects")
    return frame

async def _user_from_token(token: object) -> models.User | None:
    """The user an auth-frame token names, or `None` when it names nobody."""
    if not isinstance(token, str) or not token:
        return None
    user_id = user_id_from_token(token)
    if user_id is None:
        return None
    async with SessionLocal() as db:
        return await db.get(models.User, user_id)


async def _user_from_first_frame(raw: str) -> models.User | None:
    """The user named by an auth frame, or `None` when the first frame is not one.

    A `FrameError` propagates so a malformed first frame is answered with the
    reason its bytes deserve; a well-formed frame that simply is not an auth
    frame (a message, a ping) is a failed handshake. Either way nothing is
    stored, nothing is echoed, and the socket never enters the registry (B3).
    """
    frame = _decode_frame(raw)
    if frame.get("type") != "auth":
        return None
    return await _user_from_token(frame.get("token"))


async def _close_with_policy_violation(websocket: WebSocket, detail: str) -> None:
    """Say why, then close with 1008 — the client's cue not to retry (gap B4)."""
    with contextlib.suppress(RuntimeError):
        await websocket.send_json(realtime.error_frame(detail))
        await websocket.close(code=POLICY_VIOLATION)


async def _handle_frame(websocket: WebSocket, user_id: int, raw: str) -> None:
    """Handle one frame from an authenticated socket.

    Raised `FrameError`s are the caller's to report; every rejection is an error
    frame on the same socket, never a crash and never a silent drop.
    """
    frame = _decode_frame(raw)
    frame_type = frame.get("type")

    if frame_type == "ping":
        await websocket.send_json(realtime.pong_frame())
        return

    if frame_type != "message":
        raise FrameError(f"unsupported frame type: {frame_type!r}")

    # The same model the REST route validates with, so both transports accept and
    # reject exactly the same text, length limit included (Q38).
    try:
        payload = schemas.MessageCreate(text=frame.get("text"))
    except ValidationError as exc:
        raise FrameError("text must be a string of at most 4000 characters") from exc

    async with SessionLocal() as db:
        message = await crud.create_message(db, user_id=user_id, text=payload.text)

    # Sent to every socket of the author, this one included: the echo is how the
    # sender learns the id and the authoritative timestamp of what it sent.
    # `client_id` returns untouched so the sending tab can match the frame (F11).
    client_id = frame.get("client_id")
    await manager.send_to_user(
        user_id,
        realtime.message_frame(message, client_id if isinstance(client_id, str) else None),
    )


@router.websocket("/ws/chat")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()

    try:
        raw = await asyncio.wait_for(_receive_text(websocket), timeout=AUTH_TIMEOUT_SECONDS)
    except TimeoutError:
        await _close_with_policy_violation(websocket, "authentication timed out")
        return
    except WebSocketDisconnect:
        return
    except FrameError as error:
        await _close_with_policy_violation(websocket, str(error))
        return

    try:
        user = await _user_from_first_frame(raw)
    except FrameError as error:
        # The first frame was not even a frame; say what was wrong with the bytes.
        await _close_with_policy_violation(websocket, str(error))
        return

    if user is None:
        await _close_with_policy_violation(websocket, "authentication failed")
        return

    # Registered only after the handshake, so fan-out can never reach a socket
    # that has not proved who it is. `auth_ok` carries the id the client checks
    # against its own session before trusting the stream.
    await manager.connect(websocket, user.id)
    await websocket.send_json(realtime.auth_ok_frame(user.id))

    try:
        while True:
            try:
                await _handle_frame(websocket, user.id, await _receive_text(websocket))
            except FrameError as error:
                await websocket.send_json(realtime.error_frame(str(error)))
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(websocket, user.id)