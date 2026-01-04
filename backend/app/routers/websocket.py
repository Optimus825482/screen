import json
from uuid import UUID
from typing import Dict, Set
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db, async_session
from app.services.auth_service import AuthService
from app.services.room_service import RoomService

router = APIRouter(tags=["WebSocket"])


class ConnectionManager:
    """WebRTC Signaling ve Chat için bağlantı yöneticisi"""
    
    def __init__(self):
        # room_id -> {user_id -> WebSocket}
        self.rooms: Dict[str, Dict[str, WebSocket]] = {}
        # user_id -> username
        self.usernames: Dict[str, str] = {}
    
    async def connect(self, websocket: WebSocket, room_id: str, user_id: str, username: str):
        await websocket.accept()
        if room_id not in self.rooms:
            self.rooms[room_id] = {}
        self.rooms[room_id][user_id] = websocket
        self.usernames[user_id] = username
    
    def disconnect(self, room_id: str, user_id: str):
        if room_id in self.rooms and user_id in self.rooms[room_id]:
            del self.rooms[room_id][user_id]
            if not self.rooms[room_id]:
                del self.rooms[room_id]
        if user_id in self.usernames:
            del self.usernames[user_id]
    
    async def send_personal(self, message: dict, websocket: WebSocket):
        await websocket.send_json(message)
    
    async def broadcast_to_room(self, room_id: str, message: dict, exclude_user: str = None):
        if room_id not in self.rooms:
            return
        for user_id, ws in self.rooms[room_id].items():
            if user_id != exclude_user:
                try:
                    await ws.send_json(message)
                except:
                    pass
    
    async def send_to_user(self, room_id: str, target_user_id: str, message: dict):
        if room_id in self.rooms and target_user_id in self.rooms[room_id]:
            try:
                await self.rooms[room_id][target_user_id].send_json(message)
            except:
                pass
    
    def get_room_users(self, room_id: str) -> list[dict]:
        if room_id not in self.rooms:
            return []
        return [
            {"user_id": uid, "username": self.usernames.get(uid, "Unknown")}
            for uid in self.rooms[room_id].keys()
        ]


manager = ConnectionManager()


@router.websocket("/ws/room/{room_id}")
async def websocket_room(
    websocket: WebSocket,
    room_id: str,
    token: str = Query(...)
):
    """
    WebSocket endpoint for room communication.
    Handles: WebRTC signaling, chat messages, presence updates
    """
    async with async_session() as db:
        # Token doğrulama
        auth_service = AuthService(db)
        user = await auth_service.get_user_from_token(token)
        
        if not user:
            await websocket.close(code=4001, reason="Unauthorized")
            return
        
        # Oda kontrolü
        room_service = RoomService(db)
        room = await room_service.get_room_by_id(UUID(room_id))
        
        if not room or room.status != "active":
            await websocket.close(code=4004, reason="Room not found or ended")
            return
        
        user_id = str(user.id)
        username = user.username
        is_host = str(room.host_id) == user_id
        
        # Bağlantıyı kabul et
        await manager.connect(websocket, room_id, user_id, username)
        
        # Odadaki diğer kullanıcılara bildir
        await manager.broadcast_to_room(room_id, {
            "type": "user_joined",
            "user_id": user_id,
            "username": username,
            "is_host": is_host,
            "participants": manager.get_room_users(room_id)
        }, exclude_user=user_id)
        
        # Yeni kullanıcıya mevcut katılımcıları gönder
        await manager.send_personal({
            "type": "room_state",
            "room_id": room_id,
            "room_name": room.name,
            "host_id": str(room.host_id),
            "is_host": is_host,
            "participants": manager.get_room_users(room_id)
        }, websocket)
        
        try:
            while True:
                data = await websocket.receive_json()
                msg_type = data.get("type")
                
                if msg_type == "chat":
                    # Chat mesajı
                    await manager.broadcast_to_room(room_id, {
                        "type": "chat",
                        "user_id": user_id,
                        "username": username,
                        "message": data.get("message", ""),
                        "timestamp": data.get("timestamp")
                    })
                
                elif msg_type == "offer":
                    # WebRTC SDP Offer (host -> viewer)
                    target = data.get("target")
                    if target:
                        await manager.send_to_user(room_id, target, {
                            "type": "offer",
                            "from": user_id,
                            "sdp": data.get("sdp")
                        })
                
                elif msg_type == "answer":
                    # WebRTC SDP Answer (viewer -> host)
                    target = data.get("target")
                    if target:
                        await manager.send_to_user(room_id, target, {
                            "type": "answer",
                            "from": user_id,
                            "sdp": data.get("sdp")
                        })
                
                elif msg_type == "ice_candidate":
                    # ICE Candidate exchange
                    target = data.get("target")
                    if target:
                        await manager.send_to_user(room_id, target, {
                            "type": "ice_candidate",
                            "from": user_id,
                            "candidate": data.get("candidate")
                        })
                
                elif msg_type == "request_offer":
                    # Viewer, host'tan offer istiyor
                    host_id = str(room.host_id)
                    await manager.send_to_user(room_id, host_id, {
                        "type": "request_offer",
                        "from": user_id,
                        "username": username
                    })
                
                elif msg_type == "screen_share_started":
                    # Host ekran paylaşımı başlattı
                    if is_host:
                        await manager.broadcast_to_room(room_id, {
                            "type": "screen_share_started",
                            "host_id": user_id
                        }, exclude_user=user_id)
                
                elif msg_type == "screen_share_stopped":
                    # Host ekran paylaşımı durdurdu
                    if is_host:
                        await manager.broadcast_to_room(room_id, {
                            "type": "screen_share_stopped",
                            "host_id": user_id
                        }, exclude_user=user_id)
                
                elif msg_type == "kick_user":
                    # Host bir kullanıcıyı çıkarıyor
                    if is_host:
                        target = data.get("target")
                        if target and target != user_id:
                            await manager.send_to_user(room_id, target, {
                                "type": "kicked",
                                "reason": "Host tarafından çıkarıldınız"
                            })
                
                elif msg_type == "end_room":
                    # Host odayı sonlandırıyor
                    if is_host:
                        await manager.broadcast_to_room(room_id, {
                            "type": "room_ended",
                            "reason": "Host odayı sonlandırdı"
                        })
                        # Veritabanında odayı kapat
                        async with async_session() as db2:
                            room_service2 = RoomService(db2)
                            await room_service2.end_room(UUID(room_id), user.id)
                            await db2.commit()
                
                elif msg_type == "ping":
                    await manager.send_personal({"type": "pong"}, websocket)
        
        except WebSocketDisconnect:
            pass
        except Exception as e:
            print(f"WebSocket error: {e}")
        finally:
            manager.disconnect(room_id, user_id)
            # Diğer kullanıcılara bildir
            await manager.broadcast_to_room(room_id, {
                "type": "user_left",
                "user_id": user_id,
                "username": username,
                "participants": manager.get_room_users(room_id)
            })
