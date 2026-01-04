from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.user import User
from app.schemas.auth import UserCreate
from app.utils.security import hash_password, verify_password, create_tokens, decode_token


class AuthService:
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_user_by_email(self, email: str) -> User | None:
        result = await self.db.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()
    
    async def get_user_by_username(self, username: str) -> User | None:
        result = await self.db.execute(select(User).where(User.username == username))
        return result.scalar_one_or_none()
    
    async def get_user_by_id(self, user_id: UUID) -> User | None:
        result = await self.db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()
    
    async def get_all_users(self) -> list[User]:
        result = await self.db.execute(select(User).order_by(User.created_at.desc()))
        return list(result.scalars().all())
    
    async def create_user(self, user_data: UserCreate, role: str = "user") -> User:
        user = User(
            username=user_data.username,
            email=user_data.email,
            password_hash=hash_password(user_data.password),
            role=role
        )
        self.db.add(user)
        await self.db.flush()
        await self.db.refresh(user)
        return user
    
    async def authenticate_user(self, username: str, password: str) -> User | None:
        """Username ile authenticate"""
        user = await self.get_user_by_username(username)
        if not user or not verify_password(password, user.password_hash):
            return None
        return user
    
    def create_user_tokens(self, user: User) -> dict[str, str]:
        tokens = create_tokens(str(user.id), user.role)
        tokens["role"] = user.role
        return tokens
    
    async def get_user_from_token(self, token: str) -> User | None:
        payload = decode_token(token)
        if not payload or payload.get("type") != "access":
            return None
        user_id = payload.get("sub")
        if not user_id:
            return None
        return await self.get_user_by_id(UUID(user_id))
    
    async def refresh_tokens(self, refresh_token: str) -> dict[str, str] | None:
        payload = decode_token(refresh_token)
        if not payload or payload.get("type") != "refresh":
            return None
        user_id = payload.get("sub")
        if not user_id:
            return None
        user = await self.get_user_by_id(UUID(user_id))
        if not user:
            return None
        return self.create_user_tokens(user)
    
    async def delete_user(self, user_id: UUID) -> bool:
        user = await self.get_user_by_id(user_id)
        if not user:
            return False
        await self.db.delete(user)
        await self.db.flush()
        return True
