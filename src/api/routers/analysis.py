"""Analysis-tag routes for the HDFS control plane."""

from __future__ import annotations

import json
import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status

from src.api.deps import (
    CurrentUser,
    get_current_user,
    get_database,
    get_settings,
    not_found,
    require_project_role,
)
from src.api.inference_dispatch import dispatch_analysis_run
from src.api.responses import (
    analysis_result_summary,
    analysis_result_trace,
    analysis_run_from_store,
    anomaly_response,
    provisional_response,
)
from src.api.schemas import (
    AnalysisResultsQuery,
    AnalysisResultsResponse,
    AnalysisRunCreate,
    AnalysisRunResponse,
    AnalysisRunStatus,
    ModelStatus,
    ProjectRole,
    ProvisionalResultsQuery,
    ProvisionalResultsResponse,
)
from src.api.settings import ApiSettings
from src.api.storage import (
    AnomalyResultPageQuery,
    ApiDatabase,
    ProvisionalResultPageQuery,
    ResultCursorError,
    RunStatusConflict,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["analysis"])


def _dispatch_queued_run(run_id: UUID, settings: ApiSettings, database: ApiDatabase) -> None:
    outcome = dispatch_analysis_run(run_id, settings)
    if outcome.accepted:
        return
    report = json.dumps({"execution": outcome.public_message}, sort_keys=True)
    try:
        database.transition_analysis_run(
            run_id,
            expected_status="queued",
            next_status="failed",
            actor_user_id=None,
            error_code=outcome.error_code,
            validation_report_json=report,
        )
    except RunStatusConflict:
        logger.warning(
            "Could not mark run %s as failed after dispatch; it is no longer queued",
            run_id,
        )


@router.get(
    "/projects/{project_id}/analysis-runs",
    response_model=list[AnalysisRunResponse],
)
def list_analysis_runs(
    project_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    database: ApiDatabase = Depends(get_database),
) -> list[AnalysisRunResponse]:
    """List analysis runs scoped to an authorized project."""
    require_project_role(database, project_id, user, {ProjectRole.OPERATOR})
    return [analysis_run_from_store(item) for item in database.list_analysis_runs(project_id)]


@router.post(
    "/projects/{project_id}/analysis-runs",
    response_model=AnalysisRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_analysis_run(
    project_id: UUID,
    request: AnalysisRunCreate,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(get_current_user),
    database: ApiDatabase = Depends(get_database),
    settings: ApiSettings = Depends(get_settings),
) -> AnalysisRunResponse:
    """Queue analysis of an admitted same-project dataset without re-scanning the log."""
    require_project_role(database, project_id, user, {ProjectRole.OPERATOR})
    model = database.get_model_version(request.model_version_id)
    if model is None or model["project_id"] != str(project_id):
        raise not_found("Model version")
    if model["status"] != ModelStatus.PUBLISHED.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only published model versions can start analysis.",
        )
    if not model.get("preprocessing_bundle_id"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Published model is not inference-ready.",
        )
    dataset = database.get_dataset(request.dataset_id)
    if dataset is None or dataset["project_id"] != str(project_id):
        raise not_found("Dataset")

    run = database.create_analysis_run(
        project_id=project_id,
        model_version_id=request.model_version_id,
        requested_by_user_id=user.id,
        log_reference=str(dataset["object_reference"]),
        status=AnalysisRunStatus.QUEUED.value,
        validation_report_json=None,
        error_code=None,
        completed_at=None,
        actor_user_id=user.id,
        results_summary_json=None,
        dataset_id=request.dataset_id,
    )
    background_tasks.add_task(_dispatch_queued_run, UUID(str(run["id"])), settings, database)
    return analysis_run_from_store(run)


@router.get(
    "/projects/{project_id}/analysis-runs/{analysis_run_id}",
    response_model=AnalysisRunResponse,
)
def get_analysis_run(
    project_id: UUID,
    analysis_run_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    database: ApiDatabase = Depends(get_database),
) -> AnalysisRunResponse:
    """Get a single project-scoped analysis run."""
    require_project_role(database, project_id, user, {ProjectRole.OPERATOR})
    run = database.get_analysis_run(analysis_run_id)
    if run is None or run["project_id"] != str(project_id):
        raise not_found("Analysis run")
    return analysis_run_from_store(run)


@router.get(
    "/projects/{project_id}/analysis-runs/{analysis_run_id}/results",
    response_model=AnalysisResultsResponse,
)
def get_analysis_results(
    project_id: UUID,
    analysis_run_id: UUID,
    results_query: Annotated[AnalysisResultsQuery, Query()],
    user: CurrentUser = Depends(get_current_user),
    database: ApiDatabase = Depends(get_database),
) -> AnalysisResultsResponse:
    """Return one typed page of HDFS anomalies without executing untrusted models."""
    require_project_role(database, project_id, user, {ProjectRole.OPERATOR})
    run = database.get_analysis_run(analysis_run_id)
    if run is None or run["project_id"] != str(project_id):
        raise not_found("Analysis run")
    model = database.get_model_version(UUID(str(run["model_version_id"])))
    if model is None or str(model["project_id"]) != str(project_id):
        raise not_found("Analysis run")
    response = analysis_run_from_store(run)
    try:
        page = database.list_anomaly_result_page(
            analysis_run_id,
            AnomalyResultPageQuery(
                limit=results_query.limit,
                sort=results_query.sort.value,
                block_id_prefix=results_query.block_id_prefix,
                min_score=results_query.min_score,
                cursor=results_query.cursor,
            ),
        )
    except ResultCursorError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Result cursor is invalid.",
        ) from None
    return AnalysisResultsResponse(
        run=response,
        summary=analysis_result_summary(run, response),
        trace=analysis_result_trace(run, model),
        anomalies=[anomaly_response(item) for item in page.rows],
        next_cursor=page.next_cursor,
        query=results_query,
    )


@router.get(
    "/projects/{project_id}/analysis-runs/{analysis_run_id}/provisional-results",
    response_model=ProvisionalResultsResponse,
)
def get_provisional_results(
    project_id: UUID,
    analysis_run_id: UUID,
    results_query: Annotated[ProvisionalResultsQuery, Query()],
    user: CurrentUser = Depends(get_current_user),
    database: ApiDatabase = Depends(get_database),
) -> ProvisionalResultsResponse:
    """Return one typed page of unscored provisional HDFS histories."""
    require_project_role(database, project_id, user, {ProjectRole.OPERATOR})
    run = database.get_analysis_run(analysis_run_id)
    if run is None or run["project_id"] != str(project_id):
        raise not_found("Analysis run")
    model = database.get_model_version(UUID(str(run["model_version_id"])))
    if model is None or str(model["project_id"]) != str(project_id):
        raise not_found("Analysis run")
    try:
        page = database.list_provisional_result_page(
            analysis_run_id,
            ProvisionalResultPageQuery(
                limit=results_query.limit,
                block_id_prefix=results_query.block_id_prefix,
                cursor=results_query.cursor,
            ),
        )
    except ResultCursorError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Result cursor is invalid.",
        ) from None
    return ProvisionalResultsResponse(
        items=[provisional_response(item) for item in page.rows],
        next_cursor=page.next_cursor,
        query=results_query,
    )
