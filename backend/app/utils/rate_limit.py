"""
Rate limiting utility with Redis backend.
Supports both HTTP endpoints and WebSocket rate limiting.
"""
import time
import json
from typing import Optional, Callable
from functools import wraps
from fastapi import Request, HTTPException, status, WebSocket
from app.config import settings

# Optional Redis import - falls back to in-memory if not available
try:
    from redis.asyncio import Redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    Redis = None  # type: ignore


class RateLimiter:
    """
    Redis-based rate limiter with sliding window algorithm.
    Falls back to in-memory storage if Redis is not available.
    """

    def __init__(self, redis_url: str = None):
        self.redis_url = redis_url or settings.REDIS_URL
        self._redis: Optional["Redis"] = None
        self._fallback_store: dict = {}  # Fallback in-memory storage
        self._use_fallback = not REDIS_AVAILABLE or not settings.RATE_LIMIT_USE_REDIS

    async def get_redis(self) -> Optional["Redis"]:
        """Get or create Redis connection."""
        if self._redis is None and not self._use_fallback and REDIS_AVAILABLE:
            try:
                self._redis = Redis.from_url(
                    self.redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                    socket_connect_timeout=5,
                    socket_timeout=5,
                    retry_on_timeout=False
                )
                # Test connection
                await self._redis.ping()
            except Exception:
                self._use_fallback = True
                self._redis = None
        return self._redis

    async def close(self):
        """Close Redis connection."""
        if self._redis:
            await self._redis.close()

    def _get_fallback_key(self, key: str) -> dict:
        """Get data from fallback storage."""
        return self._fallback_store.get(key, {"count": 0, "reset_at": 0})

    def _set_fallback_key(self, key: str, data: dict):
        """Set data in fallback storage."""
        self._fallback_store[key] = data

    def _cleanup_fallback(self):
        """Remove expired entries from fallback storage."""
        now = time.time()
        expired_keys = [
            k for k, v in self._fallback_store.items()
            if v.get("reset_at", 0) < now
        ]
        for k in expired_keys:
            del self._fallback_store[k]

    async def is_allowed(
        self,
        key: str,
        limit: int,
        window: int
    ) -> tuple[bool, dict]:
        """
        Check if request is allowed under rate limit.

        Args:
            key: Unique identifier (e.g., IP, user_id)
            limit: Maximum requests allowed
            window: Time window in seconds

        Returns:
            Tuple of (is_allowed, info_dict)
        """
        now = time.time()
        window_start = now - window
        reset_at = int(now + window)

        if not self._use_fallback:
            try:
                redis = await self.get_redis()
                if redis:
                    # Redis pipeline for atomic operations
                    pipe = redis.pipeline()
                    pipe.zremrangebyscore(key, 0, window_start)
                    pipe.zcard(key)
                    pipe.zadd(key, {str(now): now})
                    pipe.expire(key, window)
                    results = await pipe.execute()

                    current_count = results[1]  # Count after cleanup
                    is_allowed = current_count < limit

                    return is_allowed, {
                        "limit": limit,
                        "remaining": max(0, limit - current_count - 1),
                        "reset": reset_at
                    }
            except Exception:
                # Fall back to in-memory on error
                self._use_fallback = True
                self._redis = None

        # Fallback: in-memory storage
        self._cleanup_fallback()
        data = self._get_fallback_key(key)

        # Reset if window expired
        if data["reset_at"] < now:
            data = {"count": 0, "reset_at": reset_at}

        data["count"] += 1
        self._set_fallback_key(key, data)

        is_allowed = data["count"] <= limit
        return is_allowed, {
            "limit": limit,
            "remaining": max(0, limit - data["count"]),
            "reset": data["reset_at"]
        }


# Global rate limiter instance
limiter = RateLimiter()


async def close_rate_limiter():
    """Close the rate limiter connection (call on shutdown)."""
    await limiter.close()


def get_client_identifier(request: Request) -> str:
    """
    Get a unique identifier for the client.
    Uses authenticated user ID if available, otherwise IP address.
    """
    # Check if user is authenticated
    if hasattr(request.state, "user") and request.state.user:
        return f"user:{request.state.user.id}"

    # Use forwarded IP if behind proxy
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        ip = forwarded.split(",")[0].strip()
    else:
        # Safely access client.host - client can be None
        ip: str = "unknown"
        if request.client is not None:
            ip = request.client.host

    return f"ip:{ip}"


def get_ws_client_identifier(websocket: WebSocket) -> str:
    """Get identifier for WebSocket client."""
    # Use token from query params for authenticated users
    token = websocket.query_params.get("token")
    if token:
        # Could decode token to get user_id, but for rate limiting
        # we'll use the token hash
        import hashlib
        token_hash = hashlib.sha256(token.encode()).hexdigest()[:16]
        return f"ws_user:{token_hash}"

    # Use IP for unauthenticated - safely handle None client
    ip: str = "unknown"
    if websocket.client is not None:
        ip = websocket.client.host
    return f"ws_ip:{ip}"


