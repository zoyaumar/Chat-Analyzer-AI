"""The realtime channel: the wire contract plus the in-process fan-out (gap B1).

Two things live here because both are shared by every writer of a message:

* the **frame builders** — one place that decides what a client receives, used
  by the WebSocket handler and by the REST route that creates a message;
* the **connection registry** — sockets grouped by user id.

Grouping by user id is deliberate. Every REST read is scoped to the author
(`GET /messages/` returns *your* messages, gap S2), so a message may only be
pushed to connections that are allowed to see it: fan-out is per user, not to
everyone. When conversations land (gap P1) the grouping key becomes the
conversation id and the envelope does not change.

Broadcasting to *every* connected client instead — a public/global timeline — is a
product decision rather than the default, because it would push messages a reader
cannot fetch again (S2). It is listed as a future feature (gap P16) and is not
implemented here.

One process, one registry (gap Q18): the fan-out is in memory, and `send_to_user`
is best effort — a socket that fails to receive is dropped rather than blocking
the writer.
"""

import asyncio
from collections import defaultdict

from fastapi import WebSocket

from chat_backend import models, schemas


def message_frame(message: models.Message, client_id: str | None = None) -> dict:
    """The one shape a created message travels in, over any transport.

    `client_id` is echoed back untouched when the sender supplied one, so the
    sending tab can match the message it is waiting for; it is not persisted.
    """
    payload = {
        "type": "message",
        "message": schemas.MessageOut.model_validate(message).model_dump(mode="json"),
    }
    if client_id is not None:
        payload["client_id"] = client_id
    return payload


def message_deleted_frame(message_id: int, user_id: int) -> dict:
    """Announce a deletion so every socket of the owner drops the row.

    The id travels, not the row: handling a repeat is a no-op on the client, and
    a socket that never had the message simply ignores the frame.
    """
    return {"type": "message_deleted", "message_id": message_id, "user_id": user_id}


def auth_ok_frame(user_id: int) -> dict:
    return {"type": "auth_ok", "user_id": user_id}


def pong_frame() -> dict:
    return {"type": "pong"}


def error_frame(detail: str) -> dict:
    return {"type": "error", "detail": detail}


class ConnectionManager:
    """Tracks live sockets per user and fans a payload out to all of them."""

    def __init__(self) -> None:
        self._connections: dict[int, set[WebSocket]] = defaultdict(set)

    async def connect(self, websocket: WebSocket, user_id: int) -> None:
        self._connections[user_id].add(websocket)

    def disconnect(self, websocket: WebSocket, user_id: int) -> None:
        connections = self._connections.get(user_id)
        if not connections:
            return
        connections.discard(websocket)
        if not connections:
            del self._connections[user_id]

    def connection_count(self, user_id: int | None = None) -> int:
        """Diagnostics/test hook: live sockets in total, or for one user."""
        if user_id is not None:
            return len(self._connections.get(user_id, ()))
        return sum(len(sockets) for sockets in self._connections.values())

    async def send_to_user(self, user_id: int, payload: dict) -> None:
        """Send `payload` to every socket of `user_id`, dropping dead ones.

        The set is copied before awaiting: a disconnect that happens while the
        sends are in flight cannot mutate what we are iterating over. There is
        no lock because the registry is only ever touched from the event loop's
        own callbacks, never from a thread.
        """
        targets = list(self._connections.get(user_id, ()))
        if not targets:
            return

        results = await asyncio.gather(
            *(socket.send_json(payload) for socket in targets),
            return_exceptions=True,
        )
        for socket, result in zip(targets, results, strict=True):
            if isinstance(result, Exception):
                self.disconnect(socket, user_id)


manager = ConnectionManager()
