"""Authoritative BookingStatus state machine and actor authorization rules."""

from typing import Literal

from fastapi import status

from chair_api.core.errors import ChairAPIError
from chair_api.domain.enums import BookingStatus, UserRole

ActorRole = UserRole | Literal["SYSTEM"]

PARTNER_ROLES: frozenset[ActorRole] = frozenset({UserRole.PARTNER_OWNER, UserRole.PARTNER_STAFF})

TERMINAL_BOOKING_STATUSES: frozenset[BookingStatus] = frozenset(
    {
        BookingStatus.COMPLETED,
        BookingStatus.CANCELLED,
        BookingStatus.EXPIRED,
        BookingStatus.NO_SHOW,
    }
)

ACTIVE_ALLOCATION_BOOKING_STATUSES: frozenset[BookingStatus] = frozenset(
    {
        BookingStatus.HELD,
        BookingStatus.REQUESTED,
        BookingStatus.CONFIRMED,
        BookingStatus.CHECKED_IN,
        BookingStatus.IN_SERVICE,
    }
)

# Maps (from_status, to_status) -> set of actors permitted to execute the transition.
ALLOWED_BOOKING_TRANSITIONS: dict[tuple[BookingStatus, BookingStatus], frozenset[ActorRole]] = {
    (BookingStatus.HELD, BookingStatus.CONFIRMED): frozenset(
        {UserRole.CUSTOMER, UserRole.ADMIN, "SYSTEM"}
    ),
    (BookingStatus.HELD, BookingStatus.CANCELLED): frozenset(
        {UserRole.CUSTOMER, UserRole.ADMIN}
    ),
    (BookingStatus.HELD, BookingStatus.EXPIRED): frozenset({"SYSTEM", UserRole.ADMIN}),
    (BookingStatus.REQUESTED, BookingStatus.CONFIRMED): frozenset(
        {*PARTNER_ROLES, UserRole.ADMIN}
    ),
    (BookingStatus.REQUESTED, BookingStatus.CANCELLED): frozenset(
        {UserRole.CUSTOMER, *PARTNER_ROLES, UserRole.ADMIN}
    ),
    (BookingStatus.REQUESTED, BookingStatus.EXPIRED): frozenset({"SYSTEM", UserRole.ADMIN}),
    (BookingStatus.CONFIRMED, BookingStatus.CHECKED_IN): frozenset(
        {*PARTNER_ROLES, UserRole.ADMIN}
    ),
    (BookingStatus.CONFIRMED, BookingStatus.CANCELLED): frozenset(
        {UserRole.CUSTOMER, *PARTNER_ROLES, UserRole.ADMIN}
    ),
    (BookingStatus.CONFIRMED, BookingStatus.NO_SHOW): frozenset(
        {*PARTNER_ROLES, UserRole.ADMIN, "SYSTEM"}
    ),
    (BookingStatus.CHECKED_IN, BookingStatus.IN_SERVICE): frozenset(
        {*PARTNER_ROLES, UserRole.ADMIN}
    ),
    (BookingStatus.CHECKED_IN, BookingStatus.CANCELLED): frozenset(
        {*PARTNER_ROLES, UserRole.ADMIN}
    ),
    (BookingStatus.IN_SERVICE, BookingStatus.COMPLETED): frozenset(
        {*PARTNER_ROLES, UserRole.ADMIN}
    ),
}


def validate_booking_transition(
    *,
    current_status: BookingStatus,
    target_status: BookingStatus,
    actor_role: ActorRole,
) -> BookingStatus:
    """Validate booking state transition and actor role; never trust client state strings."""
    if current_status in TERMINAL_BOOKING_STATUSES:
        raise ChairAPIError(
            status_code=status.HTTP_409_CONFLICT,
            code="BOOKING_TERMINAL_STATE",
            message=f"Booking in terminal state '{current_status}' cannot transition.",
            details={"current_status": current_status, "target_status": target_status},
        )

    allowed_actors = ALLOWED_BOOKING_TRANSITIONS.get((current_status, target_status))
    if allowed_actors is None:
        raise ChairAPIError(
            status_code=status.HTTP_409_CONFLICT,
            code="INVALID_BOOKING_TRANSITION",
            message=f"Transition from '{current_status}' to '{target_status}' is not allowed.",
            details={"current_status": current_status, "target_status": target_status},
        )

    if actor_role not in allowed_actors:
        raise ChairAPIError(
            status_code=status.HTTP_403_FORBIDDEN,
            code="BOOKING_TRANSITION_FORBIDDEN",
            message=f"Role '{actor_role}' cannot move booking to '{target_status}'.",
            details={"current_status": current_status, "target_status": target_status},
        )

    return target_status