def rate_limit(
    limit: int,
    window: int,
    key_func: Optional[Callable] = None,
    identifier: str = "default"
):
    """
    Rate limiting decorator for FastAPI endpoints.

    Args:
        limit: Maximum requests allowed
        window: Time window in seconds
        key_func: Optional function to generate custom key
        identifier: Endpoint identifier for the key

    Raises:
        HTTPException: When rate limit is exceeded
    """
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Find Request object in args/kwargs
            request = None
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break
            if not request:
                for v in kwargs.values():
                    if isinstance(v, Request):
                        request = v
                        break

            if request:
                # Get client identifier
                if key_func:
                    client_key = key_func(request)
                else:
                    client_key = get_client_identifier(request)

                # Full key with endpoint identifier
                full_key = f"rate_limit:{identifier}:{client_key}"

                # Check rate limit
                is_allowed, info = await limiter.is_allowed(full_key, limit, window)

                if not is_allowed:
                    # Add rate limit headers to response (stored in state)
                    request.state.rate_limit_info = info
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail="Rate limit exceeded. Please try again later.",
                        headers={
                            "X-RateLimit-Limit": str(info["limit"]),
                            "X-RateLimit-Remaining": "0",
                            "X-RateLimit-Reset": str(info["reset"]),
                            "Retry-After": str(window)
                        }
                    )

                # Store info for headers
                request.state.rate_limit_info = info

            return await func(*args, **kwargs)

        return wrapper
    return decorator


class WebSocketRateLimiter:
    """
    Rate limiter for WebSocket connections.
    Limits messages per connection within a time window.
    """

    def __init__(
        self,
        message_limit: int = 60,
        window_seconds: int = 60,
        burst_limit: int = 10,
        burst_window: int = 1
    ):
        """
        Args:
            message_limit: Max messages per window
            window_seconds: Time window in seconds
            burst_limit: Max messages in burst window
            burst_window: Burst window in seconds
        """
        self.message_limit = message_limit
        self.window = window_seconds
        self.burst_limit = burst_limit
        self.burst_window = burst_window
        # Track per-connection: {connection_id: [(timestamp, count), ...]}
        self.connections: dict = {}

    def _get_connection_key(self, websocket: WebSocket) -> str:
        """Get unique key for the connection."""
        if websocket.client is not None:
            return f"{websocket.client.host}:{websocket.client.port}"
        return "unknown"

    async def check_rate_limit(
        self,
        websocket: WebSocket,
        connection_id: str
    ) -> tuple[bool, Optional[str]]:
        """
        Check if WebSocket message is allowed.

        Returns:
            Tuple of (is_allowed, error_message)
        """
        now = time.time()
        key = self._get_connection_key(websocket)

        if key not in self.connections:
            self.connections[key] = {
                "messages": [],  # List of timestamps
                "burst_start": now,
                "burst_count": 0
            }

        conn_data = self.connections[key]

        # Clean old messages outside the main window
        conn_data["messages"] = [
            ts for ts in conn_data["messages"]
            if now - ts < self.window
        ]

        # Check main rate limit
        if len(conn_data["messages"]) >= self.message_limit:
            return False, f"Rate limit exceeded: max {self.message_limit} messages per {self.window} seconds"

        # Check burst limit
        if now - conn_data["burst_start"] > self.burst_window:
            conn_data["burst_start"] = now
            conn_data["burst_count"] = 0

        if conn_data["burst_count"] >= self.burst_limit:
            return False, f"Too many messages: max {self.burst_limit} messages per {self.burst_window} seconds"

        # Add current message
        conn_data["messages"].append(now)
        conn_data["burst_count"] += 1

        return True, None

    def cleanup(self, connection_id: str = None):
        """Remove connection from tracking."""
        if connection_id and connection_id in self.connections:
            del self.connections[connection_id]


# WebSocket rate limiter instances
ws_chat_limiter = WebSocketRateLimiter(
    message_limit=60,   # 60 messages per minute
    window_seconds=60,
    burst_limit=10,     # Max 10 messages per second
    burst_window=1
)

ws_signaling_limiter = WebSocketRateLimiter(
    message_limit=300,  # 300 messages per minute (for WebRTC signaling)
    window_seconds=60,
    burst_limit=30,     # Max 30 messages per second
    burst_window=1
)


async def check_websocket_rate_limit(
    websocket: WebSocket,
    connection_id: str,
    message_type: str = "default"
) -> tuple[bool, Optional[str]]:
    """
    Check WebSocket rate limit based on message type.

    Args:
        websocket: WebSocket connection
        connection_id: Unique connection identifier
        message_type: Type of message (chat, signaling, etc.)

    Returns:
        Tuple of (is_allowed, error_message)
    """
    if message_type == "chat":
        return await ws_chat_limiter.check_rate_limit(websocket, connection_id)
    elif message_type in ("signaling", "offer", "answer", "ice_candidate"):
        return await ws_signaling_limiter.check_rate_limit(websocket, connection_id)
    else:
        # Default limits
        limiter = WebSocketRateLimiter(
            message_limit=120,
            window_seconds=60,
            burst_limit=20,
            burst_window=1
        )
        return await limiter.check_rate_limit(websocket, connection_id)


def cleanup_websocket_rate_limit(connection_id: str):
    """Clean up rate limit tracking for a connection."""
    ws_chat_limiter.cleanup(connection_id)
    ws_signaling_limiter.cleanup(connection_id)
