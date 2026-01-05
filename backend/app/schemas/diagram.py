from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, Field


class DiagramCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    content: str = Field(default='{"elements":[],"appState":{"viewBackgroundColor":"#111822"}}')


class DiagramUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    content: str | None = None


class DiagramResponse(BaseModel):
    id: UUID
    name: str
    content: str
    owner_id: UUID
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class DiagramListResponse(BaseModel):
    id: UUID
    name: str
    owner_id: UUID
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True
