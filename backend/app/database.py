from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import select
from app.config import settings


engine = create_async_engine(settings.DATABASE_URL, echo=settings.DEBUG)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    from app.models.user import User
    from app.utils.security import get_password_hash
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # Default admin kullanıcı oluştur
    async with async_session() as session:
        result = await session.execute(select(User).where(User.username == "erkan"))
        existing_user = result.scalar_one_or_none()
        
        if not existing_user:
            admin_user = User(
                username="erkan",
                email="erkan@erkanerdem.net",
                password_hash=get_password_hash("518518"),
                role="admin"
            )
            session.add(admin_user)
            await session.commit()
            print("✅ Default admin kullanıcı oluşturuldu: erkan / 518518")
