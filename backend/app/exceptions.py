"""
Custom Exception Classes for ScreenShare Pro

Bu modul, tum uygulama izerinde kullanilacak custom exception siniflarini icerir.
Her exception sinifi, spesifik bir hata durumunu temsil eder ve tutarli hata yonetimi saglar.
"""

from typing import Any, Optional
from enum import Enum


class ErrorCode(str, Enum):
    """Standart hata kodlari - tutarli error response'lar icin"""

    # Authentication & Authorization (AUTH_xxx)
    INVALID_TOKEN = "AUTH_001"
    TOKEN_EXPIRED = "AUTH_002"
    INVALID_CREDENTIALS = "AUTH_003"
    USER_NOT_FOUND = "AUTH_004"
    USER_INACTIVE = "AUTH_005"
    USER_ALREADY_EXISTS = "AUTH_006"
    USERNAME_TAKEN = "AUTH_007"
    EMAIL_TAKEN = "AUTH_008"
    PERMISSION_DENIED = "AUTH_009"
    ADMIN_REQUIRED = "AUTH_010"

    # Room & Broadcast (ROOM_xxx)
    ROOM_NOT_FOUND = "ROOM_001"
    ROOM_INACTIVE = "ROOM_002"
    ROOM_FULL = "ROOM_003"
    ROOM_ALREADY_ENDED = "ROOM_004"
    NOT_ROOM_HOST = "ROOM_005"
    ALREADY_IN_ROOM = "ROOM_006"
    NOT_IN_ROOM = "ROOM_007"
    MAX_PRESENTERS_REACHED = "ROOM_008"
    INVALID_INVITE_CODE = "ROOM_009"

    # WebSocket (WS_xxx)
    WS_CONNECTION_FAILED = "WS_001"
    WS_INVALID_MESSAGE = "WS_002"
    WS_UNAUTHORIZED = "WS_003"
    WS_ROOM_NOT_FOUND = "WS_004"
    WS_SEND_FAILED = "WS_005"

    # Diagram & Mindmap (DIAG_xxx)
    DIAGRAM_NOT_FOUND = "DIAG_001"
    INVALID_MINDMAP_FORMAT = "DIAG_002"
    NODE_NOT_FOUND = "DIAG_003"

    # Validation (VAL_xxx)
    VALIDATION_ERROR = "VAL_001"
    INVALID_INPUT = "VAL_002"
    MISSING_REQUIRED_FIELD = "VAL_003"
    INVALID_FORMAT = "VAL_004"

    # Database (DB_xxx)
    DATABASE_ERROR = "DB_001"
    NOT_FOUND = "DB_002"
    ALREADY_EXISTS = "DB_003"
    CONSTRAINT_VIOLATION = "DB_004"

    # External Services (EXT_xxx)
    EXTERNAL_SERVICE_ERROR = "EXT_001"
    TURN_SERVER_ERROR = "EXT_002"

    # General (GEN_xxx)
    INTERNAL_SERVER_ERROR = "GEN_001"
    SERVICE_UNAVAILABLE = "GEN_002"
    RATE_LIMIT_EXCEEDED = "GEN_003"


class AppException(Exception):
    """
    Base exception class for all application errors.

    Tum custom exception'lar bu siniftan turetilmelidir.
    Tutarli hala response'lari ve loglama saglar.

    Attributes:
        message: Kullaniciya gosterilecek hata mesaji
        code: Hata kodu (ErrorCode enum)
        status_code: HTTP status code
        details: Ek hata detaylari (opsiyonel)
    """

    def __init__(
        self,
        message: str,
        code: ErrorCode = ErrorCode.INTERNAL_SERVER_ERROR,
        status_code: int = 500,
        details: Optional[dict[str, Any]] = None,
    ):
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or {}
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        """Exception'i dict formatina donusturur (API response icin)"""
        result = {
            "error": self.code.value,
            "message": self.message,
            "status_code": self.status_code,
        }
        if self.details:
            result["details"] = self.details
        return result


# ==================== Authentication Exceptions ====================

class AuthenticationException(AppException):
    """Genel authentication hatasi"""

    def __init__(
        self,
        message: str = "Kimlik dogrulama hatasi",
        code: ErrorCode = ErrorCode.INVALID_TOKEN,
        details: Optional[dict[str, Any]] = None,
    ):
        super().__init__(message, code, 401, details)


class TokenExpiredException(AuthenticationException):
    """Token'in suresi doldu"""

    def __init__(self, message: str = "Oturum suresi doldu, lutfen tekrar giris yapin"):
        super().__init__(message, ErrorCode.TOKEN_EXPIRED)


class InvalidCredentialsException(AuthenticationException):
    """Gecersiz kullanici adi veya sifre"""

    def __init__(self, message: str = "Kullanici adi veya sifre hatali"):
        super().__init__(message, ErrorCode.INVALID_CREDENTIALS)


