from typing import Dict, List
from fastapi import WebSocket


class QueueConnectionManager:
    def __init__(self):
        # centre_id -> List[WebSocket]
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, centre_id: str, websocket: WebSocket):
        await websocket.accept()
        if centre_id not in self.active_connections:
            self.active_connections[centre_id] = []
        self.active_connections[centre_id].append(websocket)

    def disconnect(self, centre_id: str, websocket: WebSocket):
        if centre_id in self.active_connections:
            if websocket in self.active_connections[centre_id]:
                self.active_connections[centre_id].remove(websocket)
            if not self.active_connections[centre_id]:
                del self.active_connections[centre_id]

    async def broadcast_queue_update(self, centre_id: str, message: dict):
        if centre_id in self.active_connections:
            for connection in list(self.active_connections[centre_id]):
                try:
                    await connection.send_json(message)
                except Exception:
                    self.disconnect(centre_id, connection)


manager = QueueConnectionManager()
