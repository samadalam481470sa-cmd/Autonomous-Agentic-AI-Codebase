"""Fail-closed license policy for dependencies, models, and first-party code."""

from .policy import (
    DEFAULT_LICENSE_POLICY,
    DEFAULT_MODEL_POLICY,
    ModelLicenseError,
    check_model,
    check_model_manifest,
    evaluate_license,
    load_json,
    normalize_license,
    normalize_metadata_license,
    require_model_use,
    validate_model_policy,
)

__all__ = [
    "DEFAULT_LICENSE_POLICY",
    "DEFAULT_MODEL_POLICY",
    "ModelLicenseError",
    "check_model",
    "check_model_manifest",
    "evaluate_license",
    "load_json",
    "normalize_license",
    "normalize_metadata_license",
    "require_model_use",
    "validate_model_policy",
]
