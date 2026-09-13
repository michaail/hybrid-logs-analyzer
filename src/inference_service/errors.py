"""Safe public error codes for private inference execution."""

from __future__ import annotations

SAFE_MESSAGES = {
    "MODEL_LOAD_FAILED": "The published model could not be loaded for inference.",
    "PREPROCESSING_BUNDLE_UNAVAILABLE": (
        "The bound preprocessing bundle is unavailable or failed verification."
    ),
    "PARSER_FAILED": "The frozen log parser could not be applied to this dataset.",
    "UNMATCHED_TEMPLATE": "An admitted log line did not match the frozen Drain templates.",
    "MISSING_CLUSTER_EMBEDDING": (
        "A parsed template has no frozen embedding in the preprocessing bundle."
    ),
    "COMPLETENESS_CATALOG_UNAVAILABLE": (
        "The pinned HDFS reference catalog is unavailable or failed verification."
    ),
    "INFERENCE_FAILED": "Inference could not complete for this analysis run.",
}


class InferenceExecutionError(RuntimeError):
    """Terminal inference failure with a stable public code and private cause."""

    def __init__(self, code: str, *, cause: str | None = None) -> None:
        if code not in SAFE_MESSAGES:
            code = "INFERENCE_FAILED"
        self.code = code
        self.public_message = SAFE_MESSAGES[code]
        self.cause = cause
        super().__init__(self.public_message)


def map_completeness_catalog_error(error: BaseException) -> InferenceExecutionError:
    """Map any catalog validation or load failure to the stable public code."""

    reason = getattr(error, "reason", None)
    if not isinstance(reason, str) or not reason.strip():
        reason = type(error).__name__
    return InferenceExecutionError("COMPLETENESS_CATALOG_UNAVAILABLE", cause=reason)
