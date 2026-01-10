"""
Rooms Router for ScreenShare Pro

Bu modul, oda yonetimi ve guest erisim endpoint'lerini icerir.
"""
from uuid import UUID
import secrets
import time
from typing import Annotated
from fastapi import APIRouter, Depends, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.services.room_service import RoomService
from app.services.redis_state import get_redis_state
from app.schemas.room import (
    RoomCreate, RoomResponse, RoomDetailResponse, ParticipantResponse,
    GuestJoinRequest, GuestJoinResponse, GuestRoomCheck
)
from app.routers.auth import get_current_user
from app.models.user import User
from app.config import settings
from app.utils.rate_limit import rate_limit
from app.utils.logging_config import room_logger
from app.exceptions import (
    RoomNotFoundException,
    RoomInactiveException,
    RoomFullException,
    NotRoomHostException,
    PermissionDeniedException,
    InvalidInviteCodeException,
)

router = APIRouter(prefix="/api/rooms", tags=["Rooms"])

# Redis state service
redis_state = get_redis_state()

# Heartbeat timeout (30 saniye icinde heartbeat gelmezse offline say)
HEARTBEAT_TIMEOUT = 30


@router.post("/heartbeat")
@rate_limit(limit=60, window=60, identifier="heartbeat")
async def heartbeat(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)]
):
    """Kullanicinin aktif oldugunu bildir - 60 istek / dakika"""
    await redis_state.update_active_user(
        user_id=str(current_user.id),
        username=current_user.username,
        is_guest=False
    )
    return {"status": "ok"}


@router.get("/active-users")
@rate_limit(limit=30, window=60, identifier="active_users")
async def get_active_users(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)]
):
    """
    Tum aktif kullanicilari doner.
    Heartbeat bazli + WebSocket baglantilari birlestirilir.
    - 30 istek / dakika
    """
    from app.routers.websocket import manager

    result_users = {}

    # 1. Heartbeat bazli aktif kullanicilar (Redis'ten, timeout kontrolu ile)
    heartbeat_users = await redis_state.get_all_active_users(timeout=HEARTBEAT_TIMEOUT)
    for user_data in heartbeat_users:
        result_users[user_data["user_id"]] = user_data

    # 2. WebSocket'e bagli kullanicilar (odalarda olanlar)
    for room_id, users in manager.rooms.items():
        for user_id in users.keys():
            if user_id not in result_users:
                # Username'i Redis'ten al
                username = await redis_state.ws_get_username(user_id)
                result_users[user_id] = {
                    "user_id": user_id,
                    "username": username or "Bilinmiyor",
                    "room_id": room_id,
                    "is_guest": False
                }

    return {
        "total_active": len(result_users),
        "users": list(result_users.values())
    }


@router.get("/ice-config")
@rate_limit(limit=30, window=60, identifier="ice_config")
async def get_ice_config(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)]
):
    """
    WebRTC ICE Server konfigurasyonunu doner.
    Metered TURN API kullaniliyor.
    - 30 istek / dakika
    """
    # Metered API'den dinamik credentials al (opsiyonel, daha guvenli)
    if settings.METERED_API_KEY:
        import httpx
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{settings.METERED_API_URL}?apiKey={settings.METERED_API_KEY}"
                )
                if response.status_code == 200:
                    return {"iceServers": response.json()}
        except Exception as e:
            room_logger.warning(
                f"Failed to get dynamic ICE config, using static fallback",
                extra={"error": str(e)}
            )

    # Static config (fallback)
    return {
        "iceServers": [
            {"urls": settings.STUN_SERVER},
            {
                "urls": "turn:standard.relay.metered.ca:80",
                "username": settings.TURN_USERNAME,
                "credential": settings.TURN_CREDENTIAL,
            },
            {
                "urls": "turn:standard.relay.metered.ca:80?transport=tcp",
                "username": settings.TURN_USERNAME,
                "credential": settings.TURN_CREDENTIAL,
            },
            {
                "urls": settings.TURN_SERVER,
                "username": settings.TURN_USERNAME,
                "credential": settings.TURN_CREDENTIAL,
            },
            {
                "urls": settings.TURN_SERVER_TCP,
                "username": settings.TURN_USERNAME,
                "credential": settings.TURN_CREDENTIAL,
            },
        ],
    }


