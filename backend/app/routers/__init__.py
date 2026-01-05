from app.routers.auth import router as auth_router
from app.routers.rooms import router as rooms_router
from app.routers.websocket import router as websocket_router
from app.routers.diagrams import router as diagrams_router
from app.routers.mindmap import router as mindmap_router

__all__ = ["auth_router", "rooms_router", "websocket_router", "diagrams_router", "mindmap_router"]