class UserNotFoundException(AuthenticationException):
    """Kullanici bulunamadi"""

    def __init__(self, message: str = "Kullanici bulunamadi"):
        super().__init__(message, ErrorCode.USER_NOT_FOUND)


class UserInactiveException(AuthenticationException):
    """Kullanici hesabi devre disi"""

    def __init__(self, message: str = "Hesabiniz devre disi birakilmis"):
        super().__init__(message, ErrorCode.USER_INACTIVE)


class UserAlreadyExistsException(AuthenticationException):
    """Kullanici zaten mevcut"""

    def __init__(
        self,
        message: str = "Bu kullanici zaten mevcut",
        details: Optional[dict[str, Any]] = None,
    ):
        super().__init__(message, ErrorCode.USER_ALREADY_EXISTS, 400, details)


class UsernameTakenException(UserAlreadyExistsException):
    """Kullanici adi zaten alinmis"""

    def __init__(self):
        super().__init__("Bu kullanici adi zaten alinmis", {"field": "username"})


class EmailTakenException(UserAlreadyExistsException):
    """E-posta adresi zaten kayitli"""

    def __init__(self):
        super().__init__("Bu e-posta adresi zaten kayitli", {"field": "email"})


class PermissionDeniedException(AppException):
    """Yetki hatasi"""

    def __init__(self, message: str = "Bu islem için yetkiniz yok"):
        super().__init__(message, ErrorCode.PERMISSION_DENIED, 403)


class AdminRequiredException(PermissionDeniedException):
    """Sadece admin yapabilir"""

    def __init__(self, message: str = "Bu islem için admin yetkisi gerekli"):
        super().__init__(message)


# ==================== Room Exceptions ====================

class RoomException(AppException):
    """Genel oda hatasi"""

    def __init__(
        self,
        message: str,
        code: ErrorCode = ErrorCode.ROOM_NOT_FOUND,
        status_code: int = 404,
        details: Optional[dict[str, Any]] = None,
    ):
        super().__init__(message, code, status_code, details)


class RoomNotFoundException(RoomException):
    """Oda bulunamadi"""

    def __init__(self, message: str = "Oda bulunamadi"):
        super().__init__(message, ErrorCode.ROOM_NOT_FOUND, 404)


class RoomInactiveException(RoomException):
    """Oda aktif degil"""

    def __init__(self, message: str = "Bu oda artik aktif degil"):
        super().__init__(message, ErrorCode.ROOM_INACTIVE, 400)


class RoomFullException(RoomException):
    """Oda kapasitesi doldu"""

    def __init__(self, message: str = "Oda kapasitesi dolmus"):
        super().__init__(message, ErrorCode.ROOM_FULL, 400)


class RoomAlreadyEndedException(RoomException):
    """Oda zaten sonlandirilmis"""

    def __init__(self, message: str = "Bu oda zaten sonlandirilmis"):
        super().__init__(message, ErrorCode.ROOM_ALREADY_ENDED, 400)


class NotRoomHostException(RoomException):
    """Kullanici oda host'u degil"""

    def __init__(self, message: str = "Bu islemi sadece oda sahibi yapabilir"):
        super().__init__(message, ErrorCode.NOT_ROOM_HOST, 403)


class AlreadyInRoomException(RoomException):
    """Kullanici zaten odada"""

    def __init__(self, message: str = "Zaten bu odada bulunuyorsunuz"):
        super().__init__(message, ErrorCode.ALREADY_IN_ROOM, 400)


class NotInRoomException(RoomException):
    """Kullanici odada degil"""

    def __init__(self, message: str = "Bu odada bulunuyorsunuz"):
        super().__init__(message, ErrorCode.NOT_IN_ROOM, 400)


class MaxPresentersReachedException(RoomException):
    """Maksimum presenter sayisina ulasildi"""

    def __init__(self, message: str = "Maksimum 2 kisi ayni anda ekran paylaşabilir"):
        super().__init__(message, ErrorCode.MAX_PRESENTERS_REACHED, 400)


class InvalidInviteCodeException(RoomException):
    """Gecersiz davet kodu"""

    def __init__(self, message: str = "Gecersiz davet kodu"):
        super().__init__(message, ErrorCode.INVALID_INVITE_CODE, 404)


# ==================== WebSocket Exceptions ====================

class WebSocketException(AppException):
    """Genel WebSocket hatasi"""

    def __init__(
        self,
        message: str,
        code: ErrorCode = ErrorCode.WS_CONNECTION_FAILED,
        details: Optional[dict[str, Any]] = None,
    ):
        super().__init__(message, code, 1000, details)


