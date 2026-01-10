"""
Diagrams Router for ScreenShare Pro

Bu modul, Excalidraw diagram yonetim endpoint'lerini icerir.
"""
from uuid import UUID
from typing import Annotated
from fastapi import APIRouter, Depends, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.models.user import User
from app.services.auth_service import AuthService
from app.services.diagram_service import DiagramService
from app.schemas.diagram import DiagramCreate, DiagramUpdate, DiagramResponse, DiagramListResponse
from app.utils.rate_limit import rate_limit
from app.utils.logging_config import diagram_logger
from app.exceptions import (
    TokenExpiredException,
    DiagramNotFoundException,
)

router = APIRouter(prefix="/api/diagrams", tags=["Diagrams"])
security = HTTPBearer()


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
    db: Annotated[AsyncSession, Depends(get_db)]
) -> User:
    """
    Token'dan kullanici al.

    Raises:
        TokenExpiredException: Token gecersizse
    """
    auth_service = AuthService(db)
    user = await auth_service.get_user_from_token(credentials.credentials)
    if not user:
        raise TokenExpiredException()
    return user


@router.get("", response_model=list[DiagramListResponse])
@rate_limit(limit=60, window=60, identifier="list_diagrams")
async def list_diagrams(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)]
):
    """Tum diagramlari listele - 60 istek / dakika"""
    service = DiagramService(db)
    return await service.get_all_diagrams()


@router.post("", response_model=DiagramResponse, status_code=status.HTTP_201_CREATED)
@rate_limit(limit=20, window=60, identifier="create_diagram")
async def create_diagram(
    request: Request,
    data: DiagramCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)]
):
    """Yeni diagram olustur - 20 istek / dakika"""
    service = DiagramService(db)
    diagram = await service.create_diagram(
        name=data.name,
        content=data.content,
        owner_id=current_user.id
    )

    diagram_logger.info(
        f"Diagram creation request completed",
        extra={
            "diagram_id": str(diagram.id),
            "diagram_name": data.name,
            "owner_id": str(current_user.id)
        }
    )
    return diagram


@router.get("/{diagram_id}", response_model=DiagramResponse)
@rate_limit(limit=60, window=60, identifier="get_diagram")
async def get_diagram(
    request: Request,
    diagram_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)]
):
    """
    Diagram detayini getir - 60 istek / dakika.

    Raises:
        DiagramNotFoundException: Diagram bulunamazsa
    """
    service = DiagramService(db)
    diagram = await service.get_diagram_by_id(diagram_id)
    if not diagram:
        raise DiagramNotFoundException()
    return diagram


@router.put("/{diagram_id}", response_model=DiagramResponse)
@rate_limit(limit=100, window=60, identifier="update_diagram")
async def update_diagram(
    request: Request,
    diagram_id: UUID,
    data: DiagramUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)]
):
    """
    Diagram guncelle - 100 istek / dakika (frequent updates).

    Raises:
        DiagramNotFoundException: Diagram bulunamazsa
    """
    service = DiagramService(db)
    diagram = await service.update_diagram(
        diagram_id=diagram_id,
        name=data.name,
        content=data.content
    )
    if not diagram:
        raise DiagramNotFoundException()
    return diagram


@router.delete("/{diagram_id}", status_code=status.HTTP_204_NO_CONTENT)
@rate_limit(limit=10, window=60, identifier="delete_diagram")
async def delete_diagram(
    request: Request,
    diagram_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)]
):
    """
    Diagram sil - 10 istek / dakika.

    Raises:
        DiagramNotFoundException: Diagram bulunamazsa
    """
    service = DiagramService(db)
    deleted = await service.delete_diagram(diagram_id)
    if not deleted:
        raise DiagramNotFoundException()

    diagram_logger.info(
        f"Diagram deleted",
        extra={
            "diagram_id": str(diagram_id),
            "deleted_by": str(current_user.id)
        }
    )
