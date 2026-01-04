from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, Field


class UserLogin(BaseModel):
    """Username ile login"""
    username: str = Field(..., min_length=3, max_length=50)
    password: str


class UserCreate(BaseModel):
    """Admin tarafından kullanıcı oluşturma"""
    username: str = Field(..., min_length=3, max_length=50)
    email: str = Field(..., max_length=100)
    password: str = Field(..., min_length=6)


class UserResponse(BaseModel):
    id: UUID
    username: str
    email: str
    role: str
    is_active: bool
    created_at: datetime
    
    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    role: str


class TokenRefresh(BaseModel):
    refresh_token: str
