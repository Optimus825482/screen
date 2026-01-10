import json
from uuid import UUID
from typing import Dict, Set, Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db, async_session
from app.services.auth_service import AuthService
from app.services.room_service import RoomService
from app.services.diagram_service import DiagramService
from app.routers.rooms import get_guest_session, remove_guest_session
from app.utils.logging_config import websocket_logger, get_logger
from app.error_handlers import WebSocketErrorHandler
from app.utils.rate_limit import check_websocket_rate_limit, cleanup_websocket_rate_limit

logger = get_logger(__name__)

router = APIRouter(tags=["WebSocket"])


class ConnectionManager:
    """WebRTC Signaling ve Chat için bağlantı yöneticisi"""

    def __init__(self):
        # room_id -> {user_id -> WebSocket}
        self.rooms: Dict[str, Dict[str, WebSocket]] = {}
        # user_id -> username
        self.usernames: Dict[str, str] = {}
        # user_id -> is_guest
        self.guests: Dict[str, bool] = {}
        # user_id -> guest_token (for cleanup)
        self.guest_tokens: Dict[str, str] = {}
        # room_id -> {presenter_id -> {share_type, username}} (max 2 presenter)
        self.presenters: Dict[str, Dict[str, dict]] = {}
        # room_id -> [shared_files]
        self.shared_files: Dict[str, list] = {}

    async def connect(self, websocket: WebSocket, room_id: str, user_id: str, username: str, is_guest: bool = False, guest_token: str = None):
        await websocket.accept()
        if room_id not in self.rooms:
            self.rooms[room_id] = {}
            self.presenters[room_id] = {}
            self.shared_files[room_id] = []
        self.rooms[room_id][user_id] = websocket
        self.usernames[user_id] = username
        self.guests[user_id] = is_guest
        if guest_token:
            self.guest_tokens[user_id] = guest_token

        websocket_logger.info(
            f"User connected to room",
            extra={
                "room_id": room_id,
                "user_id": user_id,
                "username": username,
                "is_guest": is_guest,
                "room_participants": len(self.rooms[room_id])
            }
        )
    
    def disconnect(self, room_id: str, user_id: str):
        username = self.usernames.get(user_id, "unknown")
        if room_id in self.rooms and user_id in self.rooms[room_id]:
            del self.rooms[room_id][user_id]
            if not self.rooms[room_id]:
                del self.rooms[room_id]
                if room_id in self.presenters:
                    del self.presenters[room_id]
                if room_id in self.shared_files:
                    del self.shared_files[room_id]
        # Presenter listesinden çıkar
        if room_id in self.presenters and user_id in self.presenters[room_id]:
            del self.presenters[room_id][user_id]
        if user_id in self.usernames:
            del self.usernames[user_id]
        if user_id in self.guests:
            del self.guests[user_id]
        # Guest token cleanup
        if user_id in self.guest_tokens:
            remove_guest_session(self.guest_tokens[user_id])
            del self.guest_tokens[user_id]

        # Rate limit cleanup
        cleanup_websocket_rate_limit(user_id)

        websocket_logger.info(
            f"User disconnected from room",
            extra={
                "room_id": room_id,
                "user_id": user_id,
                "username": username
            }
        )
    
    def add_presenter(self, room_id: str, user_id: str, username: str, share_type: str) -> bool:
        """Presenter ekle, max 2 presenter kontrolü yapar"""
        if room_id not in self.presenters:
            self.presenters[room_id] = {}
        if len(self.presenters[room_id]) >= 2 and user_id not in self.presenters[room_id]:
            return False  # Max 2 presenter
        self.presenters[room_id][user_id] = {"username": username, "share_type": share_type}
        return True
    
    def remove_presenter(self, room_id: str, user_id: str):
        """Presenter'ı kaldır"""
        if room_id in self.presenters and user_id in self.presenters[room_id]:
            del self.presenters[room_id][user_id]
    
    def get_presenters(self, room_id: str) -> dict:
        """Odadaki presenter'ları döndür"""
        return self.presenters.get(room_id, {})
    
    def add_shared_file(self, room_id: str, file_info: dict):
        """Paylaşılan dosya ekle"""
        if room_id not in self.shared_files:
            self.shared_files[room_id] = []
        self.shared_files[room_id].append(file_info)
    
    def get_shared_files(self, room_id: str) -> list:
        """Paylaşılan dosyaları döndür"""
        return self.shared_files.get(room_id, [])
    
    async def send_personal(self, message: dict, websocket: WebSocket):
        await websocket.send_json(message)
    
    async def broadcast_to_room(self, room_id: str, message: dict, exclude_user: str = None):
        """Odadaki tum kullanicilara mesaj gonder, basarisiz olanlari logla"""
        if room_id not in self.rooms:
            return

        failed_users = []
        for user_id, ws in self.rooms[room_id].items():
            if user_id != exclude_user:
                try:
                    await ws.send_json(message)
                except Exception as e:
                    # Basarisiz gonderimleri logla
                    failed_users.append(user_id)
                    WebSocketErrorHandler.log_websocket_error(
                        error=e,
                        room_id=room_id,
                        user_id=user_id,
                        message_type=message.get("type", "broadcast")
                    )

        # Basarisiz kullanici baglilarini temizle (opt-in cleanup)
        if failed_users:
            websocket_logger.warning(
                f"Failed to send message to some users in room",
                extra={
                    "room_id": room_id,
                    "failed_users": failed_users,
                    "failed_count": len(failed_users)
                }
            )
    
    async def send_to_user(self, room_id: str, target_user_id: str, message: dict):
        """Belirli bir kullaniciya mesaj gonder, hata durumunda logla"""
        if room_id not in self.rooms:
            websocket_logger.warning(
                f"Room not found for send_to_user",
                extra={"room_id": room_id, "target_user_id": target_user_id}
            )
            return

        if target_user_id not in self.rooms[room_id]:
            websocket_logger.warning(
                f"User not in room for send_to_user",
                extra={"room_id": room_id, "target_user_id": target_user_id}
            )
            return

        try:
            await self.rooms[room_id][target_user_id].send_json(message)
        except Exception as e:
            WebSocketErrorHandler.log_websocket_error(
                error=e,
                room_id=room_id,
                user_id=target_user_id,
                message_type=message.get("type", "send_to_user")
            )
    
    def get_room_users(self, room_id: str) -> list[dict]:
        if room_id not in self.rooms:
            return []
        return [
            {
                "user_id": uid, 
                "username": self.usernames.get(uid, "Unknown"),
                "is_guest": self.guests.get(uid, False)
            }
            for uid in self.rooms[room_id].keys()
        ]


