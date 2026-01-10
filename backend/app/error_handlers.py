"""
Centralized Error Handlers for ScreenShare Pro

Bu modul, FastAPI uygulamasinda tum exception'lari yakalayan ve
tutarli hala response'lari donen global error handler'lari icerir.
"""

import logging
from traceback import format_exc
from typing import Any, Union

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from pydantic import ValidationError

from app.exceptions import AppException, ErrorCode


# Logger konfigurasyonu
logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)


class ErrorResponse:
    """
    Standart hala response formati.

    Tum API error'lari bu format kullanir:
    {
        "success": false,
        "error": "ERROR_CODE",
        "message": "Kullaniciya gosterilecek mesaj",
        "details": {...},  // Opsiyonel
        "status_code": 400
    }
    """

    @staticmethod
    def create(
        error_code: Union[ErrorCode, str],
        message: str,
        status_code: int,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Standart error response olustur"""
        response: dict[str, Any] = {
            "success": False,
            "error": error_code.value if isinstance(error_code, ErrorCode) else error_code,
            "message": message,
            "status_code": status_code,
        }
        if details:
            response["details"] = details
        return response


def log_error(
    error: Exception,
    request: Request | None = None,
    level: str = "ERROR",
    extra: dict[str, Any] | None = None,
) -> None:
    """
    Hatalari tutarli sekilde logla.

    Args:
        error: Exception objesi
        request: FastAPI Request objesi (opsiyonel)
        level: Log seviyesi (ERROR, WARNING, INFO)
        extra: Ek log bilgileri
    """
    log_func = getattr(logger, level.lower(), logger.error)

    log_data: dict[str, Any] = {
        "error_type": type(error).__name__,
        "error_message": str(error),
    }

    if request:
        client_host: str | None = None
        if request.client is not None:
            client_host = request.client.host
        log_data.update({
            "method": request.method,
            "url": str(request.url),
            "client": client_host,
        })

    if extra:
        log_data.update(extra)

    log_func("Error occurred", extra=log_data)

    # Debug modunda stack trace logla
    if logger.level <= logging.DEBUG:
        logger.debug(f"Stack trace:\n{format_exc()}")


def register_exception_handlers(app: FastAPI) -> None:
    """
    FastAPI uygulamasina tum exception handler'lari kaydet.

    Bu fonksiyon main.py'de cagrilmalidir.
    """

    @app.exception_handler(AppException)
    async def app_exception_handler(
        request: Request, exc: AppException
    ) -> JSONResponse:
        """
        Custom AppException handler.

        Tum custom exception'lar burada yakalanir ve
        tutarli formatta response doner.
        """
        log_error(exc, request, level="WARNING")

        return JSONResponse(
            status_code=exc.status_code,
            content=ErrorResponse.create(
                error_code=exc.code,
                message=exc.message,
                status_code=exc.status_code,
                details=exc.details if exc.details else None,
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        """
        HTTPException handler.

        FastAPI'in HTTPException'lari icin.
        """
        # Error code map - status code'a gore uygun error code sec
        error_code_map = {
            400: ErrorCode.VALIDATION_ERROR,
            401: ErrorCode.INVALID_TOKEN,
            403: ErrorCode.PERMISSION_DENIED,
            404: ErrorCode.NOT_FOUND,
            422: ErrorCode.VALIDATION_ERROR,
            500: ErrorCode.INTERNAL_SERVER_ERROR,
        }
        error_code = error_code_map.get(exc.status_code, ErrorCode.INTERNAL_SERVER_ERROR)

        log_error(exc, request, level="WARNING")

        return JSONResponse(
            status_code=exc.status_code,
            content=ErrorResponse.create(
                error_code=error_code,
                message=str(exc.detail) if exc.detail else "HTTP hatasi",
                status_code=exc.status_code,
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """
        Pydantic validation error handler.

        Request body validation hatasinda tutarli response doner.
        """
        # Validation hatalarini daha okunabilir hale getir
        errors = []
        for error in exc.errors():
            field = ".".join(str(loc) for loc in error["loc"][1:])  # 'body' skip et
            errors.append({
                "field": field,
                "message": error["msg"],
                "type": error["type"],
            })

        log_error(
            exc,
            request,
            level="WARNING",
            extra={"validation_errors": errors},
        )

        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=ErrorResponse.create(
                error_code=ErrorCode.VALIDATION_ERROR,
                message="Gecerlilik hatasi - Lutfen girdilerinizi kontrol edin",
                status_code=422,
                details={"validation_errors": errors},
            ),
        )

    @app.exception_handler(ValidationError)
    async def pydantic_validation_exception_handler(
        request: Request, exc: ValidationError
    ) -> JSONResponse:
        """
        Pydantic ValidationError handler (response model validation icin).
        """
        errors = [
            {
                "field": ".".join(str(loc) for loc in error["loc"]),
                "message": error["msg"],
                "type": error["type"],
            }
            for error in exc.errors()
        ]

        log_error(
            exc,
            request,
            level="WARNING",
            extra={"validation_errors": errors},
        )

        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=ErrorResponse.create(
                error_code=ErrorCode.VALIDATION_ERROR,
                message="Response gecerlilik hatasi",
                status_code=500,
                details={"validation_errors": errors},
            ),
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        """
        General exception handler.

        Tum yakalanmamayan exception'lar burada yakalanir.
        Production'da detayli hata bilgisi gosterilmez.
        """
        log_error(exc, request, level="ERROR")

        # Debug modunda detayli bilgi goster
        import os
        debug_mode = os.getenv("DEBUG", "False").lower() == "true"

        if debug_mode:
            message = f"{type(exc).__name__}: {str(exc)}"
            details = {"traceback": format_exc()}
        else:
            message = "Beklenmeyen bir hata olustu. Lutfen daha sonra tekrar deneyin."
            details = None

        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=ErrorResponse.create(
                error_code=ErrorCode.INTERNAL_SERVER_ERROR,
                message=message,
                status_code=500,
                details=details,
            ),
        )


# ==================== WebSocket Error Handling ====================

class WebSocketErrorHandler:
    """
    WebSocket icin error handling utility.

    WebSocket connection'larda olusan hatalari loglamak
    ve uygun close code ile baglantiyi kapatmak icin kullanilir.
    """

    @staticmethod
    async def handle_connection_error(
        websocket,
        error: Exception,
        reason: str = "Connection error",
        close_code: int = 1011,
    ) -> None:
        """
        WebSocket connection hatasini handle et.

        Args:
            websocket: WebSocket connection objesi
            error: Exception objesi
            reason: Kapatma sebebi
            close_code: WebSocket close code
        """
        log_error(
            error,
            level="WARNING",
            extra={"websocket_close_reason": reason, "close_code": close_code},
        )

        try:
            await websocket.close(code=close_code, reason=reason[:125])  # Max 123 chars
        except Exception as close_error:
            logger.error(f"Failed to close websocket: {close_error}")

    @staticmethod
    async def send_error_message(
        websocket,
        message: str,
        error_code: str = "ERROR",
        details: dict[str, Any] | None = None,
    ) -> bool:
        """
        WebSocket'e error mesaji gonder.

        Args:
            websocket: WebSocket connection objesi
            message: Hata mesaji
            error_code: Hata kodu
            details: Ek detaylar

        Returns:
            bool: Mesaj basariyla gonderildiyse True
        """
        try:
            await websocket.send_json({
                "type": "error",
                "error": error_code,
                "message": message,
                **({"details": details} if details else {}),
            })
            return True
        except Exception as e:
            log_error(e, level="WARNING", extra={"failed_message": message})
            return False

    @staticmethod
    def log_websocket_error(
        error: Exception,
        room_id: str | None = None,
        user_id: str | None = None,
        message_type: str | None = None,
    ) -> None:
        """
        WebSocket error loglarini tutarli formatta yaz.

        Args:
            error: Exception objesi
            room_id: Oda ID (varsa)
            user_id: Kullanici ID (varsa)
            message_type: Mesaj tipi (varsa)
        """
        log_data: dict[str, Any] = {
            "error_type": type(error).__name__,
            "error_message": str(error),
        }

        if room_id:
            log_data["room_id"] = room_id
        if user_id:
            log_data["user_id"] = user_id
        if message_type:
            log_data["message_type"] = message_type

        logger.warning("WebSocket error occurred", extra=log_data)


# ==================== Helper Functions ====================

async def handle_service_exception(
    error: Exception,
    default_message: str = "Islem sirasinda bir hata olustu",
    default_code: ErrorCode = ErrorCode.INTERNAL_SERVER_ERROR,
    default_status: int = 500,
) -> tuple[str, ErrorCode, int, dict[str, Any] | None]:
    """
    Service layer'dan gelen exception'lari handle et.

    Bu fonksiyon service layer'da throw edilen exception'lari
    uygun formata donusturmek icin kullanilir.

    Args:
        error: Exception objesi
        default_message: Default hata mesaji
        default_code: Default error code
        default_status: Default HTTP status

    Returns:
        tuple: (message, error_code, status_code, details)
    """
    if isinstance(error, AppException):
        return error.message, error.code, error.status_code, error.details

    # Bilinmeyen exception tipleri icin logla
    log_error(error, level="ERROR")

    # Database-specific hatalar
    error_str = str(error).lower()
    if "duplicate" in error_str or "unique" in error_str:
        return "Bu kayit zaten mevcut", ErrorCode.ALREADY_EXISTS, 409, None
    if "foreign key" in error_str:
        return "Iliskili kayit bulunamadi", ErrorCode.NOT_FOUND, 404, None
    if "connection" in error_str:
        return "Veritabani baglanti hatasi", ErrorCode.DATABASE_ERROR, 503, None

    return default_message, default_code, default_status, None


def raise_if(condition: bool, exception: AppException) -> None:
    """
    Kosul saglaniyorsa exception firlat.

    Kullanim:
        raise_if(not user, UserNotFoundException())

    Args:
        condition: True ise exception firlat
        exception: Firlatilacak exception
    """
    if condition:
        raise exception


def not_found_if_none(value: Any, resource_name: str = "Kaynak") -> Any:
    """
    Deger None ise NotFoundException firlat, degilse degeri don.

    Kullanim:
        user = not_found_if_none(await get_user(id), "Kullanici")

    Args:
        value: Kontrol edilecek deger
        resource_name: Kaynak adi

    Returns:
        Eger None degilse orijinal deger

    Raises:
        NotFoundException: Deger None ise
    """
    if value is None:
        from app.exceptions import NotFoundException
        raise NotFoundException(resource_name)
    return value
