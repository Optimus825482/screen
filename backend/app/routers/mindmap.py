"""
Mindmap API Router for ScreenShare Pro

Freeplane mindmap islemleri icin REST API.
"""
from uuid import UUID
from typing import Annotated
from fastapi import APIRouter, Depends, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field
from app.database import get_db
from app.models.user import User
from app.services.auth_service import AuthService
from app.services.diagram_service import DiagramService
from app.services.mindmap_service import MindmapService
from app.utils.rate_limit import rate_limit
from app.utils.logging_config import mindmap_logger
from app.exceptions import (
    TokenExpiredException,
    DiagramNotFoundException,
    InvalidMindmapFormatException,
)

router = APIRouter(prefix="/api/mindmap", tags=["Mindmap"])
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


class AddNodeRequest(BaseModel):
    parent_id: str
    text: str = Field(..., min_length=1, max_length=500)


class UpdateNodeRequest(BaseModel):
    node_id: str
    text: str = Field(..., min_length=1, max_length=500)


class DeleteNodeRequest(BaseModel):
    node_id: str


@router.get("/{diagram_id}/tree")
@rate_limit(limit=60, window=60, identifier="get_mindmap")
async def get_mindmap_tree(
    request: Request,
    diagram_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)]
):
    """
    Mindmap'i agac yapis olarak getir - 60 istek / dakika.

    Raises:
        DiagramNotFoundException: Mindmap bulunamazsa
        InvalidMindmapFormatException: Mindmap formati gecersizse
    """
    service = DiagramService(db)
    diagram = await service.get_diagram_by_id(diagram_id)

    if not diagram:
        raise DiagramNotFoundException("Mindmap bulunamadi")

    try:
        tree = MindmapService.parse_mindmap(diagram.content)
        return {"tree": tree}
    except Exception as e:
        mindmap_logger.error(
            f"Failed to parse mindmap",
            extra={"diagram_id": str(diagram_id), "error": str(e)}
        )
        raise InvalidMindmapFormatException()


@router.post("/{diagram_id}/node")
@rate_limit(limit=100, window=60, identifier="add_mindmap_node")
async def add_mindmap_node(
    request: Request,
    diagram_id: UUID,
    data: AddNodeRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)]
):
    """
    Mindmap'e yeni node ekle - 100 istek / dakika.

    Raises:
        DiagramNotFoundException: Mindmap bulunamazsa
        InvalidMindmapFormatException: Node eklenemezse
    """
    service = DiagramService(db)
    diagram = await service.get_diagram_by_id(diagram_id)

    if not diagram:
        raise DiagramNotFoundException("Mindmap bulunamadi")

    try:
        new_content, new_node = MindmapService.add_node(
            diagram.content,
            data.parent_id,
            data.text
        )

        # Veritabanini guncelle
        await service.update_diagram(diagram_id, content=new_content)

        mindmap_logger.info(
            f"Mindmap node added",
            extra={
                "diagram_id": str(diagram_id),
                "user_id": str(current_user.id),
                "node_id": new_node.get("id", "unknown")
            }
        )

        return {"success": True, "node": new_node, "content": new_content}
    except Exception as e:
        mindmap_logger.error(
            f"Failed to add mindmap node",
            extra={
                "diagram_id": str(diagram_id),
                "error": str(e)
            }
        )
        raise InvalidMindmapFormatException(f"Node ekleme hatasi: {str(e)}")


@router.put("/{diagram_id}/node")
@rate_limit(limit=100, window=60, identifier="update_mindmap_node")
async def update_mindmap_node(
    request: Request,
    diagram_id: UUID,
    data: UpdateNodeRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)]
):
    """
    Mindmap node'unu guncelle - 100 istek / dakika.

    Raises:
        DiagramNotFoundException: Mindmap bulunamazsa
        InvalidMindmapFormatException: Node guncellenemezse
    """
    service = DiagramService(db)
    diagram = await service.get_diagram_by_id(diagram_id)

    if not diagram:
        raise DiagramNotFoundException("Mindmap bulunamadi")

    try:
        new_content = MindmapService.update_node(
            diagram.content,
            data.node_id,
            data.text
        )

        await service.update_diagram(diagram_id, content=new_content)

        mindmap_logger.debug(
            f"Mindmap node updated",
            extra={
                "diagram_id": str(diagram_id),
                "user_id": str(current_user.id),
                "node_id": data.node_id
            }
        )

        return {"success": True, "content": new_content}
    except Exception as e:
        mindmap_logger.error(
            f"Failed to update mindmap node",
            extra={
                "diagram_id": str(diagram_id),
                "node_id": data.node_id,
                "error": str(e)
            }
        )
        raise InvalidMindmapFormatException(f"Node guncelleme hatasi: {str(e)}")


@router.delete("/{diagram_id}/node")
@rate_limit(limit=50, window=60, identifier="delete_mindmap_node")
async def delete_mindmap_node(
    request: Request,
    diagram_id: UUID,
    data: DeleteNodeRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)]
):
    """
    Mindmap node'unu sil - 50 istek / dakika.

    Raises:
        DiagramNotFoundException: Mindmap bulunamazsa
        InvalidMindmapFormatException: Node silinemezse
    """
    service = DiagramService(db)
    diagram = await service.get_diagram_by_id(diagram_id)

    if not diagram:
        raise DiagramNotFoundException("Mindmap bulunamadi")

    try:
        new_content = MindmapService.delete_node(
            diagram.content,
            data.node_id
        )

        await service.update_diagram(diagram_id, content=new_content)

        mindmap_logger.info(
            f"Mindmap node deleted",
            extra={
                "diagram_id": str(diagram_id),
                "user_id": str(current_user.id),
                "node_id": data.node_id
            }
        )

        return {"success": True, "content": new_content}
    except Exception as e:
        mindmap_logger.error(
            f"Failed to delete mindmap node",
            extra={
                "diagram_id": str(diagram_id),
                "node_id": data.node_id,
                "error": str(e)
            }
        )
        raise InvalidMindmapFormatException(f"Node silme hatasi: {str(e)}")
