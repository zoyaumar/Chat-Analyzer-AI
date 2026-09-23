import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from chat_backend.auth_utils import create_access_token
from chat_backend.main import app


def test_websocket_rejects_missing_token():
    # No token: the server closes with 1008 before accepting the handshake.
    with TestClient(app) as client, pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/chat"):
            pass


def test_websocket_rejects_invalid_token():
    with TestClient(app) as client, pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/chat?token=garbage"):
            pass


def test_websocket_echoes_json_with_valid_token():
    token = create_access_token({"sub": "1"})
    with TestClient(app) as client:
        with client.websocket_connect(f"/ws/chat?token={token}") as ws:
            ws.send_text("ping")
            assert ws.receive_json() == {"text": "ping"}