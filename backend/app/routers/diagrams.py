from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.models.user import User
from app.services.auth_service import AuthService
from app.services.diagram_service import DiagramService
from app.schemas.diagram import DiagramCreate, DiagramUpdate, DiagramResponse, DiagramListResponse

router = APIRouter(prefix="/api/diagrams", tags=["Diagrams"])
security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db)
) -> User:
    """Token'dan kullanıcı al"""
    auth_service = AuthService(db)
    user = await auth_service.get_user_from_token(credentials.credentials)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Geçersiz veya süresi dolmuş token")
    return user


@router.get("", response_model=list[DiagramListResponse])
async def list_diagrams(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Tüm diagramları listele"""
    service = DiagramService(db)
    return await service.get_all_diagrams()


@router.post("", response_model=DiagramResponse, status_code=status.HTTP_201_CREATED)
async def create_diagram(
    data: DiagramCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Yeni diagram oluştur"""
    service = DiagramService(db)
    return await service.create_diagram(
        name=data.name,
        content=data.content,
        owner_id=current_user.id
    )


@router.get("/{diagram_id}", response_model=DiagramResponse)
async def get_diagram(
    diagram_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Diagram detayını getir"""
    service = DiagramService(db)
    diagram = await service.get_diagram_by_id(diagram_id)
    if not diagram:
        raise HTTPException(status_code=404, detail="Diagram bulunamadı")
    return diagram


@router.put("/{diagram_id}", response_model=DiagramResponse)
async def update_diagram(
    diagram_id: UUID,
    data: DiagramUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Diagram güncelle"""
    service = DiagramService(db)
    diagram = await service.update_diagram(
        diagram_id=diagram_id,
        name=data.name,
        content=data.content
    )
    if not diagram:
        raise HTTPException(status_code=404, detail="Diagram bulunamadı")
    return diagram


@router.delete("/{diagram_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_diagram(
    diagram_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Diagram sil"""
    service = DiagramService(db)
    deleted = await service.delete_diagram(diagram_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Diagram bulunamadı")
