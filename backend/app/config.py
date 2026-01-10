import secrets
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache
from pydantic import field_validator
import sys


class Settings(BaseSettings):
    # App
    APP_NAME: str = "ScreenShare Pro"
    DEBUG: bool = False

    # Logging
    LOG_LEVEL: str = "INFO"  # TRACE, DEBUG, INFO, SUCCESS, WARNING, ERROR, CRITICAL
    LOG_JSON: bool = False  # Set True for JSON logging in production

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/screenshare"
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 40
    DB_POOL_PRE_PING: bool = True

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # JWT
    # CRITICAL: JWT_SECRET must be set in production for security
    # In development mode (DEBUG=True), a default value is allowed
    JWT_SECRET: str = ""
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Metered TURN Server
    METERED_API_KEY: str = ""
    METERED_API_URL: str = "https://erkan.metered.live/api/v1/turn/credentials"
    STUN_SERVER: str = "stun:stun.relay.metered.ca:80"
    TURN_SERVER: str = "turn:standard.relay.metered.ca:443"
    TURN_SERVER_TCP: str = "turns:standard.relay.metered.ca:443?transport=tcp"
    TURN_USERNAME: str = ""
    TURN_CREDENTIAL: str = ""

    # CORS
    CORS_ORIGINS: list[str] = ["http://localhost:8000", "http://127.0.0.1:8000"]

    # Room Settings
    MAX_VIEWERS_PER_ROOM: int = 5  # Max 5 katılımcı (host dahil)
    MAX_PRESENTERS_PER_ROOM: int = 2  # Max 2 kişi aynı anda ekran paylaşabilir

    # File Upload Settings
    MAX_FILE_SIZE: int = 10 * 1024 * 1024  # 10MB
    FILE_RETENTION_MINUTES: int = 60  # Dosyalar 60 dakika sonra silinir

    # Public URL (dış erişim için)
    PUBLIC_URL: str = "http://localhost:8000"

    # Admin Settings
    ADMIN_USERNAME: str = "admin"
    ADMIN_EMAIL: str = "admin@example.com"
    ADMIN_PASSWORD: str = ""  # Boş bırakılırsa rastgele oluşturulur
    ADMIN_FORCE_PASSWORD_CHANGE: bool = True  # İlk girişte şifre değiştirme zorunluluğu

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @field_validator("JWT_SECRET")
    @classmethod
    def validate_jwt_secret(cls, v: str, info) -> str:
        """Validate JWT_SECRET is set in production environments."""
        # Get DEBUG value safely - field_validator runs before all fields are set
        debug_mode = False
        try:
            debug_mode = info.data.get("DEBUG", False)
        except (AttributeError, KeyError):
            pass

        # Production mode requires JWT_SECRET to be set
        if not v or v == "" or v == "your-super-secret-key-change-in-production":
            if not debug_mode:
                raise ValueError(
                    "CRITICAL SECURITY ERROR: JWT_SECRET environment variable must be set "
                    "with a strong, unique value in production mode. "
                    "\nGenerate a secure key with: python -c 'import secrets; print(secrets.token_urlsafe(32))' "
                    "\nThen set it in your .env file: JWT_SECRET=<generated-key>"
                )
            # Development mode: use a secure random key as fallback
            if not v:
                import warnings
                fallback_key = secrets.token_urlsafe(32)
                warnings.warn(
                    f"JWT_SECRET not set, using auto-generated development key: {fallback_key}. "
                    "This is NOT secure for production!",
                    RuntimeWarning,
                    stacklevel=2
                )
                return fallback_key
            # If using the placeholder value in dev, still warn
            if v == "your-super-secret-key-change-in-production":
                import warnings
                warnings.warn(
                    "Using default placeholder JWT_SECRET in development mode. "
                    "This should be changed even for development!",
                    RuntimeWarning,
                    stacklevel=2
                )
        return v

    @field_validator("JWT_SECRET")
    @classmethod
    def validate_jwt_secret_length(cls, v: str) -> str:
        """Ensure JWT_SECRET is at least 32 characters for security."""
        if v and len(v) < 32:
            import warnings
            warnings.warn(
                f"JWT_SECRET is too short ({len(v)} chars). Minimum 32 characters recommended for security.",
                RuntimeWarning,
                stacklevel=2
            )
        return v


@lru_cache()
def get_settings() -> Settings:
    """
    Get cached settings instance.
    Raises ValidationError if configuration is invalid.
    """
    try:
        return Settings()
    except Exception as e:
        print(f"\n{'='*70}")
        print(f"CONFIGURATION ERROR: {e}")
        print(f"{'='*70}\n")
        sys.exit(1)


settings = get_settings()
