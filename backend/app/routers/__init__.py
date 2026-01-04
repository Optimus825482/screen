from app.routers.auth import router as auth_router
from app.routers.rooms import router as rooms_router
from app.routers.websocket import router as websocket_router

__all__ = ["auth_router", "rooms_router", "websocket_router"]
