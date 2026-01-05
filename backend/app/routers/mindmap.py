"""
Mindmap API Router
Freeplane mindmap işlemleri için REST API
"""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field
from app.database import get_db
from app.models.user import User
from app.services.auth_service import AuthService
from app.services.diagram_service import DiagramService
from app.services.mindmap_service import MindmapService

router = APIRouter(prefix="/api/mindmap", tags=["Mindmap"])
security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db)
) -> User:
    auth_service = AuthService(db)
    user = await auth_service.get_user_from_token(credentials.credentials)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Geçersiz token")
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
async def get_mindmap_tree(
    diagram_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Mindmap'i ağaç yapısı olarak getir"""
    service = DiagramService(db)
    diagram = await service.get_diagram_by_id(diagram_id)
    
    if not diagram:
        raise HTTPException(status_code=404, detail="Mindmap bulunamadı")
    
    try:
        tree = MindmapService.parse_mindmap(diagram.content)
        return {"tree": tree}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Mindmap parse hatası: {str(e)}")


@router.post("/{diagram_id}/node")
async def add_mindmap_node(
    diagram_id: UUID,
    data: AddNodeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Mindmap'e yeni node ekle"""
    service = DiagramService(db)
    diagram = await service.get_diagram_by_id(diagram_id)
    
    if not diagram:
        raise HTTPException(status_code=404, detail="Mindmap bulunamadı")
    
    try:
        new_content, new_node = MindmapService.add_node(
            diagram.content, 
            data.parent_id, 
            data.text
        )
        
        # Veritabanını güncelle
        await service.update_diagram(diagram_id, content=new_content)
        
        return {"success": True, "node": new_node, "content": new_content}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Node ekleme hatası: {str(e)}")


@router.put("/{diagram_id}/node")
async def update_mindmap_node(
    diagram_id: UUID,
    data: UpdateNodeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Mindmap node'unu güncelle"""
    service = DiagramService(db)
    diagram = await service.get_diagram_by_id(diagram_id)
    
    if not diagram:
        raise HTTPException(status_code=404, detail="Mindmap bulunamadı")
    
    try:
        new_content = MindmapService.update_node(
            diagram.content,
            data.node_id,
            data.text
        )
        
        await service.update_diagram(diagram_id, content=new_content)
        
        return {"success": True, "content": new_content}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Node güncelleme hatası: {str(e)}")


@router.delete("/{diagram_id}/node")
async def delete_mindmap_node(
    diagram_id: UUID,
    data: DeleteNodeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Mindmap node'unu sil"""
    service = DiagramService(db)
    diagram = await service.get_diagram_by_id(diagram_id)
    
    if not diagram:
        raise HTTPException(status_code=404, detail="Mindmap bulunamadı")
    
    try:
        new_content = MindmapService.delete_node(
            diagram.content,
            data.node_id
        )
        
        await service.update_diagram(diagram_id, content=new_content)
        
        return {"success": True, "content": new_content}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Node silme hatası: {str(e)}")
