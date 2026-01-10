import secrets
import string
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import select, text
from app.config import settings
from app.utils.logging_config import database_logger


def generate_strong_password(length: int = 24) -> str:
    """
    Güçlü rastgele şifre oluştur.
    ENTLF: Büyük harf, küçük harf, rakam ve özel karakter içerir.
    """
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*()_+-=[]{}|;:,.<>?"
    return ''.join(secrets.choice(alphabet) for _ in range(length))


engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_pre_ping=settings.DB_POOL_PRE_PING,
)
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


async def run_migrations(conn):
    """
    Manuel migration'lar - eksik kolonları ekle.
    Alembic kullanmadan basit migration.
    """
    migrations = [
        # users.must_change_password kolonu
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name = 'users' AND column_name = 'must_change_password'
            ) THEN
                ALTER TABLE users ADD COLUMN must_change_password BOOLEAN DEFAULT FALSE;
            END IF;
        END $$;
        """,
    ]
    
    for migration in migrations:
        await conn.execute(text(migration))


async def init_db():
    from app.models.user import User
    from app.models.diagram import Diagram
    from app.utils.security import get_password_hash

    database_logger.info("Initializing database...")

    async with engine.begin() as conn:
        # Önce tabloları oluştur
        await conn.run_sync(Base.metadata.create_all)
        # Sonra migration'ları çalıştır (eksik kolonları ekle)
        await run_migrations(conn)
    
    database_logger.success("Database schema created/updated")

    # Admin kullanıcı oluştur - environment variable'dan veya rastgele
    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.username == settings.ADMIN_USERNAME)
        )
        existing_user = result.scalar_one_or_none()

        if not existing_user:
            # Environment'dan şifre al veya rastgele oluştur
            admin_password = settings.ADMIN_PASSWORD
            generated_password = False

            if not admin_password:
                admin_password = generate_strong_password()
                generated_password = True

            admin_user = User(
                username=settings.ADMIN_USERNAME,
                email=settings.ADMIN_EMAIL,
                password_hash=get_password_hash(admin_password),
                role="admin",
                must_change_password=settings.ADMIN_FORCE_PASSWORD_CHANGE
            )
            session.add(admin_user)
            await session.commit()

            # Şifreyi güvenli şekilde log'a yaz (sadece ilk oluşturmada)
            database_logger.warning(
                "=" * 70
            )
            database_logger.warning(
                "SECURITY ALERT: Admin user created!"
            )
            database_logger.warning(
                f"Username: {settings.ADMIN_USERNAME}"
            )
            database_logger.warning(
                f"Password:  {admin_password}"
            )
            if generated_password:
                database_logger.warning(
                    "WARNING: Random password was generated. Save it now!"
                )
                database_logger.warning(
                    "Set ADMIN_PASSWORD in .env to use a custom password."
                )
            if settings.ADMIN_FORCE_PASSWORD_CHANGE:
                database_logger.warning(
                    "First login will require password change!"
                )
            database_logger.warning(
                "IMPORTANT: Change this password immediately after first login!"
            )
            database_logger.warning(
                "=" * 70
            )
        else:
            database_logger.info(f"Admin user already exists: {settings.ADMIN_USERNAME}")
