"""Unit tests for the pure CHAIR multi-service slot availability calculator."""

import uuid
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from chair_api.services.availability import (
    AvailabilityInput,
    ServiceSpec,
    ShiftWindowSpec,
    StaffSpec,
    TimeInterval,
    WalkInDemandSpec,
    compute_available_slots,
    resolve_branch_operating_window_utc,
    schedule_walk_in_demands,
)

IST = ZoneInfo("Asia/Kolkata")


def _ist_utc(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, 26, hour, minute, tzinfo=IST).astimezone(UTC)


def _base_input(
    *,
    online_booking_paused: bool = False,
    closed: bool = False,
    blocks: list[TimeInterval] | None = None,
    staff_blocks: dict[uuid.UUID, list[TimeInterval]] | None = None,
    staff_busy: dict[uuid.UUID, list[TimeInterval]] | None = None,
    resource_busy: dict[uuid.UUID, list[TimeInterval]] | None = None,
    unassigned_walk_ins: list[TimeInterval] | None = None,
    requested_services: list[uuid.UUID] | None = None,
    staff_filter_id: uuid.UUID | None = None,
) -> tuple[AvailabilityInput, uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    branch_id = uuid.uuid4()
    svc_haircut = uuid.uuid4()
    svc_beard = uuid.uuid4()
    barber_1 = uuid.uuid4()
    barber_2 = uuid.uuid4()
    chair_1 = uuid.uuid4()

    services = {
        svc_haircut: ServiceSpec(
            branch_service_id=svc_haircut,
            duration_minutes=30,
            buffer_before_minutes=0,
            buffer_after_minutes=5,
        ),
        svc_beard: ServiceSpec(
            branch_service_id=svc_beard,
            duration_minutes=20,
            buffer_before_minutes=0,
            buffer_after_minutes=5,
        ),
    }

    staff_list = [
        StaffSpec(
            staff_id=barber_1,
            display_name="[DEMO] Rakesh",
            is_verified_staff=True,
            is_accepting_bookings=True,
            is_active=True,
            qualified_service_durations={svc_haircut: 30, svc_beard: 20},
        ),
        StaffSpec(
            staff_id=barber_2,
            display_name="[DEMO] Imran",
            is_verified_staff=True,
            is_accepting_bookings=True,
            is_active=True,
            qualified_service_durations={svc_haircut: 30},  # Not qualified for beard
        ),
    ]

    window = None if closed else TimeInterval(start_utc=_ist_utc(10, 0), end_utc=_ist_utc(13, 0))
    shifts = [
        ShiftWindowSpec(staff_id=barber_1, start_utc=_ist_utc(10, 0), end_utc=_ist_utc(13, 0)),
        ShiftWindowSpec(staff_id=barber_2, start_utc=_ist_utc(10, 0), end_utc=_ist_utc(13, 0)),
    ]

    inp = AvailabilityInput(
        branch_id=branch_id,
        online_booking_paused=online_booking_paused,
        branch_window_utc=window,
        requested_service_ids=requested_services or [svc_haircut],
        services_by_id=services,
        staff_list=staff_list,
        staff_shifts=shifts,
        branch_blocks=blocks or [],
        staff_blocks=staff_blocks or {},
        staff_busy_allocations_or_holds=staff_busy or {},
        active_resource_ids=[chair_1],
        resource_busy_intervals=resource_busy or {},
        unassigned_walk_ins=unassigned_walk_ins or [],
        now_utc=_ist_utc(9, 30),
        lead_time_minutes=15,
        slot_step_minutes=15,
        staff_filter_id=staff_filter_id,
    )
    return inp, svc_haircut, svc_beard, barber_1, chair_1


def test_resolve_operating_window_converts_ist_and_handles_closed_days() -> None:
    hours = {"thu": {"open": "09:30", "close": "21:30"}, "fri": {"closed": True}}
    thu_window = resolve_branch_operating_window_utc(hours, date(2026, 11, 26), "Asia/Kolkata")
    assert thu_window is not None
    assert thu_window.start_utc.astimezone(IST).hour == 9
    assert thu_window.end_utc.astimezone(IST).minute == 30

    fri_window = resolve_branch_operating_window_utc(hours, date(2026, 11, 27), "Asia/Kolkata")
    assert fri_window is None


def test_paused_or_closed_branch_returns_zero_slots() -> None:
    paused_inp, *_ = _base_input(online_booking_paused=True)
    paused_res = compute_available_slots(paused_inp)
    assert paused_res.online_booking_paused is True
    assert paused_res.slots == []

    closed_inp, *_ = _base_input(closed=True)
    closed_res = compute_available_slots(closed_inp)
    assert closed_res.is_branch_closed is True
    assert closed_res.slots == []


def test_multi_service_qualification_buffers_and_chair_capacity_enforced() -> None:
    # Requesting Haircut (30m) + Beard (20m) = 50m + 5m after-buffer.
    # Only barber_1 is qualified for Beard; single chair_1 is busy 10:30-11:15.
    probe, svc_haircut, svc_beard, barber_1, chair_1 = _base_input()
    inp = AvailabilityInput(
        branch_id=probe.branch_id,
        online_booking_paused=False,
        branch_window_utc=probe.branch_window_utc,
        requested_service_ids=[svc_haircut, svc_beard],
        services_by_id=probe.services_by_id,
        staff_list=probe.staff_list,
        staff_shifts=probe.staff_shifts,
        branch_blocks=[],
        staff_blocks={},
        staff_busy_allocations_or_holds={},
        active_resource_ids=[chair_1],
        resource_busy_intervals={chair_1: [TimeInterval(_ist_utc(10, 30), _ist_utc(11, 15))]},
        unassigned_walk_ins=[],
        now_utc=_ist_utc(9, 30),
    )

    res = compute_available_slots(inp)
    starts_ist = [
        (s.start_at.astimezone(IST).hour, s.start_at.astimezone(IST).minute) for s in res.slots
    ]

    # 10:00 + 50m service + 5m buffer = 10:55 overlaps 10:30 chair block -> MUST be excluded!
    assert (10, 0) not in starts_ist
    # 11:15 is the first free 50m+5m slot after chair frees at 11:15
    assert (11, 15) in starts_ist
    # Only barber_1 is qualified for both Haircut and Beard
    for slot in res.slots:
        assert [st.staff_id for st in slot.available_staff] == [barber_1]


def test_schedule_blocks_walk_ins_and_lead_time_exclude_slots() -> None:
    probe, *_ = _base_input()
    # Add unassigned walk-in consuming the sole chair from 10:00 to 10:45,
    # and a branch maintenance block from 11:30 to 12:30.
    inp = AvailabilityInput(
        branch_id=probe.branch_id,
        online_booking_paused=False,
        branch_window_utc=probe.branch_window_utc,
        requested_service_ids=probe.requested_service_ids,
        services_by_id=probe.services_by_id,
        staff_list=probe.staff_list,
        staff_shifts=probe.staff_shifts,
        branch_blocks=[TimeInterval(_ist_utc(11, 30), _ist_utc(12, 30))],
        staff_blocks={},
        staff_busy_allocations_or_holds={},
        active_resource_ids=probe.active_resource_ids,
        resource_busy_intervals={},
        unassigned_walk_ins=[TimeInterval(_ist_utc(10, 0), _ist_utc(10, 45))],
        now_utc=_ist_utc(10, 15),  # +15m lead time => earliest start 10:30
    )

    res = compute_available_slots(inp)
    starts_ist = [
        (s.start_at.astimezone(IST).hour, s.start_at.astimezone(IST).minute) for s in res.slots
    ]
    assert (10, 15) not in starts_ist  # lead time
    assert (10, 30) not in starts_ist  # blocked by walk-in
    assert (10, 45) in starts_ist  # 10:45-11:15 (+5m = 11:20) clears 11:30 maintenance
    assert (11, 0) not in starts_ist  # 11:00+35m=11:35 overlaps maintenance
    assert (12, 30) in starts_ist  # 12:30-13:00 fits cleanly before close


def test_queued_unallocated_walk_ins_serialize_and_consume_barber_and_chair() -> None:
    # Single barber + 2 chairs with 2 queued 30m unassigned walk-ins at 10:00
    probe, svc_haircut, _, barber_1, chair_1 = _base_input()
    chair_2 = uuid.uuid4()
    sole_barber = [probe.staff_list[0]]
    sole_shift = [probe.staff_shifts[0]]

    staff_busy: dict[uuid.UUID, list[TimeInterval]] = {}
    resource_busy: dict[uuid.UUID, list[TimeInterval]] = {}
    unassigned_staff: list[TimeInterval] = []
    unassigned_chair: list[TimeInterval] = []

    schedule_walk_in_demands(
        walk_ins=[
            WalkInDemandSpec(
                checked_in_at=_ist_utc(9, 50),
                estimated_duration_minutes=30,
                queue_position=1,
                staff_id=None,
                resource_id=None,
            ),
            WalkInDemandSpec(
                checked_in_at=_ist_utc(9, 55),
                estimated_duration_minutes=30,
                queue_position=2,
                staff_id=None,
                resource_id=None,
            ),
        ],
        now_utc=_ist_utc(10, 0),
        accepting_staff_count=1,
        active_chair_count=2,
        staff_busy=staff_busy,
        resource_busy=resource_busy,
        unassigned_staff_demand=unassigned_staff,
        unassigned_chair_demand=unassigned_chair,
    )

    inp = AvailabilityInput(
        branch_id=probe.branch_id,
        online_booking_paused=False,
        branch_window_utc=probe.branch_window_utc,
        requested_service_ids=[svc_haircut],
        services_by_id=probe.services_by_id,
        staff_list=sole_barber,
        staff_shifts=sole_shift,
        branch_blocks=[],
        staff_blocks={},
        staff_busy_allocations_or_holds=staff_busy,
        active_resource_ids=[chair_1, chair_2],
        resource_busy_intervals=resource_busy,
        unassigned_staff_demand=unassigned_staff,
        unassigned_chair_demand=unassigned_chair,
        now_utc=_ist_utc(9, 45),
    )

    res = compute_available_slots(inp)
    starts_ist = [
        (s.start_at.astimezone(IST).hour, s.start_at.astimezone(IST).minute) for s in res.slots
    ]
    # Walk-in 1 occupies 10:00-10:30, Walk-in 2 occupies 10:30-11:00 sequentially on sole barber!
    assert (10, 0) not in starts_ist
    assert (10, 30) not in starts_ist
    assert (10, 45) not in starts_ist
    assert (11, 0) in starts_ist

    # Also test nullable resource_id allocation/hold consumes chair capacity on other barber
    inp_nullable_res = AvailabilityInput(
        branch_id=probe.branch_id,
        online_booking_paused=False,
        branch_window_utc=probe.branch_window_utc,
        requested_service_ids=[svc_haircut],
        services_by_id=probe.services_by_id,
        staff_list=probe.staff_list,
        staff_shifts=probe.staff_shifts,
        branch_blocks=[],
        staff_blocks={},
        staff_busy_allocations_or_holds={
            barber_1: [TimeInterval(_ist_utc(10, 0), _ist_utc(10, 45))]
        },
        active_resource_ids=[chair_1],
        resource_busy_intervals={},
        unassigned_chair_demand=[TimeInterval(_ist_utc(10, 0), _ist_utc(10, 45))],
        now_utc=_ist_utc(9, 30),
    )
    res_nullable = compute_available_slots(inp_nullable_res)
    starts_nullable = [
        (s.start_at.astimezone(IST).hour, s.start_at.astimezone(IST).minute)
        for s in res_nullable.slots
    ]
    assert (10, 0) not in starts_nullable
    assert (10, 45) in starts_nullable
