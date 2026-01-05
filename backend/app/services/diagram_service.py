from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.diagram import Diagram


class DiagramService:
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create_diagram(self, name: str, content: str, owner_id: UUID) -> Diagram:
        diagram = Diagram(name=name, content=content, owner_id=owner_id)
        self.db.add(diagram)
        await self.db.commit()
        await self.db.refresh(diagram)
        return diagram
    
    async def get_diagram_by_id(self, diagram_id: UUID) -> Diagram | None:
        result = await self.db.execute(select(Diagram).where(Diagram.id == diagram_id))
        return result.scalar_one_or_none()
    
    async def get_all_diagrams(self) -> list[Diagram]:
        """Tüm diagramları getir (tüm kullanıcılar görebilir)"""
        result = await self.db.execute(
            select(Diagram).order_by(Diagram.updated_at.desc())
        )
        return list(result.scalars().all())
    
    async def update_diagram(self, diagram_id: UUID, name: str = None, content: str = None) -> Diagram | None:
        diagram = await self.get_diagram_by_id(diagram_id)
        if not diagram:
            return None
        if name is not None:
            diagram.name = name
        if content is not None:
            diagram.content = content
        await self.db.commit()
        await self.db.refresh(diagram)
        return diagram
    
    async def delete_diagram(self, diagram_id: UUID) -> bool:
        diagram = await self.get_diagram_by_id(diagram_id)
        if not diagram:
            return False
        await self.db.delete(diagram)
        await self.db.commit()
        return True
