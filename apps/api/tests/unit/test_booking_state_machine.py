"""Unit tests for authoritative BookingStatus state machine transitions."""

import pytest

from chair_api.core.errors import ChairAPIError
from chair_api.domain.booking_states import (
    TERMINAL_BOOKING_STATUSES,
    validate_booking_transition,
)
from chair_api.domain.enums import BookingStatus, UserRole


def test_valid_happy_path_transitions() -> None:
    assert (
        validate_booking_transition(
            current_status=BookingStatus.HELD,
            target_status=BookingStatus.CONFIRMED,
            actor_role=UserRole.CUSTOMER,
        )
        == BookingStatus.CONFIRMED
    )
    assert (
        validate_booking_transition(
            current_status=BookingStatus.CONFIRMED,
            target_status=BookingStatus.CHECKED_IN,
            actor_role=UserRole.PARTNER_STAFF,
        )
        == BookingStatus.CHECKED_IN
    )
    assert (
        validate_booking_transition(
            current_status=BookingStatus.CHECKED_IN,
            target_status=BookingStatus.IN_SERVICE,
            actor_role=UserRole.PARTNER_OWNER,
        )
        == BookingStatus.IN_SERVICE
    )
    assert (
        validate_booking_transition(
            current_status=BookingStatus.IN_SERVICE,
            target_status=BookingStatus.COMPLETED,
            actor_role=UserRole.PARTNER_STAFF,
        )
        == BookingStatus.COMPLETED
    )


def test_customer_cannot_self_complete_or_check_in() -> None:
    with pytest.raises(ChairAPIError) as exc:
        validate_booking_transition(
            current_status=BookingStatus.CONFIRMED,
            target_status=BookingStatus.CHECKED_IN,
            actor_role=UserRole.CUSTOMER,
        )
    assert exc.value.status_code == 403
    assert exc.value.code == "BOOKING_TRANSITION_FORBIDDEN"


def test_terminal_states_reject_further_transitions() -> None:
    for terminal in TERMINAL_BOOKING_STATUSES:
        with pytest.raises(ChairAPIError) as exc:
            validate_booking_transition(
                current_status=terminal,
                target_status=BookingStatus.CONFIRMED,
                actor_role=UserRole.ADMIN,
            )
        assert exc.value.status_code == 409
        assert exc.value.code == "BOOKING_TERMINAL_STATE"


def test_cannot_skip_check_in_before_completion() -> None:
    with pytest.raises(ChairAPIError) as exc:
        validate_booking_transition(
            current_status=BookingStatus.CONFIRMED,
            target_status=BookingStatus.COMPLETED,
            actor_role=UserRole.PARTNER_OWNER,
        )
    assert exc.value.status_code == 409
    assert exc.value.code == "INVALID_BOOKING_TRANSITION"