@router.post("", response_model=RoomResponse, status_code=status.HTTP_201_CREATED)
@rate_limit(limit=10, window=60, identifier="create_room")
async def create_room(
    request: Request,
    room_data: RoomCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """Oda olustur - 10 istek / dakika"""
    room_service = RoomService(db)
    room = await room_service.create_room(room_data, current_user.id)
    participants = await room_service.get_active_participants(room.id)

    room_logger.info(
        f"Room creation request completed",
        extra={
            "room_id": str(room.id),
            "room_name": room.name,
            "host_id": str(current_user.id),
            "host_username": current_user.username
        }
    )

    return RoomResponse(
        id=room.id,
        name=room.name,
        invite_code=room.invite_code,
        host_id=room.host_id,
        max_viewers=room.max_viewers,
        status=room.status,
        created_at=room.created_at,
        participant_count=len(participants)
    )


@router.get("", response_model=list[RoomResponse])
@rate_limit(limit=60, window=60, identifier="list_rooms")
async def get_rooms(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """Tum aktif odalari ve kullanicinin kendi odalarini getir - 60 istek / dakika"""
    from sqlalchemy import select

    room_service = RoomService(db)

    # Tum aktif odalari al
    active_rooms = await room_service.get_all_active_rooms()

    # Kullanicinin kend bitmis odalarini da al
    user_rooms = await room_service.get_user_rooms(current_user.id)

    # Birlestir (aktif odalar + kullanicinin bitmis odalari)
    all_rooms = {str(r.id): r for r in active_rooms}
    for room in user_rooms:
        if str(room.id) not in all_rooms:
            all_rooms[str(room.id)] = room

    # Host bilgilerini toplu al
    host_ids = list(set(r.host_id for r in all_rooms.values()))
    host_result = await db.execute(select(User).where(User.id.in_(host_ids)))
    hosts = {str(h.id): h.username for h in host_result.scalars().all()}

    result = []
    for room in sorted(all_rooms.values(), key=lambda x: x.created_at, reverse=True):
        participants = await room_service.get_active_participants(room.id)
        result.append(RoomResponse(
            id=room.id,
            name=room.name,
            invite_code=room.invite_code,
            host_id=room.host_id,
            host_name=hosts.get(str(room.host_id), "Bilinmiyor"),
            max_viewers=room.max_viewers,
            status=room.status,
            created_at=room.created_at,
            participant_count=len(participants)
        ))
    return result


@router.get("/{room_id}", response_model=RoomDetailResponse)
@rate_limit(limit=60, window=60, identifier="get_room")
async def get_room(
    request: Request,
    room_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """
    Oda detayi - 60 istek / dakika.

    Raises:
        RoomNotFoundException: Oda bulunamazsa
    """
    room_service = RoomService(db)
    room = await room_service.get_room_by_id(room_id)

    if not room:
        raise RoomNotFoundException()

    participants = await room_service.get_active_participants(room_id)
    participant_responses = [
        ParticipantResponse(
            id=p.id,
            user_id=p.user_id,
            username=p.user.username,
            role=p.role,
            joined_at=p.joined_at
        ) for p in participants
    ]

    return RoomDetailResponse(
        id=room.id,
        name=room.name,
        invite_code=room.invite_code,
        host_id=room.host_id,
        max_viewers=room.max_viewers,
        status=room.status,
        created_at=room.created_at,
        participants=participant_responses
    )


@router.get("/join/{invite_code}", response_model=RoomDetailResponse)
@rate_limit(limit=30, window=60, identifier="join_room")
async def join_room_by_code(
    request: Request,
    invite_code: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """
    Odaya katil - 30 istek / dakika.

    Raises:
        InvalidInviteCodeException: Davet kodu gecersizse
        RoomInactiveException: Oda aktif degilse
        RoomFullException: Oda dolduysa
    """
    room_service = RoomService(db)
    room = await room_service.get_room_by_invite_code(invite_code)

    if not room:
        raise InvalidInviteCodeException()

    if room.status != "active":
        raise RoomInactiveException()

    # Odaya katil
    participant = await room_service.join_room(room, current_user.id)
    if participant is None:
        # Zaten katilmis olabilir, kontrol et
        participants = await room_service.get_active_participants(room.id)
        is_member = any(p.user_id == current_user.id for p in participants)
        if not is_member:
            raise RoomFullException()

    room_logger.info(
        f"User joined room",
        extra={
            "room_id": str(room.id),
            "user_id": str(current_user.id),
            "username": current_user.username
        }
    )

    participants = await room_service.get_active_participants(room.id)
    participant_responses = [
        ParticipantResponse(
            id=p.id,
            user_id=p.user_id,
            username=p.user.username,
            role=p.role,
            joined_at=p.joined_at
        ) for p in participants
    ]

    return RoomDetailResponse(
        id=room.id,
        name=room.name,
        invite_code=room.invite_code,
        host_id=room.host_id,
        max_viewers=room.max_viewers,
        status=room.status,
        created_at=room.created_at,
        participants=participant_responses
    )


@router.delete("/{room_id}", status_code=status.HTTP_204_NO_CONTENT)
@rate_limit(limit=20, window=60, identifier="delete_room")
async def delete_room(
    request: Request,
    room_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """
    Odayi kalici olarak sil (sadece host veya admin) - 20 istek / dakika.

    Raises:
        RoomNotFoundException: Oda bulunamazsa
        NotRoomHostException: Yetkisiz silme denemesi
    """
    room_service = RoomService(db)
    room = await room_service.get_room_by_id(room_id)

    if not room:
        raise RoomNotFoundException()

    # Sadece host veya admin silebilir
    is_admin = current_user.role == "admin"
    is_host = room.host_id == current_user.id

    if not is_host and not is_admin:
        raise NotRoomHostException()

    # Aktif odayi silmeye calisiyorsa once sonlandir
    if room.status == "active":
        await room_service.end_room(room_id, current_user.id)

    # Odayi sil
    await room_service.delete_room(room_id)

    room_logger.info(
        f"Room deleted",
        extra={
            "room_id": str(room_id),
            "deleted_by": str(current_user.id),
            "was_active": room.status == "active"
        }
    )


@router.post("/{room_id}/leave", status_code=status.HTTP_204_NO_CONTENT)
@rate_limit(limit=30, window=60, identifier="leave_room")
async def leave_room(
    request: Request,
    room_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """Odayi terk et - 30 istek / dakika"""
    room_service = RoomService(db)
    await room_service.leave_room(room_id, current_user.id)

    room_logger.info(
        f"User left room",
        extra={
            "room_id": str(room_id),
            "user_id": str(current_user.id),
            "username": current_user.username
        }
    )


@router.post("/{room_id}/kick/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
@rate_limit(limit=30, window=60, identifier="kick_user")
async def kick_user(
    request: Request,
    room_id: UUID,
    user_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """
    Kullanicidy odadan at - 30 istek / dakika.

    Raises:
        PermissionDeniedException: Islem yapma yetkisi yoksa
    """
    room_service = RoomService(db)
    success = await room_service.kick_participant(room_id, current_user.id, user_id)

    if not success:
        raise PermissionDeniedException("Bu islemi yapma yetkiniz yok")

    room_logger.info(
        f"User kicked from room",
        extra={
            "room_id": str(room_id),
            "kicked_user_id": str(user_id),
            "kicked_by": str(current_user.id)
        }
    )


# ==================== GUEST ENDPOINTS ====================

@router.get("/guest/check/{invite_code}", response_model=GuestRoomCheck)
@rate_limit(limit=30, window=60, identifier="guest_check")
async def check_room_for_guest(
    request: Request,
    invite_code: str,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """
    Misafir icin oda durumunu kontrol et - 30 istek / dakika.

    Raises:
        InvalidInviteCodeException: Davet kodu gecersizse
        RoomInactiveException: Oda aktif degilse
    """
    room_service = RoomService(db)
    room = await room_service.get_room_by_invite_code(invite_code)

    if not room:
        raise InvalidInviteCodeException("Yayin bulunamadi")

    if room.status != "active":
        raise RoomInactiveException("Bu yayin sona ermis")

    # Host bilgisini al
    from sqlalchemy import select
    from app.models.user import User
    result = await db.execute(select(User).where(User.id == room.host_id))
    host = result.scalar_one_or_none()

    # Mevcut izleyici sayisi
    participants = await room_service.get_active_participants(room.id)
    viewer_count = len([p for p in participants if p.role == "viewer"])

    return GuestRoomCheck(
        name=room.name,
        status=room.status,
        host_name=host.username if host else "Bilinmiyor",
        current_viewers=viewer_count,
        max_viewers=room.max_viewers
    )


@router.post("/guest/join/{invite_code}", response_model=GuestJoinResponse)
@rate_limit(limit=10, window=60, identifier="guest_join")
async def join_as_guest(
    request: Request,
    invite_code: str,
    data: GuestJoinRequest,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """
    Misafir olarak yayina katil - 10 istek / dakika.

    Raises:
        InvalidInviteCodeException: Davet kodu gecersizse
        RoomInactiveException: Oda aktif degilse
        RoomFullException: Oda dolduysa
    """
    room_service = RoomService(db)
    room = await room_service.get_room_by_invite_code(invite_code)

    if not room:
        raise InvalidInviteCodeException("Yayin bulunamadi")

    if room.status != "active":
        raise RoomInactiveException("Bu yayin sona ermis")

    # Kapasite kontrolu
    participants = await room_service.get_active_participants(room.id)
    viewer_count = len([p for p in participants if p.role == "viewer"])

    # Guest'leri de say (Redis'ten)
    guest_count = await redis_state.get_room_guest_count(str(room.id))
    total_viewers = viewer_count + guest_count

    if total_viewers >= room.max_viewers:
        raise RoomFullException()

    # Guest token olustur ve Redis'e kaydet
    guest_token = secrets.token_urlsafe(32)
    await redis_state.set_guest_session(
        token=guest_token,
        room_id=str(room.id),
        guest_name=data.guest_name
    )

    room_logger.info(
        f"Guest joined room",
        extra={
            "room_id": str(room.id),
            "guest_name": data.guest_name,
            "token_prefix": guest_token[:8]
        }
    )

    return GuestJoinResponse(
        guest_token=guest_token,
        room_id=room.id,
        room_name=room.name,
        guest_name=data.guest_name
    )


async def get_guest_session(token: str) -> dict | None:
    """Guest token'dan session bilgisi al (Redis'ten)"""
    return await redis_state.get_guest_session(token)


async def remove_guest_session(token: str):
    """Guest session'i sil (Redis'ten)"""
    await redis_state.delete_guest_session(token)
