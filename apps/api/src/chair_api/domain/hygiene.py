"""Hygiene inspection evaluator enforcing mandatory critical safety overrides."""

from dataclasses import dataclass

from chair_api.domain.enums import BranchVerificationStatus, InspectionOutcome

PASSING_SCORE_THRESHOLD = 80


@dataclass(frozen=True)
class HygieneChecklistInput:
    numerical_score: int
    single_use_blades_ok: bool
    sharps_disposal_ok: bool
    instrument_disinfection_ok: bool
    fresh_towels_ok: bool


@dataclass(frozen=True)
class HygieneEvaluationResult:
    outcome: InspectionOutcome
    failed_critical_checks: tuple[str, ...]
    resulting_verification_status: BranchVerificationStatus


def evaluate_inspection(checklist: HygieneChecklistInput) -> HygieneEvaluationResult:
    """Force FAILED_CRITICAL whenever any mandatory safety check fails, regardless of score."""
    if not 0 <= checklist.numerical_score <= 100:
        raise ValueError("numerical_score must be between 0 and 100.")

    failed: list[str] = []
    if not checklist.single_use_blades_ok:
        failed.append("single_use_blades_ok")
    if not checklist.sharps_disposal_ok:
        failed.append("sharps_disposal_ok")
    if not checklist.instrument_disinfection_ok:
        failed.append("instrument_disinfection_ok")
    if not checklist.fresh_towels_ok:
        failed.append("fresh_towels_ok")

    if failed:
        return HygieneEvaluationResult(
            outcome=InspectionOutcome.FAILED_CRITICAL,
            failed_critical_checks=tuple(failed),
            resulting_verification_status=BranchVerificationStatus.SUSPENDED,
        )

    if checklist.numerical_score >= PASSING_SCORE_THRESHOLD:
        return HygieneEvaluationResult(
            outcome=InspectionOutcome.PASSED,
            failed_critical_checks=(),
            resulting_verification_status=BranchVerificationStatus.CHAIR_VERIFIED,
        )

    return HygieneEvaluationResult(
        outcome=InspectionOutcome.CORRECTIVE_ACTION_REQUIRED,
        failed_critical_checks=(),
        resulting_verification_status=BranchVerificationStatus.ACTION_REQUIRED,
    )
