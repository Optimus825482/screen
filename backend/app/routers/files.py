"""
File Upload API Router
Multipart file upload with temporary storage
"""
import os
import uuid
import asyncio
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, Request
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.routers.auth import get_current_user
from app.models.user import User
from app.config import settings
from app.utils.rate_limit import rate_limit
from app.utils.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/files", tags=["Files"])

# Temporary file storage configuration
TEMP_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "temp_files")

# file_id -> {filepath, filename, filesize, content_type, uploaded_at, uploader_id}
temp_files: dict = {}


async def ensure_temp_dir():
    """Temp dizinini oluştur"""
    os.makedirs(TEMP_DIR, exist_ok=True)


async def cleanup_old_files():
    """Eski dosyaları temizle (background task)"""
    while True:
        try:
            now = datetime.utcnow()
            expired_ids = []

            for file_id, file_info in list(temp_files.items()):
                uploaded_at = datetime.fromisoformat(file_info["uploaded_at"])
                if now - uploaded_at > timedelta(minutes=settings.FILE_RETENTION_MINUTES):
                    expired_ids.append(file_id)

            # Silinecek dosyaları temizle
            for file_id in expired_ids:
                file_info = temp_files.get(file_id)
                if file_info:
                    filepath = file_info["filepath"]
                    try:
                        if os.path.exists(filepath):
                            os.remove(filepath)
                    except Exception as e:
                        logger.error(f"Error deleting file {filepath}: {e}")
                    del temp_files[file_id]

            if expired_ids:
                logger.info(f"Cleaned up {len(expired_ids)} expired files")

        except Exception as e:
            logger.error(f"Error in cleanup task: {e}")

        # 5 dakikada bir kontrol et
        await asyncio.sleep(300)


# Start cleanup task on module load
_cleanup_task = None


def start_cleanup_task():
    global _cleanup_task
    if _cleanup_task is None:
        _cleanup_task = asyncio.create_task(cleanup_old_files())


@router.post("/upload")
@rate_limit(limit=10, window=60, identifier="upload_file")
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    room_id: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Multipart file upload endpoint.
    Dosya boyutu kontrolü backend'de yapılır.
    Upload edilen dosyalar temporary storage'a kaydedilir.
    - 10 istek / dakika
    """
    await ensure_temp_dir()

    # Dosya boyutu kontrolü
    content = await file.read()
    file_size = len(content)

    if file_size > settings.MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Dosya boyutu {settings.MAX_FILE_SIZE // (1024*1024)}MB'dan büyük olamaz"
        )

    if file_size == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Boş dosya yüklenemez"
        )

    # Güvenli dosya adı oluştur
    file_id = str(uuid.uuid4())
    original_filename = file.filename or "unnamed"
    safe_filename = f"{file_id}_{original_filename}"

    # Dosya yolunu oluştur
    filepath = os.path.join(TEMP_DIR, safe_filename)

    # Dosyayı diske yaz
    with open(filepath, "wb") as f:
        f.write(content)

    # Dosya bilgisini kaydet
    file_info = {
        "file_id": file_id,
        "filepath": filepath,
        "filename": original_filename,
        "filesize": file_size,
        "content_type": file.content_type or "application/octet-stream",
        "uploaded_at": datetime.utcnow().isoformat(),
        "uploader_id": str(current_user.id),
        "room_id": room_id
    }
    temp_files[file_id] = file_info

    return {
        "file_id": file_id,
        "filename": original_filename,
        "filesize": file_size,
        "content_type": file.content_type,
        "message": "Dosya başarıyla yüklendi"
    }


@router.get("/download/{file_id}")
@rate_limit(limit=30, window=60, identifier="download_file")
async def download_file(
    request: Request,
    file_id: str,
    current_user: User = Depends(get_current_user)
):
    """
    Dosya ID'sinden dosyayı indir.
    - 30 istek / dakika
    """
    file_info = temp_files.get(file_id)

    if not file_info:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dosya bulunamadı veya süresi dolmuş"
        )

    filepath = file_info["filepath"]

    if not os.path.exists(filepath):
        # Temp dosyadan sil ama memory'de var
        del temp_files[file_id]
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dosya bulunamadı"
        )

    return FileResponse(
        filepath,
        filename=file_info["filename"],
        media_type=file_info["content_type"]
    )


@router.get("/info/{file_id}")
@rate_limit(limit=60, window=60, identifier="get_file_info")
async def get_file_info(
    request: Request,
    file_id: str,
    current_user: User = Depends(get_current_user)
):
    """
    Dosya bilgisini getir (download olmadan)
    - 60 istek / dakika
    """
    file_info = temp_files.get(file_id)

    if not file_info:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dosya bulunamadı veya süresi dolmuş"
        )

    return {
        "file_id": file_info["file_id"],
        "filename": file_info["filename"],
        "filesize": file_info["filesize"],
        "content_type": file_info["content_type"],
        "uploaded_at": file_info["uploaded_at"]
    }


@router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
@rate_limit(limit=20, window=60, identifier="delete_file")
async def delete_file(
    request: Request,
    file_id: str,
    current_user: User = Depends(get_current_user)
):
    """
    Dosyayı manuel olarak sil
    - 20 istek / dakika
    """
    file_info = temp_files.get(file_id)

    if not file_info:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dosya bulunamadı"
        )

    # Sadece yükleyen silebilir
    if file_info["uploader_id"] != str(current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bu dosyayı silme yetkiniz yok"
        )

    filepath = file_info["filepath"]

    if os.path.exists(filepath):
        os.remove(filepath)

    del temp_files[file_id]


def get_temp_file_info(file_id: str) -> Optional[dict]:
    """
    Internal helper: Dosya bilgisini getir (auth olmadan)
    """
    return temp_files.get(file_id)


def remove_temp_file(file_id: str):
    """
    Internal helper: Dosyayı sil (auth olmadan)
    """
    file_info = temp_files.get(file_id)
    if file_info:
        filepath = file_info["filepath"]
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
        except Exception:
            pass
        del temp_files[file_id]
