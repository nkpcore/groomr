import type {
  BookingDetailDto,
  BookingListResponseDto,
  CreateHoldRequestDto,
  CreateReviewRequestDto,
  HoldCreationResponseDto,
  HoldDetailResponseDto,
  PaymentOrderResponseDto,
} from "@chair/shared-types";
import { authorizedMobileRequest } from "./authApi";
import type { StoredMobileSession } from "./tokenStorage";

export function makeMobileIdempotencyKey(prefix: string): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return `${prefix}-${crypto.randomUUID()}`;
  }
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

export function createSlotHold(
  session: StoredMobileSession,
  payload: CreateHoldRequestDto,
  onSessionUpdate?: (next: StoredMobileSession | null) => void,
  idempotencyKey: string = makeMobileIdempotencyKey("hold")
): Promise<HoldCreationResponseDto> {
  return authorizedMobileRequest<HoldCreationResponseDto>(
    "/holds",
    session,
    {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: JSON.stringify(payload),
    },
    onSessionUpdate
  );
}

export function fetchHoldDetail(
  session: StoredMobileSession,
  holdId: string,
  onSessionUpdate?: (next: StoredMobileSession | null) => void
): Promise<HoldDetailResponseDto> {
  return authorizedMobileRequest<HoldDetailResponseDto>(
    `/holds/${encodeURIComponent(holdId)}`,
    session,
    {},
    onSessionUpdate
  );
}

export function releaseSlotHold(
  session: StoredMobileSession,
  holdId: string,
  onSessionUpdate?: (next: StoredMobileSession | null) => void
): Promise<{ status: string }> {
  return authorizedMobileRequest<{ status: string }>(
    `/holds/${encodeURIComponent(holdId)}`,
    session,
    { method: "DELETE" },
    onSessionUpdate
  );
}

export function confirmPayAtSalon(
  session: StoredMobileSession,
  bookingId: string,
  onSessionUpdate?: (next: StoredMobileSession | null) => void,
  idempotencyKey: string = makeMobileIdempotencyKey("confirm-pas")
): Promise<BookingDetailDto> {
  return authorizedMobileRequest<BookingDetailDto>(
    `/bookings/${encodeURIComponent(bookingId)}/confirm-pay-at-salon`,
    session,
    {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
    },
    onSessionUpdate
  );
}

export function createPaymentOrder(
  session: StoredMobileSession,
  bookingId: string,
  onSessionUpdate?: (next: StoredMobileSession | null) => void,
  idempotencyKey: string = makeMobileIdempotencyKey("order")
): Promise<PaymentOrderResponseDto> {
  return authorizedMobileRequest<PaymentOrderResponseDto>(
    `/bookings/${encodeURIComponent(bookingId)}/payment-order`,
    session,
    {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
    },
    onSessionUpdate
  );
}

export function captureTestModePayment(
  session: StoredMobileSession,
  bookingId: string,
  providerOrderId: string,
  onSessionUpdate?: (next: StoredMobileSession | null) => void,
  idempotencyKey: string = makeMobileIdempotencyKey("cap")
): Promise<BookingDetailDto> {
  return authorizedMobileRequest<BookingDetailDto>(
    `/bookings/${encodeURIComponent(bookingId)}/test-payment-capture`,
    session,
    {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: JSON.stringify({ provider_order_id: providerOrderId }),
    },
    onSessionUpdate
  );
}

export function fetchMyBookings(
  session: StoredMobileSession,
  onSessionUpdate?: (next: StoredMobileSession | null) => void
): Promise<BookingListResponseDto> {
  return authorizedMobileRequest<BookingListResponseDto>("/bookings", session, {}, onSessionUpdate);
}

export function fetchBookingDetail(
  session: StoredMobileSession,
  bookingId: string,
  onSessionUpdate?: (next: StoredMobileSession | null) => void
): Promise<BookingDetailDto> {
  return authorizedMobileRequest<BookingDetailDto>(
    `/bookings/${encodeURIComponent(bookingId)}`,
    session,
    {},
    onSessionUpdate
  );
}

export function cancelMyBooking(
  session: StoredMobileSession,
  bookingId: string,
  reason: string | null,
  onSessionUpdate?: (next: StoredMobileSession | null) => void,
  idempotencyKey: string = makeMobileIdempotencyKey("cancel")
): Promise<BookingDetailDto> {
  return authorizedMobileRequest<BookingDetailDto>(
    `/bookings/${encodeURIComponent(bookingId)}/cancel`,
    session,
    {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: JSON.stringify({ reason }),
    },
    onSessionUpdate
  );
}

export function submitBookingReview(
  session: StoredMobileSession,
  bookingId: string,
  payload: CreateReviewRequestDto,
  onSessionUpdate?: (next: StoredMobileSession | null) => void
): Promise<{ id: string; booking_id: string }> {
  return authorizedMobileRequest<{ id: string; booking_id: string }>(
    `/bookings/${encodeURIComponent(bookingId)}/review`,
    session,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
    onSessionUpdate
  );
}
