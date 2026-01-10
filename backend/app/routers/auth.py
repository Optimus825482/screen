"""
Authentication Router for ScreenShare Pro

Bu modul, kullanici kimlik dogrulama ve yonetim endpoint'lerini icerir.
"""
from uuid import UUID
from typing import Annotated
from fastapi import APIRouter, Depends, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.services.auth_service import AuthService
from app.schemas.auth import (
    UserCreate, UserLogin, UserResponse, TokenResponse, TokenRefresh, ChangePassword
)
from app.utils.security import verify_password, hash_password
from app.models.user import User
from app.utils.rate_limit import rate_limit
from app.utils.logging_config import auth_logger
from app.exceptions import (
    TokenExpiredException,
    InvalidCredentialsException,
    UserInactiveException,
    UsernameTakenException,
    EmailTakenException,
    PermissionDeniedException,
    AdminRequiredException,
    UserNotFoundException,
    ValidationException,
)

router = APIRouter(prefix="/api/auth", tags=["Authentication"])
security = HTTPBearer()


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
    db: Annotated[AsyncSession, Depends(get_db)]
) -> User:
    """
    Token'dan mevcut kullanicinin bilgilerini al.

    Raises:
        TokenExpiredException: Token suresi dolduysa
        UserNotFoundException: Kullanici bulunamazsa
    """
    auth_service = AuthService(db)
    user = await auth_service.get_user_from_token(credentials.credentials)
    if not user:
        auth_logger.warning(f"Failed authorization attempt via token")
        raise TokenExpiredException()
    return user


async def get_admin_user(current_user: Annotated[User, Depends(get_current_user)]) -> User:
    """
    Sadece admin kullanicilar icin dependency.

    Raises:
        AdminRequiredException: Kullanici admin degilse
    """
    if not current_user.is_admin:
        raise AdminRequiredException()
    return current_user


@router.post("/login", response_model=TokenResponse)
@rate_limit(limit=5, window=60, identifier="login")
async def login(
    request: Request,
    login_data: UserLogin,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """
    Username ile giris yap - 5 deneme / dakika.

    Raises:
        InvalidCredentialsException: Kullanici adi veya sifre hataliysa
        UserInactiveException: Hesap devre disi birakildiysa
    """
    auth_service = AuthService(db)
    user = await auth_service.authenticate_user(login_data.username, login_data.password)

    if not user:
        raise InvalidCredentialsException()

    if not user.is_active:
        raise UserInactiveException()

    auth_logger.info(f"User logged in successfully", extra={"username": user.username})
    return auth_service.create_user_tokens(user)


@router.post("/refresh", response_model=TokenResponse)
@rate_limit(limit=20, window=60, identifier="refresh")
async def refresh_token(
    request: Request,
    token_data: TokenRefresh,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """
    Token yenileme - 20 istek / dakika.

    Raises:
        TokenExpiredException: Refresh token gecersizse
    """
    auth_service = AuthService(db)
    tokens = await auth_service.refresh_tokens(token_data.refresh_token)

    if not tokens:
        raise TokenExpiredException("Gecersiz refresh token")

    return tokens


@router.get("/me", response_model=UserResponse)
@rate_limit(limit=60, window=60, identifier="me")
async def get_me(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)]
):
    """Kullanici bilgisi - 60 istek / dakika"""
    return current_user


@router.post("/change-password", status_code=status.HTTP_200_OK)
@rate_limit(limit=10, window=60, identifier="change_password")
async def change_password(
    request: Request,
    password_data: ChangePassword,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """
    Sifre degistirme - 10 istek / dakika.

    Raises:
        ValidationException: Eski sifre hataliysa
    """
    # Eski sifreyi dogrula
    if not verify_password(password_data.old_password, current_user.password_hash):
        raise ValidationException(
            "Mevcut sifre hatali",
            details={"field": "old_password", "reason": "password_mismatch"}
        )

    # Yeni sifreyi hashleyerek guncelle
    current_user.password_hash = hash_password(password_data.new_password)
    current_user.must_change_password = False
    await db.commit()

    auth_logger.info(f"User changed password", extra={"user_id": str(current_user.id)})
    return {"message": "Sifre basariyla degistirildi"}


# ============ ADMIN ENDPOINTS ============

@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
@rate_limit(limit=10, window=60, identifier="create_user")
async def create_user(
    request: Request,
    user_data: UserCreate,
    admin: Annotated[User, Depends(get_admin_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """
    Admin: Yeni kullanici olustur (user rolu ile) - 10 istek / dakika.

    Raises:
        UsernameTakenException: Kullanici adi alinmissa
        EmailTakenException: E-posta adresi kayitliysa
    """
    auth_service = AuthService(db)

    if await auth_service.get_user_by_username(user_data.username):
        raise UsernameTakenException()

    if await auth_service.get_user_by_email(user_data.email):
        raise EmailTakenException()

    user = await auth_service.create_user(user_data, "user")

    auth_logger.info(
        f"Admin created new user",
        extra={"admin_id": str(admin.id), "new_user_id": str(user.id)}
    )
    return user


@router.get("/users", response_model=list[UserResponse])
@rate_limit(limit=30, window=60, identifier="list_users")
async def list_users(
    request: Request,
    admin: Annotated[User, Depends(get_admin_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """Admin: Tum kullanicilari listele - 30 istek / dakika"""
    auth_service = AuthService(db)
    return await auth_service.get_all_users()


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
@rate_limit(limit=10, window=60, identifier="delete_user")
async def delete_user(
    request: Request,
    user_id: UUID,
    admin: Annotated[User, Depends(get_admin_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """
    Admin: Kullanici sil - 10 istek / dakika.

    Raises:
        PermissionDeniedException: Kendini silmeye calisiyorsa
        UserNotFoundException: Kullanici bulunamazsa
    """
    if admin.id == user_id:
        raise PermissionDeniedException("Kendinizi silemezsiniz")

    auth_service = AuthService(db)
    success = await auth_service.delete_user(user_id)

    if not success:
        raise UserNotFoundException()

    auth_logger.info(
        f"Admin deleted user",
        extra={"admin_id": str(admin.id), "deleted_user_id": str(user_id)}
    )
