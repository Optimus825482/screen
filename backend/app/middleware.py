"""
Rate limiting middleware for adding rate limit headers to responses.
"""
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp


class RateLimitHeaderMiddleware(BaseHTTPMiddleware):
    """
    Middleware to add rate limit headers to HTTP responses.
    Headers are set by the rate_limit decorator in request.state.rate_limit_info
    """

    def __init__(self, app: ASGIApp):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)

        # Add rate limit headers if available
        if hasattr(request.state, "rate_limit_info"):
            info = request.state.rate_limit_info
            response.headers["X-RateLimit-Limit"] = str(info.get("limit", 100))
            response.headers["X-RateLimit-Remaining"] = str(info.get("remaining", 0))
            response.headers["X-RateLimit-Reset"] = str(info.get("reset", 0))

        return response
