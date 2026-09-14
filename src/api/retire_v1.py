"""One-off administrator cleanup for leftover v1 / null-bundle model rows."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any
from uuid import UUID

from src.api.object_store import ObjectStore, build_object_store
from src.api.settings import ApiSettings
from src.api.storage import ApiDatabase, DatabaseIntegrityError, DatabaseRow
from src.modules.model_package import PACKAGE_FORMAT_V1

ACTION_DELETE = "delete"
ACTION_SKIP_DEPENDENT = "skip-dependent"
ACTION_SKIP_WORKSPACE = "skip-workspace"


@dataclass(frozen=True)
class RetireCandidate:
    """One leftover model the CLI may delete or skip."""

    model_id: UUID
    format_name: str | None
    bundle_id: str | None
    bundle_prefix: str | None
    storage_kind: str
    package_reference: str
    run_count: int
    action: str


@dataclass(frozen=True)
class RetireReport:
    """Printed inventory plus the process exit code."""

    candidates: tuple[RetireCandidate, ...]
    exit_code: int


def metadata_format(metadata_json: str) -> str | None:
    """Return metadata_json.format when it is a string; ignore feature_contract."""

    try:
        payload = json.loads(metadata_json)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    value = payload.get("format")
    return value if isinstance(value, str) and value else None


def is_retire_candidate(row: Mapping[str, Any]) -> bool:
    """True when format is v1 or the model has no preprocessing bundle id."""

    if metadata_format(str(row.get("metadata_json") or "")) == PACKAGE_FORMAT_V1:
        return True
    bundle_id = row.get("preprocessing_bundle_id")
    return bundle_id is None or str(bundle_id).strip() == ""


def _package_reference(row: Mapping[str, Any]) -> str:
    value = row.get("package_reference")
    return str(value).strip() if value is not None else ""


def classify_candidate(row: DatabaseRow, run_count: int) -> RetireCandidate:
    """Decide delete vs skip without mutating storage."""

    bundle_id_raw = row.get("preprocessing_bundle_id")
    bundle_id = str(bundle_id_raw) if bundle_id_raw else None
    prefix_raw = row.get("preprocessing_bundle_prefix")
    bundle_prefix = str(prefix_raw).strip() if prefix_raw else None
    storage_kind = str(row.get("storage_kind") or "")
    package_reference = _package_reference(row)
    if run_count > 0:
        action = ACTION_SKIP_DEPENDENT
    elif storage_kind != "object" or not package_reference:
        action = ACTION_SKIP_WORKSPACE
    else:
        action = ACTION_DELETE
    return RetireCandidate(
        model_id=UUID(str(row["id"])),
        format_name=metadata_format(str(row.get("metadata_json") or "")),
        bundle_id=bundle_id,
        bundle_prefix=bundle_prefix or None,
        storage_kind=storage_kind,
        package_reference=package_reference,
        run_count=run_count,
        action=action,
    )


def format_candidate_line(candidate: RetireCandidate) -> str:
    """One operator-readable inventory line."""

    format_name = candidate.format_name or "-"
    bundle_null = "yes" if candidate.bundle_id is None else "no"
    return (
        f"id={candidate.model_id} format={format_name} bundle_null={bundle_null} "
        f"storage_kind={candidate.storage_kind} runs={candidate.run_count} "
        f"action={candidate.action}"
    )


def retire_v1_models(
    database: ApiDatabase,
    object_store: ObjectStore,
    *,
    apply: bool,
) -> RetireReport:
    """Inventory leftovers; when apply is true, delete eligible object-kind rows."""

    candidates: list[RetireCandidate] = []
    for row in database.list_all_model_versions():
        if not is_retire_candidate(row):
            continue
        model_id = UUID(str(row["id"]))
        run_count = database.count_analysis_runs_for_model(model_id)
        candidates.append(classify_candidate(row, run_count))

    if apply:
        applied: list[RetireCandidate] = []
        for candidate in candidates:
            if candidate.action != ACTION_DELETE:
                applied.append(candidate)
                continue
            object_store.delete_prefix(candidate.package_reference)
            if candidate.bundle_prefix:
                object_store.delete_prefix(candidate.bundle_prefix)
            try:
                database.delete_model_version(candidate.model_id)
            except DatabaseIntegrityError:
                applied.append(
                    replace(
                        candidate,
                        run_count=max(candidate.run_count, 1),
                        action=ACTION_SKIP_DEPENDENT,
                    )
                )
                continue
            applied.append(candidate)
        candidates = applied

    exit_code = (
        1 if any(item.action == ACTION_SKIP_DEPENDENT for item in candidates) else 0
    )
    return RetireReport(candidates=tuple(candidates), exit_code=exit_code)


def main(argv: list[str] | None = None) -> int:
    """Run leftover v1 cleanup. Default is dry-run; --apply mutates."""

    parser = argparse.ArgumentParser(
        description=(
            "Inventory leftover attribute-aware-gae-v1 or null-bundle model rows. "
            "Deletes object prefixes and model rows only with --apply."
        )
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="List candidates without deleting (default).",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Delete object prefixes and eligible model rows.",
    )
    arguments = parser.parse_args(argv)
    apply = bool(arguments.apply)

    try:
        settings = ApiSettings.from_environment()
    except RuntimeError as error:
        parser.error(str(error))

    database = ApiDatabase(settings.database_url)
    object_store = build_object_store(settings)
    report = retire_v1_models(database, object_store, apply=apply)
    mode_label = "apply" if apply else "dry-run"
    print(f"retire-v1 {mode_label}: {len(report.candidates)} candidate(s)")
    for candidate in report.candidates:
        print(format_candidate_line(candidate))
    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
