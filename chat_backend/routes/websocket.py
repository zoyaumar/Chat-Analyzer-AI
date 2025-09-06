from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from jose import jwt, JWTError
from typing import List

from chat_backend.auth_utils import ALGORITHM, SECRET_KEY

router = APIRouter()

# Manage connections
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
    # token = websocket.query_params.get("token")
    # print("Token received:", token)

    # if not token:
    #     await websocket.close(code=1008)
    #     return

    # try:
    #     payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])    
    #     print("Decoded payload:", payload)

    #     user_id = payload.get("sub")
    #     if not user_id:
    #         print("⚠️ No user_id in token")
    #         await websocket.close(code=1008)
    #         return
    # except JWTError as e:
    #     print(f"⚠️ JWT error: {e}")
    #     await websocket.close(code=1008)
    #     return

    # await manager.connect(websocket)
    # print(f"✅ WebSocket connected: user {user_id}")

    # try:
    #     while True:
    #         data = await websocket.receive_text()
    #         print(f"Message from {user_id}: {data}")
    #         await manager.broadcast(f"{user_id}: {data}")
    # except WebSocketDisconnect:
    #     manager.disconnect(websocket)
    #     print(f"❌ WebSocket disconnected: user {user_id}")


    await websocket.accept()
    print("✅ WebSocket connected")

    try:
        while True:
            data = await websocket.receive_text()
            print("Got:", data)
            await websocket.send_text(f"You said: {data}")
    except WebSocketDisconnect:
        print("❌ WebSocket disconnected")