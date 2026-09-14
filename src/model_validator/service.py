"""Private FastAPI service that probes uploaded HDFS package ZIP bytes."""

from __future__ import annotations

import hmac
import os
import tempfile
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.model_validator.runtime import scrub_environment, validate_release_with_probe
from src.model_validator.settings import ValidatorSettings
from src.modules.model_package import (
    MAX_ZIP_COMPRESSED_BYTES,
    PackageValidationIssue,
    PackageValidationResult,
    unpack_zip_bytes,
)


def create_app(settings: ValidatorSettings | None = None) -> FastAPI:
    """Create the private validator app. The public API must not import Torch from here."""

    if settings is None:
        resolved = ValidatorSettings.from_environment()
        scrub_environment()
    else:
        resolved = settings
    bearer = HTTPBearer(auto_error=False)

    def require_internal_token(
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    ) -> None:
        provided = credentials.credentials if credentials is not None else ""
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise _unauthorized()
        if not _tokens_match(provided, resolved.internal_token):
            raise _unauthorized()

    app = FastAPI(
        title="HDFS Model Validator",
        version="0.1.0",
        description="Private package probe. Accepts ZIP bytes only.",
    )

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        """Return liveness without opening a database or object store."""

        return {"status": "ok"}

    @app.post(
        "/internal/packages/validate",
        response_model=PackageValidationResult,
        tags=["validation"],
    )
    def validate_packages(
        _: None = Depends(require_internal_token),
        package: UploadFile = File(..., description="HDFS model package ZIP"),
        preprocessing_bundle: UploadFile = File(
            ...,
            description="Companion preprocessing-bundle ZIP",
        ),
    ) -> PackageValidationResult:
        """Extract privately, probe, and return the typed report."""

        package_bytes = package.file.read(MAX_ZIP_COMPRESSED_BYTES + 1)
        bundle_bytes = preprocessing_bundle.file.read(MAX_ZIP_COMPRESSED_BYTES + 1)
        size_issue = _zip_size_issue(package_bytes, path="package")
        if size_issue is not None:
            return size_issue
        size_issue = _zip_size_issue(bundle_bytes, path="preprocessing_bundle")
        if size_issue is not None:
            return size_issue
        with tempfile.TemporaryDirectory(prefix="model-validator-") as tmp:
            tmp_root = Path(tmp)
            package_root = tmp_root / "package"
            bundle_root = tmp_root / "bundle"
            package_root.mkdir()
            bundle_root.mkdir()
            unpack_report = unpack_zip_bytes(package_bytes, package_root)
            if not unpack_report.valid:
                return unpack_report
            bundle_unpack = unpack_zip_bytes(bundle_bytes, bundle_root)
            if not bundle_unpack.valid:
                return bundle_unpack
            return validate_release_with_probe(package_root, bundle_root)

    return app


def _zip_size_issue(archive_bytes: bytes, *, path: str) -> PackageValidationResult | None:
    if len(archive_bytes) > MAX_ZIP_COMPRESSED_BYTES:
        return PackageValidationResult.from_issues(
            [
                PackageValidationIssue(
                    path=path,
                    reason="Zip archive exceeds the 32 MiB compressed size limit.",
                )
            ]
        )
    if not archive_bytes:
        return PackageValidationResult.from_issues(
            [
                PackageValidationIssue(
                    path=path,
                    reason="Package zip must contain a readable archive.",
                )
            ]
        )
    return None


def _tokens_match(provided: str, expected: str) -> bool:
    if not expected:
        return False
    provided_bytes = provided.encode("utf-8")
    expected_bytes = expected.encode("utf-8")
    if len(provided_bytes) != len(expected_bytes):
        return False
    return hmac.compare_digest(provided_bytes, expected_bytes)


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid validator token.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def main() -> None:
    """Run the validator ASGI app. Requires MODEL_VALIDATOR_INTERNAL_TOKEN."""

    import uvicorn

    port = int(os.environ.get("PORT", "8080"))
    uvicorn.run(
        "src.model_validator.service:create_app",
        factory=True,
        host="0.0.0.0",
        port=port,
    )


if __name__ == "__main__":
    main()
