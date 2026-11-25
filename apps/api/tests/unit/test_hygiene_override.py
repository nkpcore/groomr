"""Unit tests for mandatory hygiene safety override and adapter safety rules."""

import hashlib
import hmac

import pytest

from chair_api.adapters.base import LocalSignedStorageAdapter, TestModePaymentAdapter
from chair_api.core.config import Settings
from chair_api.domain.enums import BranchVerificationStatus, InspectionOutcome
from chair_api.domain.hygiene import HygieneChecklistInput, evaluate_inspection


def test_critical_hygiene_failure_overrides_perfect_score() -> None:
    result = evaluate_inspection(
        HygieneChecklistInput(
            numerical_score=98,
            single_use_blades_ok=False,
            sharps_disposal_ok=True,
            instrument_disinfection_ok=True,
            fresh_towels_ok=True,
        )
    )
    assert result.outcome == InspectionOutcome.FAILED_CRITICAL
    assert result.failed_critical_checks == ("single_use_blades_ok",)
    assert result.resulting_verification_status == BranchVerificationStatus.SUSPENDED


def test_passing_all_critical_and_score_grants_chair_verified() -> None:
    result = evaluate_inspection(
        HygieneChecklistInput(
            numerical_score=85,
            single_use_blades_ok=True,
            sharps_disposal_ok=True,
            instrument_disinfection_ok=True,
            fresh_towels_ok=True,
        )
    )
    assert result.outcome == InspectionOutcome.PASSED
    assert result.resulting_verification_status == BranchVerificationStatus.CHAIR_VERIFIED


def test_low_score_with_safe_critical_items_requires_corrective_action() -> None:
    result = evaluate_inspection(
        HygieneChecklistInput(
            numerical_score=72,
            single_use_blades_ok=True,
            sharps_disposal_ok=True,
            instrument_disinfection_ok=True,
            fresh_towels_ok=True,
        )
    )
    assert result.outcome == InspectionOutcome.CORRECTIVE_ACTION_REQUIRED
    assert result.resulting_verification_status == BranchVerificationStatus.ACTION_REQUIRED


def test_storage_adapter_rejects_spoofed_magic_bytes() -> None:
    storage = LocalSignedStorageAdapter(root_dir=".storage", signing_secret="test-secret")
    with pytest.raises(ValueError, match="magic bytes"):
        storage.validate_upload(
            content=b"#!/bin/sh\necho pwned",
            declared_mime="image/png",
            max_bytes=1024,
        )


def test_webhook_hmac_verification() -> None:
    adapter = TestModePaymentAdapter()
    body = b'{"event":"payment.captured"}'
    secret = "whsec_test_123"
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert adapter.verify_webhook_signature(payload_bytes=body, signature=sig, secret=secret)
    assert not adapter.verify_webhook_signature(
        payload_bytes=body, signature="bad-sig", secret=secret
    )


def test_production_settings_reject_mock_providers() -> None:
    with pytest.raises(ValueError, match="Mock OTP"):
        Settings(app_env="production", auth_otp_provider="mock")

    with pytest.raises(ValueError, match="Mock OTP"):
        Settings(app_env="staging", auth_otp_provider="mock")

    with pytest.raises(ValueError, match="SECRET_KEY"):
        Settings(
            app_env="staging",
            auth_otp_provider="msg91",
            payment_provider="razorpay",
            payment_test_mode=False,
            secret_key="replace-with-64-char-random-hex-for-local-dev",
            storage_signing_secret="9f4f9e8b7a6c5d4e3f2a1b0c9d8e7f6a",
        )
