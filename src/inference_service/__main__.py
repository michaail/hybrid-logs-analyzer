"""Launch the private HDFS inference service."""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    """Run the inference ASGI app. Requires INFERENCE_INTERNAL_TOKEN."""

    port = int(os.environ.get("PORT", "8080"))
    uvicorn.run(
        "src.inference_service.main:create_app",
        factory=True,
        host="0.0.0.0",
        port=port,
    )


if __name__ == "__main__":
    main()
