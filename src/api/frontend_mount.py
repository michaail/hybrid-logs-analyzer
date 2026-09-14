"""Optional SPA mount for the compiled React client."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


def mount_frontend(app: FastAPI) -> None:
    """Serve the compiled React client when it is included in the deployed image."""
    frontend_dir = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    assets_dir = frontend_dir / "assets"
    if not frontend_dir.is_dir() or not assets_dir.is_dir():
        return

    app.mount("/assets", StaticFiles(directory=assets_dir), name="frontend-assets")

    @app.get("/{requested_path:path}", include_in_schema=False)
    def serve_frontend(requested_path: str) -> FileResponse:
        """Return static assets or the SPA entry point without masking API 404 responses."""
        if requested_path.startswith(("admin/", "auth/", "health", "projects/", "users/")):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource was not found.")
        requested_file = (frontend_dir / requested_path).resolve()
        try:
            requested_file.relative_to(frontend_dir.resolve())
        except ValueError:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource was not found.") from None
        if requested_path and requested_file.is_file():
            return FileResponse(requested_file)
        return FileResponse(frontend_dir / "index.html", media_type="text/html")
