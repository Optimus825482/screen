from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from app.config import settings
from app.database import init_db
from app.routers import auth_router, rooms_router, websocket_router, diagrams_router, mindmap_router, files_router
from app.utils.logging_config import setup_logging, fastapi_logger
from app.error_handlers import register_exception_handlers


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    # Setup logging first
    setup_logging()
    fastapi_logger.info(f"Starting {settings.APP_NAME}")
    await init_db()
    fastapi_logger.info("Database initialized")
    # Start file cleanup task
    from app.routers.files import start_cleanup_task
    start_cleanup_task()
    fastapi_logger.info("File cleanup task started")
    yield
    # Shutdown
    fastapi_logger.info("Shutting down application")
    # Close rate limiter connections
    from app.utils.rate_limit import close_rate_limiter
    await close_rate_limiter()
    fastapi_logger.info("Rate limiter connections closed")


app = FastAPI(
    title=settings.APP_NAME,
    description="Web tabanlı ekran paylaşım platformu",
    version="1.0.0",
    lifespan=lifespan
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global Exception Handlers
register_exception_handlers(app)

# Static files & Templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# API Routers
app.include_router(auth_router)
app.include_router(rooms_router)
app.include_router(websocket_router)
app.include_router(diagrams_router)
app.include_router(mindmap_router)
app.include_router(files_router)


# Health Check
@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": settings.APP_NAME}


@app.get("/ready")
async def readiness_check():
    return {"status": "ready"}


# Frontend Routes
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    # Register kapalı - login'e yönlendir
    return RedirectResponse(url="/login", status_code=302)


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})


@app.get("/room/{room_id}", response_class=HTMLResponse)
async def room_page(request: Request, room_id: str):
    return templates.TemplateResponse("room.html", {
        "request": request, 
        "room_id": room_id,
        "public_url": settings.PUBLIC_URL
    })


@app.get("/join/{invite_code}", response_class=HTMLResponse)
async def join_page(request: Request, invite_code: str):
    return templates.TemplateResponse("join.html", {"request": request, "invite_code": invite_code})


@app.get("/watch/{room_id}", response_class=HTMLResponse)
async def watch_page(request: Request, room_id: str):
    """Guest viewer sayfası - giriş yapmadan izleme"""
    return templates.TemplateResponse("watch.html", {
        "request": request, 
        "room_id": room_id,
        "public_url": settings.PUBLIC_URL
    })


@app.get("/mindmap", response_class=HTMLResponse)
async def mindmap_page(request: Request):
    """Mindmap editörü"""
    return templates.TemplateResponse("mindmap.html", {"request": request})


@app.get("/mindmap/{diagram_id}", response_class=HTMLResponse)
async def mindmap_edit_page(request: Request, diagram_id: str):
    """Mindmap editörü - belirli diagram"""
    return templates.TemplateResponse("mindmap.html", {
        "request": request,
        "diagram_id": diagram_id
    })


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8005, reload=True)
