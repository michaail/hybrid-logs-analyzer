"""HTTP security headers for the HDFS control plane."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Apply browser protections without breaking FastAPI's interactive documentation."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Permissions-Policy",
            "camera=(), geolocation=(), microphone=()",
        )
        if request.url.path not in {"/docs", "/openapi.json", "/redoc"}:
            response.headers.setdefault(
                "Content-Security-Policy",
                "base-uri 'self'; connect-src 'self'; default-src 'self'; form-action 'self'; "
                "frame-ancestors 'none'; img-src 'self' data:; object-src 'none'; "
                "script-src 'self'; style-src 'self'",
            )
        return response