manager = ConnectionManager()


@router.websocket("/ws/room/{room_id}")
async def websocket_room(
    websocket: WebSocket,
    room_id: str,
    token: str = Query(None),
    guest_token: str = Query(None)
):
    """
    WebSocket endpoint for room communication.
    Handles: WebRTC signaling, chat messages, presence updates
    Supports both authenticated users (token) and guests (guest_token)
    """
    async with async_session() as db:
        user = None
        user_id = None
        username = None
        is_host = False
        is_guest = False
        
        # Token doğrulama - önce normal token, sonra guest token
        if token:
            auth_service = AuthService(db)
            user = await auth_service.get_user_from_token(token)
            if user:
                user_id = str(user.id)
                username = user.username
        
        if not user and guest_token:
            # Guest token kontrolü
            guest_session = get_guest_session(guest_token)
            if guest_session and guest_session.get("room_id") == room_id:
                is_guest = True
                user_id = f"guest_{guest_token[:16]}"
                username = guest_session.get("guest_name", "Misafir")
        
        if not user_id:
            await websocket.close(code=4001, reason="Unauthorized")
            return
        
        # Oda kontrolü
        room_service = RoomService(db)
        room = await room_service.get_room_by_id(UUID(room_id))
        
        if not room or room.status != "active":
            await websocket.close(code=4004, reason="Room not found or ended")
            return
        
        if not is_guest:
            is_host = str(room.host_id) == user_id
        
        # Bağlantıyı kabul et
        await manager.connect(websocket, room_id, user_id, username, is_guest, guest_token if is_guest else None)
        
        # Odadaki diğer kullanıcılara bildir
        await manager.broadcast_to_room(room_id, {
            "type": "user_joined",
            "user_id": user_id,
            "username": username,
            "is_host": is_host,
            "is_guest": is_guest,
            "participants": manager.get_room_users(room_id)
        }, exclude_user=user_id)
        
        # Yeni kullanıcıya mevcut katılımcıları gönder
        await manager.send_personal({
            "type": "room_state",
            "room_id": room_id,
            "room_name": room.name,
            "host_id": str(room.host_id),
            "is_host": is_host,
            "is_guest": is_guest,
            "participants": manager.get_room_users(room_id),
            "presenters": manager.get_presenters(room_id),
            "shared_files": manager.get_shared_files(room_id)
        }, websocket)

        try:
            while True:
                data = await websocket.receive_json()
                msg_type = data.get("type")

                # Rate limiting based on message type
                rate_limit_type = "default"
                if msg_type == "chat":
                    rate_limit_type = "chat"
                elif msg_type in ("offer", "answer", "ice_candidate", "request_offer"):
                    rate_limit_type = "signaling"

                # Check rate limit
                is_allowed, error_msg = await check_websocket_rate_limit(
                    websocket, user_id, rate_limit_type
                )

                if not is_allowed:
                    await manager.send_personal({
                        "type": "rate_limit_exceeded",
                        "message": error_msg or "Rate limit exceeded"
                    }, websocket)
                    continue

                # Log all WebSocket messages (signaling, chat, etc.)
                websocket_logger.debug(
                    f"WebSocket message received",
                    extra={
                        "room_id": room_id,
                        "user_id": user_id,
                        "username": username,
                        "msg_type": msg_type
                    }
                )

                if msg_type == "chat":
                    # Chat mesajı
                    websocket_logger.info(
                        f"Chat message",
                        extra={
                            "room_id": room_id,
                            "user_id": user_id,
                            "username": username,
                            "message_length": len(data.get("message", ""))
                        }
                    )
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
                    else:
                        # Target yoksa host'a gönder (viewer audio için)
                        host_id = str(room.host_id)
                        if user_id != host_id:
                            await manager.send_to_user(room_id, host_id, {
                                "type": "ice_candidate",
                                "from": user_id,
                                "candidate": data.get("candidate")
                            })
                
                elif msg_type == "request_offer":
                    # Viewer, presenter'dan offer istiyor
                    # Target belirtilmişse ona, yoksa tüm odaya broadcast et
                    target = data.get("target")
                    if target:
                        await manager.send_to_user(room_id, target, {
                            "type": "request_offer",
                            "from": user_id,
                            "username": username
                        })
                    else:
                        # Tüm odaya broadcast et (presenter kim olursa olsun)
                        await manager.broadcast_to_room(room_id, {
                            "type": "request_offer",
                            "from": user_id,
                            "username": username
                        }, exclude_user=user_id)
                
                elif msg_type == "screen_share_started":
                    # Biri ekran/kamera paylaşımı başlattı (max 2 presenter)
                    share_type = data.get("share_type", "screen")
                    
                    # Presenter ekle (max 2 kontrolü)
                    if manager.add_presenter(room_id, user_id, username, share_type):
                        await manager.broadcast_to_room(room_id, {
                            "type": "screen_share_started",
                            "presenter_id": user_id,
                            "presenter_name": username,
                            "share_type": share_type,
                            "presenters": manager.get_presenters(room_id)
                        }, exclude_user=user_id)
                    else:
                        # Max presenter'a ulaşıldı
                        await manager.send_personal({
                            "type": "error",
                            "message": "Maksimum 2 kişi aynı anda ekran paylaşabilir"
                        }, websocket)
                
                elif msg_type == "screen_share_stopped":
                    # Paylaşım durduruldu
                    manager.remove_presenter(room_id, user_id)
                    await manager.broadcast_to_room(room_id, {
                        "type": "screen_share_stopped",
                        "presenter_id": user_id,
                        "presenters": manager.get_presenters(room_id)
                    }, exclude_user=user_id)
                
                elif msg_type == "annotation":
                    # Ekran üzerine çizim/işaretleme - TÜM kullanıcılara gönder (çizen dahil değil)
                    await manager.broadcast_to_room(room_id, {
                        "type": "annotation",
                        "user_id": user_id,
                        "username": username,
                        "presenterId": data.get("presenterId"),  # Hangi ekrana çiziliyor
                        "tool": data.get("tool"),  # pen, laser, highlight, eraser
                        "color": data.get("color"),
                        "size": data.get("size"),
                        "fromX": data.get("fromX"),
                        "fromY": data.get("fromY"),
                        "toX": data.get("toX"),
                        "toY": data.get("toY"),
                    }, exclude_user=user_id)
                
                elif msg_type == "file_share":
                    # Dosya paylaşımı - sadece file_id ile (Base64 yerine)
                    from app.routers.files import get_temp_file_info
                    file_id = data.get("file_id")
                    file_info = get_temp_file_info(file_id)

                    if file_info:
                        shared_file = {
                            "id": file_id,
                            "name": file_info["filename"],
                            "size": file_info["filesize"],
                            "type": file_info["content_type"],
                            "sender_id": user_id,
                            "sender_name": username,
                            "timestamp": data.get("timestamp")
                        }
                        manager.add_shared_file(room_id, shared_file)
                        await manager.broadcast_to_room(room_id, {
                            "type": "file_shared",
                            **shared_file
                        })
                    else:
                        # Dosya bulunamadı veya süresi dolmuş
                        await manager.send_personal({
                            "type": "error",
                            "message": "Dosya bulunamadı veya süresi dolmuş"
                        }, websocket)
                
                elif msg_type == "viewer_audio_offer":
                    # Viewer (guest) mikrofon açtı, host'a offer gönder
                    if is_guest or not is_host:
                        host_id = str(room.host_id)
                        await manager.send_to_user(room_id, host_id, {
                            "type": "viewer_audio_offer",
                            "from": user_id,
                            "username": username,
                            "sdp": data.get("sdp")
                        })
                
                elif msg_type == "viewer_audio_answer":
                    # Host, viewer'ın audio offer'ına answer veriyor
                    if is_host:
                        target = data.get("target")
                        if target:
                            await manager.send_to_user(room_id, target, {
                                "type": "viewer_audio_answer",
                                "from": user_id,
                                "sdp": data.get("sdp")
                            })
                
                elif msg_type == "viewer_audio_stopped":
                    # Viewer mikrofonu kapattı
                    host_id = str(room.host_id)
                    await manager.send_to_user(room_id, host_id, {
                        "type": "viewer_audio_stopped",
                        "from": user_id,
                        "username": username
                    })
                
                elif msg_type == "whiteboard_started":
                    # Biri whiteboard açtı
                    await manager.broadcast_to_room(room_id, {
                        "type": "whiteboard_started",
                        "user_id": user_id,
                        "username": username
                    }, exclude_user=user_id)
                
                elif msg_type == "whiteboard_stopped":
                    # Whiteboard kapatıldı
                    await manager.broadcast_to_room(room_id, {
                        "type": "whiteboard_stopped",
                        "user_id": user_id
                    }, exclude_user=user_id)
                
                elif msg_type == "whiteboard_draw":
                    # Whiteboard çizim verisi
                    await manager.broadcast_to_room(room_id, {
                        "type": "whiteboard_draw",
                        "user_id": user_id,
                        "fromX": data.get("fromX"),
                        "fromY": data.get("fromY"),
                        "toX": data.get("toX"),
                        "toY": data.get("toY"),
                        "color": data.get("color"),
                        "size": data.get("size")
                    }, exclude_user=user_id)
                
                elif msg_type == "whiteboard_clear":
                    # Whiteboard temizlendi
                    await manager.broadcast_to_room(room_id, {
                        "type": "whiteboard_clear",
                        "user_id": user_id
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
            websocket_logger.info(
                f"WebSocket disconnected",
                extra={
                    "room_id": room_id,
                    "user_id": user_id,
                    "username": username
                }
            )
        except Exception as e:
            websocket_logger.error(
                f"WebSocket error",
                extra={
                    "room_id": room_id,
                    "user_id": user_id,
                    "username": username,
                    "error": str(e),
                    "error_type": type(e).__name__
                }
            )
        finally:
            manager.disconnect(room_id, user_id)
            # Diğer kullanıcılara bildir
            await manager.broadcast_to_room(room_id, {
                "type": "user_left",
                "user_id": user_id,
                "username": username,
                "participants": manager.get_room_users(room_id)
            })


# ============================================
# EXCALIDRAW COLLABORATIVE EDITING
# ============================================

class DiagramConnectionManager:
    """Excalidraw için real-time collaboration yöneticisi"""
    
    def __init__(self):
        # diagram_id -> {user_id -> WebSocket}
        self.diagrams: Dict[str, Dict[str, WebSocket]] = {}
        # user_id -> username
        self.usernames: Dict[str, str] = {}
        # diagram_id -> current content (memory cache)
        self.content_cache: Dict[str, str] = {}
        # diagram_id -> cursor positions {user_id -> {line, column}}
        self.cursors: Dict[str, Dict[str, dict]] = {}
    
    async def connect(self, websocket: WebSocket, diagram_id: str, user_id: str, username: str):
        await websocket.accept()
        if diagram_id not in self.diagrams:
            self.diagrams[diagram_id] = {}
            self.cursors[diagram_id] = {}
        self.diagrams[diagram_id][user_id] = websocket
        self.usernames[user_id] = username
    
    def disconnect(self, diagram_id: str, user_id: str):
        if diagram_id in self.diagrams and user_id in self.diagrams[diagram_id]:
            del self.diagrams[diagram_id][user_id]
            if not self.diagrams[diagram_id]:
                del self.diagrams[diagram_id]
                if diagram_id in self.content_cache:
                    del self.content_cache[diagram_id]
                if diagram_id in self.cursors:
                    del self.cursors[diagram_id]
        if diagram_id in self.cursors and user_id in self.cursors[diagram_id]:
            del self.cursors[diagram_id][user_id]
        if user_id in self.usernames:
            del self.usernames[user_id]
        # Rate limit cleanup
        cleanup_websocket_rate_limit(user_id)

    async def broadcast_to_diagram(self, diagram_id: str, message: dict, exclude_user: str = None):
        """Diagramdaki tum kullanicilara mesaj gonder, basarisiz olanlari logla"""
        if diagram_id not in self.diagrams:
            return

        failed_users = []
        for user_id, ws in list(self.diagrams[diagram_id].items()):
            if user_id != exclude_user:
                try:
                    await ws.send_json(message)
                except Exception as e:
                    # Basarisiz gonderimleri logla
                    failed_users.append(user_id)
                    WebSocketErrorHandler.log_websocket_error(
                        error=e,
                        message_type=message.get("type", "broadcast_diagram")
                    )

        if failed_users:
            websocket_logger.warning(
                f"Failed to send message to some users in diagram",
                extra={
                    "diagram_id": diagram_id,
                    "failed_users": failed_users,
                    "failed_count": len(failed_users)
                }
            )
    
    async def send_personal(self, message: dict, websocket: WebSocket):
        await websocket.send_json(message)
    
    def get_diagram_users(self, diagram_id: str) -> list[dict]:
        if diagram_id not in self.diagrams:
            return []
        return [
            {"user_id": uid, "username": self.usernames.get(uid, "Unknown")}
            for uid in self.diagrams[diagram_id].keys()
        ]
    
    def set_content(self, diagram_id: str, content: str):
        self.content_cache[diagram_id] = content
    
    def get_content(self, diagram_id: str) -> str | None:
        return self.content_cache.get(diagram_id)
    
    def set_cursor(self, diagram_id: str, user_id: str, position: dict):
        if diagram_id not in self.cursors:
            self.cursors[diagram_id] = {}
        self.cursors[diagram_id][user_id] = position
    
    def get_cursors(self, diagram_id: str) -> dict:
        return self.cursors.get(diagram_id, {})


diagram_manager = DiagramConnectionManager()


@router.websocket("/ws/diagram/{diagram_id}")
async def websocket_diagram(
    websocket: WebSocket,
    diagram_id: str,
    token: str = Query(None)
):
    """
    WebSocket endpoint for collaborative Excalidraw editing.
    Handles: content sync, cursor positions, presence updates
    """
    async with async_session() as db:
        user = None
        user_id = None
        username = None
        
        # Token doğrulama
        if token:
            auth_service = AuthService(db)
            user = await auth_service.get_user_from_token(token)
            if user:
                user_id = str(user.id)
                username = user.username
        
        if not user_id:
            await websocket.close(code=4001, reason="Unauthorized")
            return
        
        # Diagram kontrolü
        diagram_service = DiagramService(db)
        diagram = await diagram_service.get_diagram_by_id(UUID(diagram_id))
        
        if not diagram:
            await websocket.close(code=4004, reason="Diagram not found")
            return
        
        # Bağlantıyı kabul et
        await diagram_manager.connect(websocket, diagram_id, user_id, username)
        
        # Cache'de content yoksa DB'den al
        if not diagram_manager.get_content(diagram_id):
            diagram_manager.set_content(diagram_id, diagram.content)
        
        # Diğer kullanıcılara bildir
        await diagram_manager.broadcast_to_diagram(diagram_id, {
            "type": "user_joined",
            "user_id": user_id,
            "username": username,
            "participants": diagram_manager.get_diagram_users(diagram_id)
        }, exclude_user=user_id)
        
        # Yeni kullanıcıya mevcut state'i gönder
        await diagram_manager.send_personal({
            "type": "diagram_state",
            "diagram_id": diagram_id,
            "diagram_name": diagram.name,
            "content": diagram_manager.get_content(diagram_id),
            "participants": diagram_manager.get_diagram_users(diagram_id),
            "cursors": diagram_manager.get_cursors(diagram_id)
        }, websocket)
        
        try:
            while True:
                data = await websocket.receive_json()
                msg_type = data.get("type")

                # Rate limiting based on message type
                rate_limit_type = "default"
                if msg_type == "content_update":
                    rate_limit_type = "content_update"
                elif msg_type == "cursor_update":
                    rate_limit_type = "cursor_update"

                # Check rate limit
                is_allowed, error_msg = await check_websocket_rate_limit(
                    websocket, user_id, rate_limit_type
                )

                if not is_allowed:
                    await diagram_manager.send_personal({
                        "type": "rate_limit_exceeded",
                        "message": error_msg or "Rate limit exceeded"
                    }, websocket)
                    continue

                if msg_type == "content_update":
                    # İçerik güncellendi
                    content = data.get("content", "")
                    diagram_manager.set_content(diagram_id, content)
                    
                    # Diğer kullanıcılara broadcast
                    await diagram_manager.broadcast_to_diagram(diagram_id, {
                        "type": "content_update",
                        "user_id": user_id,
                        "username": username,
                        "content": content
                    }, exclude_user=user_id)
                
                elif msg_type == "cursor_update":
                    # Cursor pozisyonu güncellendi
                    position = data.get("position", {})
                    diagram_manager.set_cursor(diagram_id, user_id, position)
                    
                    await diagram_manager.broadcast_to_diagram(diagram_id, {
                        "type": "cursor_update",
                        "user_id": user_id,
                        "username": username,
                        "position": position
                    }, exclude_user=user_id)
                
                elif msg_type == "save":
                    # Diagram'ı kaydet
                    content = diagram_manager.get_content(diagram_id)
                    if content:
                        async with async_session() as db2:
                            diagram_service2 = DiagramService(db2)
                            await diagram_service2.update_diagram(
                                diagram_id=UUID(diagram_id),
                                content=content
                            )
                        
                        await diagram_manager.broadcast_to_diagram(diagram_id, {
                            "type": "saved",
                            "user_id": user_id,
                            "username": username
                        })
                
                elif msg_type == "ping":
                    await diagram_manager.send_personal({"type": "pong"}, websocket)
        
        except WebSocketDisconnect:
            websocket_logger.info(
                f"Diagram WebSocket disconnected",
                extra={
                    "diagram_id": diagram_id,
                    "user_id": user_id,
                    "username": username
                }
            )
        except Exception as e:
            websocket_logger.error(
                f"Diagram WebSocket error",
                extra={
                    "diagram_id": diagram_id,
                    "user_id": user_id,
                    "username": username,
                    "error": str(e),
                    "error_type": type(e).__name__
                }
            )
        finally:
            diagram_manager.disconnect(diagram_id, user_id)
            # Diğer kullanıcılara bildir
            await diagram_manager.broadcast_to_diagram(diagram_id, {
                "type": "user_left",
                "user_id": user_id,
                "username": username,
                "participants": diagram_manager.get_diagram_users(diagram_id)
            })
