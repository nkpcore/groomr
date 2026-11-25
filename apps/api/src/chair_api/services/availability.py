"""Deterministic multi-service slot availability calculator and batched DB loader."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import status
from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.ext.asyncio import AsyncSession

from chair_api.core.errors import ChairAPIError
from chair_api.db.models import (
    BookingAllocation,
    Branch,
    BranchService,
    Resource,
    Salon,
    ScheduleBlock,
    Service,
    SlotHold,
    Staff,
    StaffService,
    StaffShift,
    WalkIn,
)
from chair_api.domain.enums import BranchVerificationStatus

DEFAULT_TIMEZONE = "Asia/Kolkata"
_WEEKDAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


@dataclass(frozen=True, slots=True)
class TimeInterval:
    start_utc: datetime
    end_utc: datetime


@dataclass(frozen=True, slots=True)
class ServiceSpec:
    branch_service_id: uuid.UUID
    duration_minutes: int
    buffer_before_minutes: int
    buffer_after_minutes: int


@dataclass(frozen=True, slots=True)
class StaffSpec:
    staff_id: uuid.UUID
    display_name: str
    is_verified_staff: bool
    is_accepting_bookings: bool
    is_active: bool
    qualified_service_durations: dict[uuid.UUID, int]


@dataclass(frozen=True, slots=True)
class ShiftWindowSpec:
    staff_id: uuid.UUID
    start_utc: datetime
    end_utc: datetime


@dataclass(frozen=True, slots=True)
class WalkInDemandSpec:
    checked_in_at: datetime
    estimated_duration_minutes: int
    queue_position: int
    staff_id: uuid.UUID | None
    resource_id: uuid.UUID | None


@dataclass(frozen=True, slots=True)
class AvailabilityInput:
    branch_id: uuid.UUID
    online_booking_paused: bool
    branch_window_utc: TimeInterval | None
    requested_service_ids: list[uuid.UUID]
    services_by_id: dict[uuid.UUID, ServiceSpec]
    staff_list: list[StaffSpec]
    staff_shifts: list[ShiftWindowSpec]
    branch_blocks: list[TimeInterval]
    staff_blocks: dict[uuid.UUID, list[TimeInterval]]
    staff_busy_allocations_or_holds: dict[uuid.UUID, list[TimeInterval]]
    active_resource_ids: list[uuid.UUID]
    resource_busy_intervals: dict[uuid.UUID, list[TimeInterval]]
    unassigned_walk_ins: list[TimeInterval] = field(default_factory=list)
    unassigned_staff_demand: list[TimeInterval] = field(default_factory=list)
    unassigned_chair_demand: list[TimeInterval] = field(default_factory=list)
    now_utc: datetime = field(default_factory=lambda: datetime.now(UTC))
    lead_time_minutes: int = 15
    slot_step_minutes: int = 15
    staff_filter_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class AvailableStaffOption:
    staff_id: uuid.UUID
    display_name: str
    is_verified_staff: bool
    duration_minutes: int
    end_at: datetime


@dataclass(frozen=True, slots=True)
class ComputedSlot:
    start_at: datetime
    end_at: datetime
    duration_minutes: int
    allocated_start_at: datetime
    allocated_end_at: datetime
    available_staff: list[AvailableStaffOption]
    available_chair_count: int


@dataclass(frozen=True, slots=True)
class AvailabilityResult:
    online_booking_paused: bool
    is_branch_closed: bool
    slots: list[ComputedSlot]


@dataclass(frozen=True, slots=True)
class NextSlotProbe:
    branch: Branch
    service_id: uuid.UUID
    service_spec: ServiceSpec


def _overlaps(a: TimeInterval, b: TimeInterval) -> bool:
    return a.start_utc < b.end_utc and b.start_utc < a.end_utc


def _overlaps_any(target: TimeInterval, intervals: list[TimeInterval]) -> bool:
    return any(_overlaps(target, item) for item in intervals)


def _count_overlaps(target: TimeInterval, intervals: list[TimeInterval]) -> int:
    return sum(1 for item in intervals if _overlaps(target, item))


def _contains(outer: TimeInterval, inner: TimeInterval) -> bool:
    return outer.start_utc <= inner.start_utc and inner.end_utc <= outer.end_utc


def _parse_hhmm(raw: object) -> time | None:
    if not isinstance(raw, str) or ":" not in raw:
        return None
    parts = raw.strip().split(":", maxsplit=1)
    try:
        return time(hour=int(parts[0]), minute=int(parts[1]))
    except ValueError:
        return None


def resolve_branch_operating_window_utc(
    operating_hours_json: dict[str, Any],
    target_date: date,
    tz_name: str = DEFAULT_TIMEZONE,
) -> TimeInterval | None:
    """Resolve branch operating hours for a local date into an explicit UTC window."""
    if not operating_hours_json:
        return None
    day_spec = operating_hours_json.get(_WEEKDAY_KEYS[target_date.weekday()])
    if not isinstance(day_spec, dict) or bool(day_spec.get("closed")):
        return None

    open_t = _parse_hhmm(day_spec.get("open"))
    close_t = _parse_hhmm(day_spec.get("close"))
    if open_t is None or close_t is None or close_t <= open_t:
        return None

    tz = ZoneInfo(tz_name)
    start_local = datetime.combine(target_date, open_t, tzinfo=tz)
    end_local = datetime.combine(target_date, close_t, tzinfo=tz)
    return TimeInterval(start_utc=start_local.astimezone(UTC), end_utc=end_local.astimezone(UTC))


def is_branch_open_now(
    operating_hours_json: dict[str, Any],
    now_utc: datetime | None = None,
    tz_name: str = DEFAULT_TIMEZONE,
) -> bool:
    """Check if branch operating hours cover the current instant in branch local timezone."""
    current = now_utc or datetime.now(UTC)
    local_today = current.astimezone(ZoneInfo(tz_name)).date()
    window = resolve_branch_operating_window_utc(operating_hours_json, local_today, tz_name)
    if window is None:
        return False
    return window.start_utc <= current < window.end_utc


def schedule_walk_in_demands(
    *,
    walk_ins: Sequence[WalkInDemandSpec],
    now_utc: datetime,
    accepting_staff_count: int,
    active_chair_count: int,
    staff_busy: dict[uuid.UUID, list[TimeInterval]],
    resource_busy: dict[uuid.UUID, list[TimeInterval]],
    unassigned_staff_demand: list[TimeInterval],
    unassigned_chair_demand: list[TimeInterval],
) -> None:
    """Serialize queued unallocated walk-ins across active shop lanes instead of stacking."""
    if not walk_ins:
        return

    lane_count = max(1, min(max(1, accepting_staff_count), max(1, active_chair_count)))
    lanes = [now_utc for _ in range(lane_count)]
    ordered = sorted(walk_ins, key=lambda wi: (wi.queue_position, wi.checked_in_at))

    for wi in ordered:
        duration = timedelta(minutes=max(1, wi.estimated_duration_minutes))
        if wi.staff_id is not None and wi.resource_id is not None:
            wi_start = max(wi.checked_in_at, now_utc)
            interval = TimeInterval(start_utc=wi_start, end_utc=wi_start + duration)
            staff_busy.setdefault(wi.staff_id, []).append(interval)
            resource_busy.setdefault(wi.resource_id, []).append(interval)
            continue

        earliest_idx = min(range(lane_count), key=lanes.__getitem__)
        wi_start = max(wi.checked_in_at, lanes[earliest_idx])
        wi_end = wi_start + duration
        lanes[earliest_idx] = wi_end
        interval = TimeInterval(start_utc=wi_start, end_utc=wi_end)

        if wi.staff_id is not None:
            staff_busy.setdefault(wi.staff_id, []).append(interval)
        else:
            unassigned_staff_demand.append(interval)

        if wi.resource_id is not None:
            resource_busy.setdefault(wi.resource_id, []).append(interval)
        else:
            unassigned_chair_demand.append(interval)


def compute_available_slots(inp: AvailabilityInput) -> AvailabilityResult:
    """Compute genuinely available bookable slots respecting shifts, blocks, chairs, and holds."""
    if inp.online_booking_paused:
        return AvailabilityResult(online_booking_paused=True, is_branch_closed=False, slots=[])
    if inp.branch_window_utc is None:
        return AvailabilityResult(online_booking_paused=False, is_branch_closed=True, slots=[])
    if not inp.requested_service_ids or not inp.active_resource_ids:
        return AvailabilityResult(online_booking_paused=False, is_branch_closed=False, slots=[])

    accepting_staff = [st for st in inp.staff_list if st.is_active and st.is_accepting_bookings]
    qualified_staff = [
        st
        for st in accepting_staff
        if (inp.staff_filter_id is None or st.staff_id == inp.staff_filter_id)
        and all(sid in st.qualified_service_durations for sid in inp.requested_service_ids)
    ]
    if not qualified_staff:
        return AvailabilityResult(online_booking_paused=False, is_branch_closed=False, slots=[])

    first_svc = inp.services_by_id[inp.requested_service_ids[0]]
    last_svc = inp.services_by_id[inp.requested_service_ids[-1]]
    buf_before = timedelta(minutes=first_svc.buffer_before_minutes)
    buf_after = timedelta(minutes=last_svc.buffer_after_minutes)

    shifts_by_staff: dict[uuid.UUID, list[TimeInterval]] = {}
    for shift in inp.staff_shifts:
        shifts_by_staff.setdefault(shift.staff_id, []).append(
            TimeInterval(start_utc=shift.start_utc, end_utc=shift.end_utc)
        )

    all_chair_demand = [*inp.unassigned_chair_demand, *inp.unassigned_walk_ins]
    all_staff_demand = [*inp.unassigned_staff_demand, *inp.unassigned_walk_ins]

    earliest_start = inp.now_utc + timedelta(minutes=inp.lead_time_minutes)
    step = timedelta(minutes=max(5, inp.slot_step_minutes))
    cursor = inp.branch_window_utc.start_utc
    slots: list[ComputedSlot] = []

    while cursor < inp.branch_window_utc.end_utc:
        if cursor >= earliest_start:
            matching_staff: list[AvailableStaffOption] = []
            representative_duration: int | None = None
            representative_chairs = 0

            for staff in qualified_staff:
                svc_minutes = sum(
                    staff.qualified_service_durations[sid] for sid in inp.requested_service_ids
                )
                service_end = cursor + timedelta(minutes=svc_minutes)
                service_window = TimeInterval(start_utc=cursor, end_utc=service_end)

                if not _contains(inp.branch_window_utc, service_window):
                    continue

                staff_shifts = shifts_by_staff.get(staff.staff_id, [])
                if not any(_contains(sh, service_window) for sh in staff_shifts):
                    continue

                alloc_window = TimeInterval(
                    start_utc=cursor - buf_before,
                    end_utc=service_end + buf_after,
                )
                if _overlaps_any(alloc_window, inp.branch_blocks):
                    continue
                if _overlaps_any(alloc_window, inp.staff_blocks.get(staff.staff_id, [])):
                    continue
                if _overlaps_any(
                    alloc_window, inp.staff_busy_allocations_or_holds.get(staff.staff_id, [])
                ):
                    continue

                # Ensure unassigned walk-ins do not leave 0 actual idle barbers at this branch.
                idle_barbers_at_branch = sum(
                    1
                    for br_staff in accepting_staff
                    if any(
                        _contains(sh, service_window)
                        for sh in shifts_by_staff.get(br_staff.staff_id, [])
                    )
                    and not _overlaps_any(alloc_window, inp.staff_blocks.get(br_staff.staff_id, []))
                    and not _overlaps_any(
                        alloc_window,
                        inp.staff_busy_allocations_or_holds.get(br_staff.staff_id, []),
                    )
                )
                unassigned_staff_overlap = _count_overlaps(alloc_window, all_staff_demand)
                if idle_barbers_at_branch - unassigned_staff_overlap <= 0:
                    continue

                free_chairs = sum(
                    1
                    for rid in inp.active_resource_ids
                    if not _overlaps_any(alloc_window, inp.resource_busy_intervals.get(rid, []))
                )
                unassigned_chair_overlap = _count_overlaps(alloc_window, all_chair_demand)
                effective_chairs = max(0, free_chairs - unassigned_chair_overlap)
                if effective_chairs <= 0:
                    continue

                matching_staff.append(
                    AvailableStaffOption(
                        staff_id=staff.staff_id,
                        display_name=staff.display_name,
                        is_verified_staff=staff.is_verified_staff,
                        duration_minutes=svc_minutes,
                        end_at=service_end,
                    )
                )
                if representative_duration is None:
                    representative_duration = svc_minutes
                representative_chairs = max(representative_chairs, effective_chairs)

            if matching_staff and representative_duration is not None:
                rep_end = cursor + timedelta(minutes=representative_duration)
                slots.append(
                    ComputedSlot(
                        start_at=cursor,
                        end_at=rep_end,
                        duration_minutes=representative_duration,
                        allocated_start_at=cursor - buf_before,
                        allocated_end_at=rep_end + buf_after,
                        available_staff=matching_staff,
                        available_chair_count=representative_chairs,
                    )
                )

        cursor += step

    return AvailabilityResult(
        online_booking_paused=False,
        is_branch_closed=False,
        slots=slots,
    )


def _range_to_interval(rng: Any) -> TimeInterval | None:
    if rng is None or getattr(rng, "lower", None) is None or getattr(rng, "upper", None) is None:
        return None
    lower = rng.lower
    upper = rng.upper
    if isinstance(lower, datetime) and isinstance(upper, datetime) and upper > lower:
        start = lower if lower.tzinfo else lower.replace(tzinfo=UTC)
        end = upper if upper.tzinfo else upper.replace(tzinfo=UTC)
        return TimeInterval(start_utc=start.astimezone(UTC), end_utc=end.astimezone(UTC))
    return None


async def _load_branches_schedule_data(
    session: AsyncSession,
    *,
    branches: Sequence[Branch],
    target_date: date,
    services_by_branch: dict[uuid.UUID, dict[uuid.UUID, ServiceSpec]],
    now_utc: datetime,
) -> dict[uuid.UUID, AvailabilityResult]:
    """Batch-load schedule inputs (staff, shifts, blocks, holds, chairs, walk-ins)."""
    branch_ids = [b.id for b in branches]
    if not branch_ids:
        return {}

    windows_by_branch: dict[uuid.UUID, TimeInterval] = {}
    results: dict[uuid.UUID, AvailabilityResult] = {}

    for b in branches:
        if b.online_booking_paused:
            results[b.id] = AvailabilityResult(
                online_booking_paused=True, is_branch_closed=False, slots=[]
            )
            continue
        win = resolve_branch_operating_window_utc(b.operating_hours_json, target_date)
        if win is None:
            results[b.id] = AvailabilityResult(
                online_booking_paused=False, is_branch_closed=True, slots=[]
            )
            continue
        windows_by_branch[b.id] = win

    active_branch_ids = list(windows_by_branch.keys())
    if not active_branch_ids:
        return results

    min_start = min(w.start_utc for w in windows_by_branch.values()) - timedelta(hours=1)
    max_end = max(w.end_utc for w in windows_by_branch.values()) + timedelta(hours=1)
    query_range = Range(min_start, max_end, bounds="[)")

    staff_rows = list(
        await session.scalars(
            select(Staff).where(Staff.branch_id.in_(active_branch_ids), Staff.status == "ACTIVE")
        )
    )
    staff_by_branch: dict[uuid.UUID, list[Staff]] = {}
    all_staff_ids: list[uuid.UUID] = []
    for st in staff_rows:
        staff_by_branch.setdefault(st.branch_id, []).append(st)
        all_staff_ids.append(st.id)

    all_requested_svc_ids = {
        sid for svc_map in services_by_branch.values() for sid in svc_map.keys()
    }
    staff_service_rows = (
        list(
            await session.scalars(
                select(StaffService).where(
                    StaffService.staff_id.in_(all_staff_ids),
                    StaffService.is_active.is_(True),
                    StaffService.branch_service_id.in_(all_requested_svc_ids),
                )
            )
        )
        if all_staff_ids and all_requested_svc_ids
        else []
    )

    staff_branch_lookup = {st.id: st.branch_id for st in staff_rows}
    qual_by_staff: dict[uuid.UUID, dict[uuid.UUID, int]] = {}
    for ss in staff_service_rows:
        b_id = staff_branch_lookup.get(ss.staff_id)
        if b_id is None:
            continue
        svc_spec = services_by_branch.get(b_id, {}).get(ss.branch_service_id)
        if svc_spec is None:
            continue
        dur = (
            ss.custom_duration_minutes
            if ss.custom_duration_minutes is not None
            else svc_spec.duration_minutes
        )
        qual_by_staff.setdefault(ss.staff_id, {})[ss.branch_service_id] = dur

    shift_rows = (
        list(
            await session.scalars(
                select(StaffShift).where(
                    StaffShift.branch_id.in_(active_branch_ids),
                    StaffShift.weekday == target_date.weekday(),
                    StaffShift.is_active.is_(True),
                )
            )
        )
        if all_staff_ids
        else []
    )
    shifts_by_branch: dict[uuid.UUID, list[ShiftWindowSpec]] = {}
    for sh in shift_rows:
        tz = ZoneInfo(sh.timezone or DEFAULT_TIMEZONE)
        sh_start = datetime.combine(target_date, sh.start_time_local, tzinfo=tz).astimezone(UTC)
        sh_end = datetime.combine(target_date, sh.end_time_local, tzinfo=tz).astimezone(UTC)
        if sh_end > sh_start:
            shifts_by_branch.setdefault(sh.branch_id, []).append(
                ShiftWindowSpec(staff_id=sh.staff_id, start_utc=sh_start, end_utc=sh_end)
            )

    resource_rows = (
        await session.execute(
            select(Resource.id, Resource.branch_id).where(
                Resource.branch_id.in_(active_branch_ids), Resource.is_active.is_(True)
            )
        )
    ).all()
    resources_by_branch: dict[uuid.UUID, list[uuid.UUID]] = {}
    for r_id, b_id in resource_rows:
        resources_by_branch.setdefault(b_id, []).append(r_id)

    block_rows = list(
        await session.scalars(
            select(ScheduleBlock).where(
                ScheduleBlock.branch_id.in_(active_branch_ids),
                ScheduleBlock.blocked_range.op("&&")(query_range),
            )
        )
    )
    branch_blocks_map: dict[uuid.UUID, list[TimeInterval]] = {}
    staff_blocks_map: dict[uuid.UUID, dict[uuid.UUID, list[TimeInterval]]] = {}
    for blk in block_rows:
        interval = _range_to_interval(blk.blocked_range)
        if interval is None:
            continue
        if blk.staff_id is None:
            branch_blocks_map.setdefault(blk.branch_id, []).append(interval)
        else:
            staff_blocks_map.setdefault(blk.branch_id, {}).setdefault(blk.staff_id, []).append(
                interval
            )

    alloc_rows = list(
        await session.scalars(
            select(BookingAllocation).where(
                BookingAllocation.branch_id.in_(active_branch_ids),
                BookingAllocation.is_active.is_(True),
                BookingAllocation.allocated_range.op("&&")(query_range),
            )
        )
    )
    hold_rows = list(
        await session.scalars(
            select(SlotHold).where(
                SlotHold.branch_id.in_(active_branch_ids),
                SlotHold.status == "ACTIVE",
                SlotHold.expires_at > now_utc,
                SlotHold.hold_range.op("&&")(query_range),
            )
        )
    )
    walk_in_rows = list(
        await session.scalars(
            select(WalkIn).where(
                WalkIn.branch_id.in_(active_branch_ids),
                WalkIn.status.in_(("WAITING", "SEATED", "IN_SERVICE")),
                and_(
                    WalkIn.checked_in_at >= min_start - timedelta(hours=12),
                    WalkIn.checked_in_at <= max_end,
                ),
            )
        )
    )

    staff_busy_map: dict[uuid.UUID, dict[uuid.UUID, list[TimeInterval]]] = {}
    resource_busy_map: dict[uuid.UUID, dict[uuid.UUID, list[TimeInterval]]] = {}
    unassigned_staff_map: dict[uuid.UUID, list[TimeInterval]] = {}
    unassigned_chair_map: dict[uuid.UUID, list[TimeInterval]] = {}
    allocated_walk_in_ids: set[uuid.UUID] = set()

    for alloc in alloc_rows:
        if alloc.walk_in_id is not None:
            allocated_walk_in_ids.add(alloc.walk_in_id)
        interval = _range_to_interval(alloc.allocated_range)
        if interval is None:
            continue
        staff_busy_map.setdefault(alloc.branch_id, {}).setdefault(alloc.staff_id, []).append(
            interval
        )
        if alloc.resource_id is not None:
            resource_busy_map.setdefault(alloc.branch_id, {}).setdefault(
                alloc.resource_id, []
            ).append(interval)
        else:
            unassigned_chair_map.setdefault(alloc.branch_id, []).append(interval)

    for hold in hold_rows:
        interval = _range_to_interval(hold.hold_range)
        if interval is None:
            continue
        staff_busy_map.setdefault(hold.branch_id, {}).setdefault(hold.staff_id, []).append(interval)
        if hold.resource_id is not None:
            resource_busy_map.setdefault(hold.branch_id, {}).setdefault(
                hold.resource_id, []
            ).append(interval)
        else:
            unassigned_chair_map.setdefault(hold.branch_id, []).append(interval)

    walk_ins_by_branch: dict[uuid.UUID, list[WalkInDemandSpec]] = {}
    for wi in walk_in_rows:
        if wi.id in allocated_walk_in_ids:
            continue
        walk_ins_by_branch.setdefault(wi.branch_id, []).append(
            WalkInDemandSpec(
                checked_in_at=wi.checked_in_at,
                estimated_duration_minutes=wi.estimated_duration_minutes,
                queue_position=wi.queue_position,
                staff_id=wi.staff_id,
                resource_id=wi.resource_id,
            )
        )

    for b in branches:
        if b.id in results:
            continue
        b_staff = [
            StaffSpec(
                staff_id=s.id,
                display_name=s.display_name,
                is_verified_staff=s.is_verified_staff,
                is_accepting_bookings=s.is_accepting_bookings,
                is_active=s.status == "ACTIVE",
                qualified_service_durations=qual_by_staff.get(s.id, {}),
            )
            for s in staff_by_branch.get(b.id, [])
        ]
        b_resources = resources_by_branch.get(b.id, [])
        b_staff_busy = staff_busy_map.setdefault(b.id, {})
        b_resource_busy = resource_busy_map.setdefault(b.id, {})
        b_unassigned_staff = unassigned_staff_map.setdefault(b.id, [])
        b_unassigned_chair = unassigned_chair_map.setdefault(b.id, [])

        accepting_count = sum(1 for st in b_staff if st.is_active and st.is_accepting_bookings)
        schedule_walk_in_demands(
            walk_ins=walk_ins_by_branch.get(b.id, []),
            now_utc=now_utc,
            accepting_staff_count=accepting_count,
            active_chair_count=len(b_resources),
            staff_busy=b_staff_busy,
            resource_busy=b_resource_busy,
            unassigned_staff_demand=b_unassigned_staff,
            unassigned_chair_demand=b_unassigned_chair,
        )

        svc_map = services_by_branch.get(b.id, {})
        results[b.id] = compute_available_slots(
            AvailabilityInput(
                branch_id=b.id,
                online_booking_paused=b.online_booking_paused,
                branch_window_utc=windows_by_branch[b.id],
                requested_service_ids=list(svc_map.keys()),
                services_by_id=svc_map,
                staff_list=b_staff,
                staff_shifts=shifts_by_branch.get(b.id, []),
                branch_blocks=branch_blocks_map.get(b.id, []),
                staff_blocks=staff_blocks_map.get(b.id, {}),
                staff_busy_allocations_or_holds=b_staff_busy,
                active_resource_ids=b_resources,
                resource_busy_intervals=b_resource_busy,
                unassigned_staff_demand=b_unassigned_staff,
                unassigned_chair_demand=b_unassigned_chair,
                now_utc=now_utc,
            )
        )

    return results


async def load_branches_next_available_slots(
    session: AsyncSession,
    *,
    probes: Sequence[NextSlotProbe],
    now_utc: datetime | None = None,
) -> dict[uuid.UUID, datetime | None]:
    """Compute next available slot across multiple branches in batched DB round-trips."""
    if not probes:
        return {}
    current_utc = now_utc or datetime.now(UTC)
    today_ist = current_utc.astimezone(ZoneInfo(DEFAULT_TIMEZONE)).date()
    tomorrow_ist = today_ist + timedelta(days=1)

    next_slot_by_branch: dict[uuid.UUID, datetime | None] = {p.branch.id: None for p in probes}
    remaining = list(probes)

    for probe_date in (today_ist, tomorrow_ist):
        if not remaining:
            break
        branches = [p.branch for p in remaining]
        svc_maps = {p.branch.id: {p.service_id: p.service_spec} for p in remaining}
        avail_map = await _load_branches_schedule_data(
            session,
            branches=branches,
            target_date=probe_date,
            services_by_branch=svc_maps,
            now_utc=current_utc,
        )
        still_remaining: list[NextSlotProbe] = []
        for p in remaining:
            avail = avail_map.get(p.branch.id)
            if avail and avail.slots:
                next_slot_by_branch[p.branch.id] = avail.slots[0].start_at
            else:
                still_remaining.append(p)
        remaining = still_remaining

    return next_slot_by_branch


async def load_branch_availability_from_db(
    session: AsyncSession,
    *,
    branch_id: uuid.UUID,
    service_ids: list[uuid.UUID],
    target_date: date,
    staff_id: uuid.UUID | None = None,
    now_utc: datetime | None = None,
) -> tuple[Branch, AvailabilityResult]:
    """Load real branch schedule/capacity rows from PostgreSQL and compute live slots."""
    branch = await session.scalar(
        select(Branch)
        .join(Salon, Salon.id == Branch.salon_id)
        .where(
            Branch.id == branch_id,
            Branch.status == "ACTIVE",
            Salon.status == "ACTIVE",
            Branch.verification_status != BranchVerificationStatus.SUSPENDED.value,
        )
    )
    if branch is None:
        raise ChairAPIError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="BRANCH_NOT_FOUND",
            message="Branch does not exist or is not active.",
        )

    current_utc = now_utc or datetime.now(UTC)
    unique_service_ids = list(dict.fromkeys(service_ids))
    branch_service_rows = list(
        await session.scalars(
            select(BranchService)
            .join(Service, Service.id == BranchService.service_id)
            .where(
                BranchService.branch_id == branch.id,
                BranchService.is_active.is_(True),
                Service.is_active.is_(True),
                BranchService.id.in_(unique_service_ids),
            )
        )
    )
    services_by_id = {
        row.id: ServiceSpec(
            branch_service_id=row.id,
            duration_minutes=row.duration_minutes,
            buffer_before_minutes=row.buffer_before_minutes,
            buffer_after_minutes=row.buffer_after_minutes,
        )
        for row in branch_service_rows
    }
    if len(services_by_id) != len(unique_service_ids):
        raise ChairAPIError(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="INVALID_SERVICE_SELECTION",
            message="One or more selected services are unavailable at this branch.",
        )

    if staff_id is None:
        # Preserve exact requested service order in dict insertion order
        ordered_services = {sid: services_by_id[sid] for sid in unique_service_ids}
        result_map = await _load_branches_schedule_data(
            session,
            branches=[branch],
            target_date=target_date,
            services_by_branch={branch.id: ordered_services},
            now_utc=current_utc,
        )
        return branch, result_map[branch.id]

    if branch.online_booking_paused:
        return branch, AvailabilityResult(
            online_booking_paused=True, is_branch_closed=False, slots=[]
        )

    branch_window = resolve_branch_operating_window_utc(branch.operating_hours_json, target_date)
    if branch_window is None:
        return branch, AvailabilityResult(
            online_booking_paused=False, is_branch_closed=True, slots=[]
        )

    # Filter staff cleanly when specific barber is chosen
    ordered_services = {sid: services_by_id[sid] for sid in unique_service_ids}
    staff_rows = list(
        await session.scalars(
            select(Staff).where(Staff.branch_id == branch.id, Staff.status == "ACTIVE")
        )
    )
    staff_ids = [s.id for s in staff_rows]
    ss_rows = (
        list(
            await session.scalars(
                select(StaffService).where(
                    StaffService.staff_id.in_(staff_ids),
                    StaffService.is_active.is_(True),
                    StaffService.branch_service_id.in_(unique_service_ids),
                )
            )
        )
        if staff_ids
        else []
    )
    qual_by_staff: dict[uuid.UUID, dict[uuid.UUID, int]] = {}
    for ss in ss_rows:
        base_dur = ordered_services[ss.branch_service_id].duration_minutes
        qual_by_staff.setdefault(ss.staff_id, {})[ss.branch_service_id] = (
            ss.custom_duration_minutes if ss.custom_duration_minutes is not None else base_dur
        )
    staff_specs = [
        StaffSpec(
            staff_id=s.id,
            display_name=s.display_name,
            is_verified_staff=s.is_verified_staff,
            is_accepting_bookings=s.is_accepting_bookings,
            is_active=s.status == "ACTIVE",
            qualified_service_durations=qual_by_staff.get(s.id, {}),
        )
        for s in staff_rows
    ]
    shift_rows = (
        list(
            await session.scalars(
                select(StaffShift).where(
                    StaffShift.branch_id == branch.id,
                    StaffShift.weekday == target_date.weekday(),
                    StaffShift.is_active.is_(True),
                )
            )
        )
        if staff_ids
        else []
    )
    shift_specs = []
    for sh in shift_rows:
        tz = ZoneInfo(sh.timezone or DEFAULT_TIMEZONE)
        sh_start = datetime.combine(target_date, sh.start_time_local, tzinfo=tz).astimezone(UTC)
        sh_end = datetime.combine(target_date, sh.end_time_local, tzinfo=tz).astimezone(UTC)
        if sh_end > sh_start:
            shift_specs.append(
                ShiftWindowSpec(staff_id=sh.staff_id, start_utc=sh_start, end_utc=sh_end)
            )

    resource_ids = list(
        await session.scalars(
            select(Resource.id).where(Resource.branch_id == branch.id, Resource.is_active.is_(True))
        )
    )
    query_range = Range(
        branch_window.start_utc - timedelta(hours=1),
        branch_window.end_utc + timedelta(hours=1),
        bounds="[)",
    )
    block_rows = list(
        await session.scalars(
            select(ScheduleBlock).where(
                ScheduleBlock.branch_id == branch.id,
                ScheduleBlock.blocked_range.op("&&")(query_range),
            )
        )
    )
    branch_blocks: list[TimeInterval] = []
    staff_blocks: dict[uuid.UUID, list[TimeInterval]] = {}
    for blk in block_rows:
        interval = _range_to_interval(blk.blocked_range)
        if interval is None:
            continue
        if blk.staff_id is None:
            branch_blocks.append(interval)
        else:
            staff_blocks.setdefault(blk.staff_id, []).append(interval)

    alloc_rows = list(
        await session.scalars(
            select(BookingAllocation).where(
                BookingAllocation.branch_id == branch.id,
                BookingAllocation.is_active.is_(True),
                BookingAllocation.allocated_range.op("&&")(query_range),
            )
        )
    )
    hold_rows = list(
        await session.scalars(
            select(SlotHold).where(
                SlotHold.branch_id == branch.id,
                SlotHold.status == "ACTIVE",
                SlotHold.expires_at > current_utc,
                SlotHold.hold_range.op("&&")(query_range),
            )
        )
    )
    walk_in_rows = list(
        await session.scalars(
            select(WalkIn).where(
                WalkIn.branch_id == branch.id,
                WalkIn.status.in_(("WAITING", "SEATED", "IN_SERVICE")),
                and_(
                    WalkIn.checked_in_at >= branch_window.start_utc - timedelta(hours=12),
                    WalkIn.checked_in_at <= branch_window.end_utc + timedelta(hours=1),
                ),
            )
        )
    )

    staff_busy: dict[uuid.UUID, list[TimeInterval]] = {}
    resource_busy: dict[uuid.UUID, list[TimeInterval]] = {}
    unassigned_staff: list[TimeInterval] = []
    unassigned_chair: list[TimeInterval] = []
    allocated_walk_in_ids: set[uuid.UUID] = set()

    for alloc in alloc_rows:
        if alloc.walk_in_id is not None:
            allocated_walk_in_ids.add(alloc.walk_in_id)
        interval = _range_to_interval(alloc.allocated_range)
        if interval is None:
            continue
        staff_busy.setdefault(alloc.staff_id, []).append(interval)
        if alloc.resource_id is not None:
            resource_busy.setdefault(alloc.resource_id, []).append(interval)
        else:
            unassigned_chair.append(interval)

    for hold in hold_rows:
        interval = _range_to_interval(hold.hold_range)
        if interval is None:
            continue
        staff_busy.setdefault(hold.staff_id, []).append(interval)
        if hold.resource_id is not None:
            resource_busy.setdefault(hold.resource_id, []).append(interval)
        else:
            unassigned_chair.append(interval)

    unallocated_wi = [
        WalkInDemandSpec(
            checked_in_at=wi.checked_in_at,
            estimated_duration_minutes=wi.estimated_duration_minutes,
            queue_position=wi.queue_position,
            staff_id=wi.staff_id,
            resource_id=wi.resource_id,
        )
        for wi in walk_in_rows
        if wi.id not in allocated_walk_in_ids
    ]
    accepting_count = sum(1 for st in staff_specs if st.is_active and st.is_accepting_bookings)
    schedule_walk_in_demands(
        walk_ins=unallocated_wi,
        now_utc=current_utc,
        accepting_staff_count=accepting_count,
        active_chair_count=len(resource_ids),
        staff_busy=staff_busy,
        resource_busy=resource_busy,
        unassigned_staff_demand=unassigned_staff,
        unassigned_chair_demand=unassigned_chair,
    )

    return branch, compute_available_slots(
        AvailabilityInput(
            branch_id=branch.id,
            online_booking_paused=branch.online_booking_paused,
            branch_window_utc=branch_window,
            requested_service_ids=unique_service_ids,
            services_by_id=ordered_services,
            staff_list=staff_specs,
            staff_shifts=shift_specs,
            branch_blocks=branch_blocks,
            staff_blocks=staff_blocks,
            staff_busy_allocations_or_holds=staff_busy,
            active_resource_ids=resource_ids,
            resource_busy_intervals=resource_busy,
            unassigned_staff_demand=unassigned_staff,
            unassigned_chair_demand=unassigned_chair,
            now_utc=current_utc,
            staff_filter_id=staff_id,
        )
    )
