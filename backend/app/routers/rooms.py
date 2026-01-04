from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.services.room_service import RoomService
from app.schemas.room import RoomCreate, RoomResponse, RoomDetailResponse, ParticipantResponse
from app.routers.auth import get_current_user
from app.models.user import User
from app.config import settings

router = APIRouter(prefix="/api/rooms", tags=["Rooms"])


@router.get("/ice-config")
async def get_ice_config(current_user: User = Depends(get_current_user)):
    """
    WebRTC ICE Server konfigürasyonunu döner.
    Metered TURN API kullanılıyor.
    """
    # Metered API'den dinamik credentials al (opsiyonel, daha güvenli)
    if settings.METERED_API_KEY:
        import httpx
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{settings.METERED_API_URL}?apiKey={settings.METERED_API_KEY}"
                )
                if response.status_code == 200:
                    return {"iceServers": response.json()}
        except Exception:
            pass  # Fallback to static config
    
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
async def create_room(
    room_data: RoomCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    room_service = RoomService(db)
    room = await room_service.create_room(room_data, current_user.id)
    participants = await room_service.get_active_participants(room.id)
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
async def get_my_rooms(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    room_service = RoomService(db)
    rooms = await room_service.get_user_rooms(current_user.id)
    result = []
    for room in rooms:
        participants = await room_service.get_active_participants(room.id)
        result.append(RoomResponse(
            id=room.id,
            name=room.name,
            invite_code=room.invite_code,
            host_id=room.host_id,
            max_viewers=room.max_viewers,
            status=room.status,
            created_at=room.created_at,
            participant_count=len(participants)
        ))
    return result


@router.get("/{room_id}", response_model=RoomDetailResponse)
async def get_room(
    room_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    room_service = RoomService(db)
    room = await room_service.get_room_by_id(room_id)
    
    if not room:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Oda bulunamadı")
    
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
async def join_room_by_code(
    invite_code: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    room_service = RoomService(db)
    room = await room_service.get_room_by_invite_code(invite_code)
    
    if not room:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Oda bulunamadı veya sona ermiş")
    
    if room.status != "active":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Bu oda artık aktif değil")
    
    # Odaya katıl
    participant = await room_service.join_room(room, current_user.id)
    if participant is None:
        # Zaten katılmış olabilir, kontrol et
        participants = await room_service.get_active_participants(room.id)
        is_member = any(p.user_id == current_user.id for p in participants)
        if not is_member:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Oda dolu")
    
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
async def end_room(
    room_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    room_service = RoomService(db)
    success = await room_service.end_room(room_id, current_user.id)
    
    if not success:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Bu odayı sonlandırma yetkiniz yok")


@router.post("/{room_id}/leave", status_code=status.HTTP_204_NO_CONTENT)
async def leave_room(
    room_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    room_service = RoomService(db)
    await room_service.leave_room(room_id, current_user.id)


@router.post("/{room_id}/kick/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def kick_user(
    room_id: UUID,
    user_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    room_service = RoomService(db)
    success = await room_service.kick_participant(room_id, current_user.id, user_id)
    
    if not success:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Bu işlemi yapma yetkiniz yok")
