from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # App
    APP_NAME: str = "ScreenShare Pro"
    DEBUG: bool = False
    
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/screenshare"
    
    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    
    # JWT
    JWT_SECRET: str = "your-super-secret-key-change-in-production"
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
    MAX_VIEWERS_PER_ROOM: int = 3
    
    # Public URL (dış erişim için)
    PUBLIC_URL: str = "http://localhost:8000"
    
    class Config:
        env_file = ".env"


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
