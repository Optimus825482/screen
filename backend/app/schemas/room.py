from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, Field


class RoomCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    max_viewers: int = Field(default=3, ge=1, le=10)


class RoomResponse(BaseModel):
    id: UUID
    name: str
    invite_code: str
    host_id: UUID
    max_viewers: int
    status: str
    created_at: datetime
    participant_count: int = 0
    
    class Config:
        from_attributes = True


class RoomJoin(BaseModel):
    invite_code: str


class ParticipantResponse(BaseModel):
    id: UUID
    user_id: UUID
    username: str
    role: str
    joined_at: datetime
    
    class Config:
        from_attributes = True


class RoomDetailResponse(BaseModel):
    id: UUID
    name: str
    invite_code: str
    host_id: UUID
    max_viewers: int
    status: str
    created_at: datetime
    participants: list[ParticipantResponse] = []
    
    class Config:
        from_attributes = True
