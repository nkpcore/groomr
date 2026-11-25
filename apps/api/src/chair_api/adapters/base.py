"""External integration adapter interfaces and safe development/test implementations."""

import hashlib
import hmac
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import urlencode


class OTPProvider(Protocol):
    async def send_otp(self, phone_e164: str) -> str: ...
    async def verify_otp(self, phone_e164: str, code: str) -> bool: ...


@dataclass(frozen=True)
class PaymentOrderResult:
    provider: str
    provider_order_id: str
    amount_paise: int
    currency: str


class PaymentProvider(Protocol):
    async def create_order(
        self, *, booking_id: str, amount_paise: int, currency: str = "INR"
    ) -> PaymentOrderResult: ...

    def verify_webhook_signature(
        self, *, payload_bytes: bytes, signature: str, secret: str
    ) -> bool: ...


class StorageProvider(Protocol):
    def validate_upload(
        self, *, content: bytes, declared_mime: str, max_bytes: int
    ) -> str: ...

    def store_object(self, *, object_key: str, content: bytes) -> None: ...

    def delete_object(self, *, object_key: str) -> None: ...

    def read_object(self, *, object_key: str) -> bytes: ...

    def verify_signed_url(self, *, object_key: str, expires: int, signature: str) -> bool: ...

    def create_signed_url(self, *, object_key: str, ttl_seconds: int = 300) -> str: ...


class MapsProvider(Protocol):
    async def reverse_geocode(self, *, lat: float, lng: float) -> str: ...


class NotificationProvider(Protocol):
    async def dispatch(self, *, user_id: str, channel: str, template_key: str) -> None: ...


class MockOTPProvider:
    """Development/test OTP adapter. Blocked in production by Settings validator."""

    DEV_FIXED_CODE = "123456"

    async def send_otp(self, phone_e164: str) -> str:
        return f"mock-otp-challenge:{phone_e164}"

    async def verify_otp(self, phone_e164: str, code: str) -> bool:
        return bool(phone_e164) and hmac.compare_digest(code, self.DEV_FIXED_CODE)


class TestModePaymentAdapter:
    """Test-mode payment adapter and Razorpay-compatible HMAC-SHA256 signature verification."""

    async def create_order(
        self, *, booking_id: str, amount_paise: int, currency: str = "INR"
    ) -> PaymentOrderResult:
        if amount_paise <= 0:
            raise ValueError("amount_paise must be positive.")
        short_booking = booking_id.replace("-", "")[:12]
        return PaymentOrderResult(
            provider="TEST_MODE",
            provider_order_id=f"test_order_{short_booking}_{uuid.uuid4().hex[:8]}",
            amount_paise=amount_paise,
            currency=currency,
        )

    def verify_webhook_signature(
        self, *, payload_bytes: bytes, signature: str, secret: str
    ) -> bool:
        if not secret or not signature:
            return False
        expected = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)


ALLOWED_IMAGE_PDF_SIGNATURES: dict[str, tuple[bytes, ...]] = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/webp": (b"RIFF",),
    "application/pdf": (b"%PDF-",),
}


class LocalSignedStorageAdapter:
    """Private local storage adapter validating magic bytes, size, and HMAC signed access."""

    def __init__(self, *, root_dir: str, signing_secret: str) -> None:
        self.root_dir = Path(root_dir)
        self.signing_secret = signing_secret

    def validate_upload(self, *, content: bytes, declared_mime: str, max_bytes: int) -> str:
        if not content:
            raise ValueError("Uploaded file is empty.")
        if len(content) > max_bytes:
            raise ValueError(f"File exceeds maximum size of {max_bytes} bytes.")
        prefixes = ALLOWED_IMAGE_PDF_SIGNATURES.get(declared_mime)
        if not prefixes:
            raise ValueError(f"Unsupported MIME type: {declared_mime}")
        if not any(content.startswith(prefix) for prefix in prefixes):
            raise ValueError("File magic bytes do not match declared MIME type.")
        if declared_mime == "image/webp" and content[8:12] != b"WEBP":
            raise ValueError("Invalid WebP header.")
        return hashlib.sha256(content).hexdigest()

    def _resolve_safe_path(self, object_key: str) -> Path:
        root_resolved = self.root_dir.resolve()
        candidate = (root_resolved / object_key).resolve()
        if not candidate.is_relative_to(root_resolved):
            raise ValueError("Invalid storage object key path.")
        return candidate

    def store_object(self, *, object_key: str, content: bytes) -> None:
        target = self._resolve_safe_path(object_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    def delete_object(self, *, object_key: str) -> None:
        target = self._resolve_safe_path(object_key)
        target.unlink(missing_ok=True)

    def read_object(self, *, object_key: str) -> bytes:
        target = self._resolve_safe_path(object_key)
        if not target.is_file():
            raise FileNotFoundError(f"Object not found: {object_key}")
        return target.read_bytes()

    def verify_signed_url(self, *, object_key: str, expires: int, signature: str) -> bool:
        if not signature or expires < int(time.time()):
            return False
        msg = f"{object_key}:{expires}".encode()
        expected = hmac.new(self.signing_secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    def create_signed_url(self, *, object_key: str, ttl_seconds: int = 300) -> str:
        expires = int(time.time()) + ttl_seconds
        msg = f"{object_key}:{expires}".encode()
        sig = hmac.new(self.signing_secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()
        query = urlencode({"key": object_key, "expires": expires, "sig": sig})
        return f"/api/v1/assets/signed?{query}"


class LocalStubMapsAdapter:
    async def reverse_geocode(self, *, lat: float, lng: float) -> str:
        return f"Lat {lat:.4f}, Lng {lng:.4f} (Demo Geocoder)"


class ConsoleOutboxNotificationAdapter:
    async def dispatch(self, *, user_id: str, channel: str, template_key: str) -> None:
        return None