class WebSocketUnauthorizedException(WebSocketException):
    """WebSocket yetkilendirme hatasi"""

    def __init__(self, message: str = "WebSocket yetkilendirme hatasi"):
        super().__init__(message, ErrorCode.WS_UNAUTHORIZED, {"close_code": 4001})


class WebSocketRoomNotFoundException(WebSocketException):
    """WebSocket oda bulunamadi hatasi"""

    def __init__(self, message: str = "WebSocket oda bulunamadi"):
        super().__init__(message, ErrorCode.WS_ROOM_NOT_FOUND, {"close_code": 4004})


class WebSocketSendException(WebSocketException):
    """WebSocket mesaj gonderme hatasi"""

    def __init__(self, recipient: str, reason: str = "Unknown"):
        super().__init__(
            f"WebSocket mesaj gonderilemedi: {recipient}",
            ErrorCode.WS_SEND_FAILED,
            {"recipient": recipient, "reason": reason},
        )


class WebSocketInvalidMessageException(WebSocketException):
    """Gecersiz WebSocket mesaji"""

    def __init__(self, reason: str = "Invalid message format"):
        super().__init__(
            f"Gecersiz mesaj formati: {reason}",
            ErrorCode.WS_INVALID_MESSAGE,
            {"reason": reason},
        )


# ==================== Diagram Exceptions ====================

class DiagramException(AppException):
    """Genel diagram hatasi"""

    def __init__(
        self,
        message: str,
        code: ErrorCode = ErrorCode.DIAGRAM_NOT_FOUND,
        status_code: int = 404,
        details: Optional[dict[str, Any]] = None,
    ):
        super().__init__(message, code, status_code, details)


class DiagramNotFoundException(DiagramException):
    """Diagram bulunamadi"""

    def __init__(self, message: str = "Diagram bulunamadi"):
        super().__init__(message, ErrorCode.DIAGRAM_NOT_FOUND, 404)


class InvalidMindmapFormatException(DiagramException):
    """Gecersiz mindmap formati"""

    def __init__(self, message: str = "Gecersiz mindmap formati"):
        super().__init__(message, ErrorCode.INVALID_MINDMAP_FORMAT, 400)


class NodeNotFoundException(DiagramException):
    """Node bulunamadi"""

    def __init__(self, message: str = "Node bulunamadi"):
        super().__init__(message, ErrorCode.NODE_NOT_FOUND, 404)


# ==================== Validation Exceptions ====================

class ValidationException(AppException):
    """Genel dogrulama hatasi"""

    def __init__(
        self,
        message: str = "Dogrulama hatasi",
        details: Optional[dict[str, Any]] = None,
    ):
        super().__init__(message, ErrorCode.VALIDATION_ERROR, 400, details)


class InvalidInputException(ValidationException):
    """Gecersiz input"""

    def __init__(self, field: str, reason: str = "Invalid value"):
        super().__init__(
            f"Gecersiz deger: {field}",
            {"field": field, "reason": reason},
        )


class MissingFieldException(ValidationException):
    """Eksik zorunlu alan"""

    def __init__(self, field: str):
        super().__init__(
            f"Zorunlu alan eksik: {field}",
            {"field": field},
        )
        self.code = ErrorCode.MISSING_REQUIRED_FIELD


# ==================== Database Exceptions ====================

class DatabaseException(AppException):
    """Genel veritabani hatasi"""

    def __init__(
        self,
        message: str = "Veritabani hatasi",
        details: Optional[dict[str, Any]] = None,
    ):
        super().__init__(message, ErrorCode.DATABASE_ERROR, 500, details)


class NotFoundException(DatabaseException):
    """Kaynak bulunamadi"""

    def __init__(self, resource: str = "Kaynak"):
        super().__init__(
            f"{resource} bulunamadi",
            {"resource": resource},
        )
        self.code = ErrorCode.NOT_FOUND
        self.status_code = 404


class AlreadyExistsException(DatabaseException):
    """Kaynak zaten mevcut"""

    def __init__(self, resource: str = "Kaynak"):
        super().__init__(
            f"{resource} zaten mevcut",
            {"resource": resource},
        )
        self.code = ErrorCode.ALREADY_EXISTS
        self.status_code = 409


# ==================== External Service Exceptions ====================

class ExternalServiceException(AppException):
    """Genel dis servis hatasi"""

    def __init__(
        self,
        service: str,
        message: str = "Dis servis hatasi",
        details: Optional[dict[str, Any]] = None,
    ):
        full_message = f"{service}: {message}"
        all_details = {"service": service}
        if details:
            all_details.update(details)
        super().__init__(full_message, ErrorCode.EXTERNAL_SERVICE_ERROR, 502, all_details)


class TurnServerException(ExternalServiceException):
    """TURN server hatasi"""

    def __init__(self, message: str = "TURN server baglanti hatasi"):
        super().__init__("TURN Server", message)
        self.code = ErrorCode.TURN_SERVER_ERROR
