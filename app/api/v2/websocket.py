"""v2 WebSocket API for real-time updates."""

import asyncio
import json
import logging
from datetime import datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.redis_client import get_redis
from app.schemas.v2 import WSMessage, WSMessageType
from app.services.queued_reservation_service import get_queued_reservation_service

router = APIRouter()
logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages WebSocket connections."""

    def __init__(self):
        # request_id -> list of websockets
        self.active_connections: dict[str, list[WebSocket]] = {}
        # user_id -> list of websockets
        self.user_connections: dict[str, list[WebSocket]] = {}

    async def connect(
        self,
        websocket: WebSocket,
        request_id: str | None = None,
        user_id: str | None = None,
    ) -> None:
        """Accept and register a connection."""
        await websocket.accept()

        if request_id:
            if request_id not in self.active_connections:
                self.active_connections[request_id] = []
            self.active_connections[request_id].append(websocket)

        if user_id:
            if user_id not in self.user_connections:
                self.user_connections[user_id] = []
            self.user_connections[user_id].append(websocket)

    def disconnect(
        self,
        websocket: WebSocket,
        request_id: str | None = None,
        user_id: str | None = None,
    ) -> None:
        """Remove a connection."""
        if request_id and request_id in self.active_connections:
            self.active_connections[request_id] = [
                ws for ws in self.active_connections[request_id] if ws != websocket
            ]
            if not self.active_connections[request_id]:
                del self.active_connections[request_id]

        if user_id and user_id in self.user_connections:
            self.user_connections[user_id] = [
                ws for ws in self.user_connections[user_id] if ws != websocket
            ]
            if not self.user_connections[user_id]:
                del self.user_connections[user_id]

    async def send_to_request(self, request_id: str, message: WSMessage) -> None:
        """Send message to all connections watching a request."""
        if request_id in self.active_connections:
            message_data = message.model_dump_json()
            for websocket in self.active_connections[request_id]:
                try:
                    await websocket.send_text(message_data)
                except Exception as e:
                    logger.error(f"Error sending to websocket: {e}")

    async def send_to_user(self, user_id: str, message: WSMessage) -> None:
        """Send message to all connections for a user."""
        if user_id in self.user_connections:
            message_data = message.model_dump_json()
            for websocket in self.user_connections[user_id]:
                try:
                    await websocket.send_text(message_data)
                except Exception as e:
                    logger.error(f"Error sending to websocket: {e}")


# Global connection manager
manager = ConnectionManager()


@router.websocket("/reservation/{request_id}")
async def websocket_reservation_status(
    websocket: WebSocket,
    request_id: str,
):
    """
    WebSocket endpoint for real-time reservation status updates.
    
    Connect to receive live updates about your reservation request.
    
    Messages:
    - status_update: Status changed
    - queue_position: Position in queue updated
    - reservation_complete: Reservation successful
    - reservation_failed: Reservation failed
    """
    user_id = websocket.query_params.get("user_id")

    await manager.connect(websocket, request_id=request_id, user_id=user_id)

    try:
        # Get initial status
        service = await get_queued_reservation_service()
        status = await service.get_request_status(request_id)

        if status:
            await websocket.send_text(
                WSMessage(
                    type=WSMessageType.STATUS_UPDATE,
                    request_id=request_id,
                    data=status,
                ).model_dump_json()
            )

        # Keep connection alive and poll for updates
        last_status = status.get("status") if status else None

        while True:
            try:
                # Wait for client messages (ping/pong)
                # or timeout after 5 seconds to check status
                try:
                    data = await asyncio.wait_for(
                        websocket.receive_text(),
                        timeout=5.0,
                    )
                    # Handle client messages if needed
                    client_msg = json.loads(data)
                    if client_msg.get("type") == "ping":
                        await websocket.send_text(
                            json.dumps({"type": "pong", "timestamp": datetime.now().isoformat()})
                        )
                except asyncio.TimeoutError:
                    pass

                # Check for status updates
                current_status = await service.get_request_status(request_id)

                if current_status and current_status.get("status") != last_status:
                    last_status = current_status.get("status")

                    # Determine message type
                    if last_status == "completed":
                        msg_type = WSMessageType.RESERVATION_COMPLETE
                    elif last_status == "failed":
                        msg_type = WSMessageType.RESERVATION_FAILED
                    else:
                        msg_type = WSMessageType.STATUS_UPDATE

                    await websocket.send_text(
                        WSMessage(
                            type=msg_type,
                            request_id=request_id,
                            data=current_status,
                        ).model_dump_json()
                    )

                    # Close connection if terminal state
                    if last_status in ("completed", "failed"):
                        break

            except WebSocketDisconnect:
                break
            except Exception as e:
                logger.error(f"WebSocket error: {e}")
                await websocket.send_text(
                    WSMessage(
                        type=WSMessageType.ERROR,
                        request_id=request_id,
                        data={"error": str(e)},
                    ).model_dump_json()
                )
                break

    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(websocket, request_id=request_id, user_id=user_id)


@router.websocket("/user/{user_id}")
async def websocket_user_updates(
    websocket: WebSocket,
    user_id: str,
):
    """
    WebSocket endpoint for all updates for a user.
    
    Receive updates for all reservation requests made by this user.
    """
    await manager.connect(websocket, user_id=user_id)

    try:
        while True:
            try:
                data = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=30.0,
                )
                client_msg = json.loads(data)
                if client_msg.get("type") == "ping":
                    await websocket.send_text(
                        json.dumps({"type": "pong", "timestamp": datetime.now().isoformat()})
                    )
            except asyncio.TimeoutError:
                # Send keepalive
                await websocket.send_text(
                    json.dumps({"type": "keepalive", "timestamp": datetime.now().isoformat()})
                )
            except WebSocketDisconnect:
                break

    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(websocket, user_id=user_id)
