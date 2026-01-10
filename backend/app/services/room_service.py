from uuid import UUID
from datetime import datetime
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.models.room import Room, RoomParticipant
from app.models.user import User
from app.schemas.room import RoomCreate
from app.config import settings
from app.utils.logging_config import room_logger


class RoomService:
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create_room(self, room_data: RoomCreate, host_id: UUID) -> Room:
        room = Room(
            name=room_data.name,
            host_id=host_id,
            max_viewers=min(room_data.max_viewers, settings.MAX_VIEWERS_PER_ROOM)
        )
        self.db.add(room)
        await self.db.flush()

        # Host'u katılımcı olarak ekle
        participant = RoomParticipant(
            room_id=room.id,
            user_id=host_id,
            role="host"
        )
        self.db.add(participant)
        await self.db.flush()
        await self.db.refresh(room)

        room_logger.info(
            f"Room created",
            extra={
                "room_id": str(room.id),
                "room_name": room.name,
                "host_id": str(host_id),
                "invite_code": room.invite_code,
                "max_viewers": room.max_viewers
            }
        )
        return room
    
    async def get_room_by_id(self, room_id: UUID) -> Room | None:
        result = await self.db.execute(
            select(Room)
            .options(selectinload(Room.participants).selectinload(RoomParticipant.user))
            .where(Room.id == room_id)
        )
        return result.scalar_one_or_none()
    
    async def get_room_by_invite_code(self, invite_code: str) -> Room | None:
        result = await self.db.execute(
            select(Room)
            .options(selectinload(Room.participants))
            .where(Room.invite_code == invite_code, Room.status == "active")
        )
        return result.scalar_one_or_none()
    
    async def get_user_rooms(self, user_id: UUID) -> list[Room]:
        """Kullanıcının oluşturduğu odaları getir"""
        result = await self.db.execute(
            select(Room)
            .where(Room.host_id == user_id)
            .order_by(Room.created_at.desc())
        )
        return list(result.scalars().all())
    
    async def get_all_active_rooms(self) -> list[Room]:
        """Tüm aktif odaları getir"""
        result = await self.db.execute(
            select(Room)
            .where(Room.status == "active")
            .order_by(Room.created_at.desc())
        )
        return list(result.scalars().all())
    
    async def join_room(self, room: Room, user_id: UUID) -> RoomParticipant | None:
        # Zaten katılmış mı kontrol et
        existing = await self.db.execute(
            select(RoomParticipant)
            .where(RoomParticipant.room_id == room.id, RoomParticipant.user_id == user_id)
        )
        if existing.scalar_one_or_none():
            room_logger.debug(f"User already in room: {user_id}")
            return None

        # Viewer sayısını kontrol et
        viewer_count = await self.db.execute(
            select(func.count(RoomParticipant.id))
            .where(
                RoomParticipant.room_id == room.id,
                RoomParticipant.role == "viewer",
                RoomParticipant.left_at.is_(None)
            )
        )
        if viewer_count.scalar() >= room.max_viewers:
            room_logger.warning(
                f"Room is full",
                extra={
                    "room_id": str(room.id),
                    "room_name": room.name,
                    "user_id": str(user_id),
                    "max_viewers": room.max_viewers
                }
            )
            return None

        participant = RoomParticipant(
            room_id=room.id,
            user_id=user_id,
            role="viewer"
        )
        self.db.add(participant)
        await self.db.flush()
        await self.db.refresh(participant)

        room_logger.info(
            f"User joined room",
            extra={
                "room_id": str(room.id),
                "room_name": room.name,
                "user_id": str(user_id)
            }
        )
        return participant
    
    async def leave_room(self, room_id: UUID, user_id: UUID) -> bool:
        result = await self.db.execute(
            select(RoomParticipant)
            .where(RoomParticipant.room_id == room_id, RoomParticipant.user_id == user_id)
        )
        participant = result.scalar_one_or_none()
        if not participant:
            return False
        participant.left_at = datetime.utcnow()
        await self.db.flush()
        return True
    
    async def end_room(self, room_id: UUID, host_id: UUID) -> bool:
        room = await self.get_room_by_id(room_id)
        if not room or room.host_id != host_id:
            room_logger.warning(
                f"Unauthorized attempt to end room",
                extra={"room_id": str(room_id), "host_id": str(host_id)}
            )
            return False
        room.status = "ended"
        room.ended_at = datetime.utcnow()
        await self.db.flush()

        room_logger.info(
            f"Room ended",
            extra={
                "room_id": str(room_id),
                "room_name": room.name,
                "host_id": str(host_id)
            }
        )
        return True
    
    async def get_active_participants(self, room_id: UUID) -> list[RoomParticipant]:
        result = await self.db.execute(
            select(RoomParticipant)
            .options(selectinload(RoomParticipant.user))
            .where(RoomParticipant.room_id == room_id, RoomParticipant.left_at.is_(None))
        )
        return list(result.scalars().all())
    
    async def kick_participant(self, room_id: UUID, host_id: UUID, user_id: UUID) -> bool:
        room = await self.get_room_by_id(room_id)
        if not room or room.host_id != host_id:
            return False
        return await self.leave_room(room_id, user_id)

    async def delete_room(self, room_id: UUID) -> bool:
        """Odayı ve ilişkili katılımcıları kalıcı olarak sil"""
        # Önce katılımcıları sil
        await self.db.execute(
            RoomParticipant.__table__.delete().where(RoomParticipant.room_id == room_id)
        )
        # Sonra odayı sil
        result = await self.db.execute(
            select(Room).where(Room.id == room_id)
        )
        room = result.scalar_one_or_none()
        if room:
            await self.db.delete(room)
            await self.db.flush()
            return True
        return False
