import json
from typing import List

import jwt
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from chat_backend.auth_utils import ALGORITHM
from chat_backend.config import settings

router = APIRouter()

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for conn in self.active_connections:
            await conn.send_text(message)


manager = ConnectionManager()

@router.websocket("/ws/chat")
async def websocket_endpoint(websocket: WebSocket):
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=1008)
        return

    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except jwt.InvalidTokenError:
        await websocket.close(code=1008)
        return
    if payload.get("sub") is None:
        await websocket.close(code=1008)
        return

    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            # Echo only (persistence + broadcast land with gap B1); reply with JSON
            # so the client's JSON.parse never throws (gap F3).
            await websocket.send_text(json.dumps({"text": data}))
    except WebSocketDisconnect:
        manager.disconnect(websocket)