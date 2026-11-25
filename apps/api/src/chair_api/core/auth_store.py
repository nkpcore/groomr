"""Redis and in-memory state store using atomic operations for auth security."""

import json
import time
from dataclasses import asdict, dataclass
from typing import Literal, Protocol, cast

from fastapi import status
from redis.asyncio import Redis
from redis.exceptions import RedisError

from chair_api.core.errors import ChairAPIError

OTPClaimStatus = Literal["claimed", "missing", "locked"]
RefreshRotateStatus = Literal["rotated", "missing", "revoked", "reused"]

_RATE_LIMIT_LUA = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
  redis.call('EXPIRE', KEYS[1], tonumber(ARGV[1]))
end
local ttl = redis.call('TTL', KEYS[1])
if ttl < 0 then
  redis.call('EXPIRE', KEYS[1], tonumber(ARGV[1]))
  ttl = tonumber(ARGV[1])
end
return {current, ttl}
"""

_SAVE_ACTIVE_CHALLENGE_LUA = """
local prev_id = redis.call('GET', KEYS[1])
if prev_id and prev_id ~= ARGV[2] then
  redis.call('DEL', ARGV[4] .. prev_id)
end
redis.call('SET', KEYS[1], ARGV[2], 'EX', tonumber(ARGV[1]))
redis.call('SET', KEYS[2], ARGV[3], 'EX', tonumber(ARGV[1]))
return 1
"""

_CLAIM_OTP_ATTEMPT_LUA = """
local raw = redis.call('GET', KEYS[1])
if not raw then
  return {'missing', 0}
end
local rec = cjson.decode(raw)
if rec.phone_e164 ~= ARGV[1] then
  return {'missing', 0}
end
local max_attempts = tonumber(ARGV[2])
if rec.attempts >= max_attempts then
  redis.call('DEL', KEYS[1])
  return {'locked', rec.attempts}
end
rec.attempts = rec.attempts + 1
local ttl = redis.call('TTL', KEYS[1])
if ttl <= 0 then
  ttl = 60
end
redis.call('SET', KEYS[1], cjson.encode(rec), 'EX', ttl)
return {'claimed', rec.attempts}
"""

_ROTATE_REFRESH_LUA = """
local raw = redis.call('GET', KEYS[1])
if not raw then
  return 'missing'
end
local rec = cjson.decode(raw)
if rec.revoked then
  return 'revoked'
end
if rec.user_id ~= ARGV[1] then
  return 'missing'
end
local ttl = tonumber(ARGV[4])
if rec.active_jti_hash ~= ARGV[2] then
  rec.revoked = true
  redis.call('SET', KEYS[1], cjson.encode(rec), 'EX', ttl)
  return 'reused'
end
rec.active_jti_hash = ARGV[3]
redis.call('SET', KEYS[1], cjson.encode(rec), 'EX', ttl)
return 'rotated'
"""

_REVOKE_REFRESH_LUA = """
local raw = redis.call('GET', KEYS[1])
if not raw then
  return 0
end
local rec = cjson.decode(raw)
rec.revoked = true
redis.call('SET', KEYS[1], cjson.encode(rec), 'EX', tonumber(ARGV[1]))
return 1
"""


@dataclass(slots=True)
class OTPChallengeRecord:
    challenge_id: str
    phone_e164: str
    provider: str
    attempts: int
    created_at_iso: str


@dataclass(slots=True)
class RefreshFamilyRecord:
    family_id: str
    user_id: str
    active_jti_hash: str
    revoked: bool = False


class AuthStore(Protocol):
    async def check_and_increment_otp_rate_limit(
        self,
        *,
        phone_e164: str,
        ip_key: str,
        window_seconds: int,
        max_per_phone: int,
        max_per_ip: int,
    ) -> int | None: ...

    async def save_otp_challenge(
        self, challenge: OTPChallengeRecord, *, ttl_seconds: int
    ) -> None: ...

    async def claim_otp_attempt(
        self,
        *,
        challenge_id: str,
        expected_phone: str,
        max_attempts: int,
    ) -> tuple[OTPClaimStatus, int]: ...

    async def consume_otp_challenge(self, challenge_id: str) -> bool: ...

    async def is_phone_verify_locked(self, phone_e164: str, *, max_failures: int) -> int | None: ...

    async def record_otp_verify_failure(
        self,
        *,
        phone_e164: str,
        window_seconds: int,
        max_failures: int,
    ) -> int | None: ...

    async def clear_otp_verify_failures(self, phone_e164: str) -> None: ...

    async def save_refresh_family(
        self, family: RefreshFamilyRecord, *, ttl_seconds: int
    ) -> None: ...

    async def get_refresh_family(self, family_id: str) -> RefreshFamilyRecord | None: ...

    async def rotate_refresh_family(
        self,
        *,
        family_id: str,
        expected_user_id: str,
        expected_jti_hash: str,
        new_jti_hash: str,
        ttl_seconds: int,
    ) -> RefreshRotateStatus: ...

    async def revoke_refresh_family(self, family_id: str, *, ttl_seconds: int) -> None: ...


class RedisAuthStore:
    """Production/integration AuthStore backed by atomic Redis Lua scripts."""

    _CHALLENGE_PREFIX = "chair:auth:otp_challenge:"

    def __init__(self, redis_client: Redis) -> None:
        self._redis = redis_client

    @classmethod
    def _challenge_key(cls, challenge_id: str) -> str:
        return f"{cls._CHALLENGE_PREFIX}{challenge_id}"

    @staticmethod
    def _active_phone_challenge_key(phone_e164: str) -> str:
        return f"chair:auth:otp_active:{phone_e164}"

    @staticmethod
    def _phone_rl_key(phone_e164: str) -> str:
        return f"chair:auth:rl:phone:{phone_e164}"

    @staticmethod
    def _ip_rl_key(ip_key: str) -> str:
        return f"chair:auth:rl:ip:{ip_key}"

    @staticmethod
    def _verify_fail_key(phone_e164: str) -> str:
        return f"chair:auth:verify_fail:{phone_e164}"

    @staticmethod
    def _family_key(family_id: str) -> str:
        return f"chair:auth:rt_family:{family_id}"

    async def _incr_window(self, key: str, window_seconds: int) -> tuple[int, int]:
        try:
            raw = await self._redis.eval(_RATE_LIMIT_LUA, 1, key, str(window_seconds))
            count_val, ttl_val = cast(list[int], raw)
            return int(count_val), max(int(ttl_val), 1)
        except RedisError as exc:
            raise ChairAPIError(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                code="AUTH_STORE_UNAVAILABLE",
                message="Authentication rate-limit store is temporarily unavailable.",
            ) from exc

    async def check_and_increment_otp_rate_limit(
        self,
        *,
        phone_e164: str,
        ip_key: str,
        window_seconds: int,
        max_per_phone: int,
        max_per_ip: int,
    ) -> int | None:
        # Check/increment caller IP bucket BEFORE incrementing victim phone bucket.
        ip_count, ip_ttl = await self._incr_window(self._ip_rl_key(ip_key), window_seconds)
        if ip_count > max_per_ip:
            return ip_ttl

        phone_count, phone_ttl = await self._incr_window(
            self._phone_rl_key(phone_e164), window_seconds
        )
        if phone_count > max_per_phone:
            return phone_ttl
        return None

    async def save_otp_challenge(
        self, challenge: OTPChallengeRecord, *, ttl_seconds: int
    ) -> None:
        try:
            await self._redis.eval(
                _SAVE_ACTIVE_CHALLENGE_LUA,
                2,
                self._active_phone_challenge_key(challenge.phone_e164),
                self._challenge_key(challenge.challenge_id),
                str(ttl_seconds),
                challenge.challenge_id,
                json.dumps(asdict(challenge)),
                self._CHALLENGE_PREFIX,
            )
        except RedisError as exc:
            raise ChairAPIError(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                code="AUTH_STORE_UNAVAILABLE",
                message="Authentication session store is temporarily unavailable.",
            ) from exc

    async def claim_otp_attempt(
        self,
        *,
        challenge_id: str,
        expected_phone: str,
        max_attempts: int,
    ) -> tuple[OTPClaimStatus, int]:
        try:
            raw = await self._redis.eval(
                _CLAIM_OTP_ATTEMPT_LUA,
                1,
                self._challenge_key(challenge_id),
                expected_phone,
                str(max_attempts),
            )
            state_raw, attempts_raw = cast(list[object], raw)
            state = cast(OTPClaimStatus, str(state_raw))
            return state, int(str(attempts_raw))
        except RedisError as exc:
            raise ChairAPIError(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                code="AUTH_STORE_UNAVAILABLE",
                message="Authentication session store is temporarily unavailable.",
            ) from exc

    async def consume_otp_challenge(self, challenge_id: str) -> bool:
        try:
            deleted = await self._redis.delete(self._challenge_key(challenge_id))
            return int(deleted) > 0
        except RedisError as exc:
            raise ChairAPIError(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                code="AUTH_STORE_UNAVAILABLE",
                message="Authentication session store is temporarily unavailable.",
            ) from exc

    async def is_phone_verify_locked(self, phone_e164: str, *, max_failures: int) -> int | None:
        key = self._verify_fail_key(phone_e164)
        try:
            raw = await self._redis.get(key)
            if raw is None or int(raw) < max_failures:
                return None
            ttl = await self._redis.ttl(key)
            return max(1, int(ttl)) if ttl and int(ttl) > 0 else 60
        except RedisError as exc:
            raise ChairAPIError(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                code="AUTH_STORE_UNAVAILABLE",
                message="Authentication rate-limit store is temporarily unavailable.",
            ) from exc

    async def record_otp_verify_failure(
        self,
        *,
        phone_e164: str,
        window_seconds: int,
        max_failures: int,
    ) -> int | None:
        failures, ttl = await self._incr_window(self._verify_fail_key(phone_e164), window_seconds)
        return ttl if failures >= max_failures else None

    async def clear_otp_verify_failures(self, phone_e164: str) -> None:
        try:
            await self._redis.delete(self._verify_fail_key(phone_e164))
        except RedisError as exc:
            raise ChairAPIError(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                code="AUTH_STORE_UNAVAILABLE",
                message="Authentication rate-limit store is temporarily unavailable.",
            ) from exc

    async def save_refresh_family(
        self, family: RefreshFamilyRecord, *, ttl_seconds: int
    ) -> None:
        try:
            await self._redis.set(
                self._family_key(family.family_id),
                json.dumps(asdict(family)),
                ex=ttl_seconds,
            )
        except RedisError as exc:
            raise ChairAPIError(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                code="AUTH_STORE_UNAVAILABLE",
                message="Authentication session store is temporarily unavailable.",
            ) from exc

    async def get_refresh_family(self, family_id: str) -> RefreshFamilyRecord | None:
        try:
            raw = await self._redis.get(self._family_key(family_id))
        except RedisError as exc:
            raise ChairAPIError(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                code="AUTH_STORE_UNAVAILABLE",
                message="Authentication session store is temporarily unavailable.",
            ) from exc
        if raw is None:
            return None
        data = cast(dict[str, object], json.loads(raw))
        return RefreshFamilyRecord(
            family_id=str(data["family_id"]),
            user_id=str(data["user_id"]),
            active_jti_hash=str(data["active_jti_hash"]),
            revoked=bool(data["revoked"]),
        )

    async def rotate_refresh_family(
        self,
        *,
        family_id: str,
        expected_user_id: str,
        expected_jti_hash: str,
        new_jti_hash: str,
        ttl_seconds: int,
    ) -> RefreshRotateStatus:
        try:
            result = await self._redis.eval(
                _ROTATE_REFRESH_LUA,
                1,
                self._family_key(family_id),
                expected_user_id,
                expected_jti_hash,
                new_jti_hash,
                str(ttl_seconds),
            )
            return cast(RefreshRotateStatus, str(result))
        except RedisError as exc:
            raise ChairAPIError(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                code="AUTH_STORE_UNAVAILABLE",
                message="Authentication session store is temporarily unavailable.",
            ) from exc

    async def revoke_refresh_family(self, family_id: str, *, ttl_seconds: int) -> None:
        try:
            await self._redis.eval(
                _REVOKE_REFRESH_LUA,
                1,
                self._family_key(family_id),
                str(ttl_seconds),
            )
        except RedisError as exc:
            raise ChairAPIError(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                code="AUTH_STORE_UNAVAILABLE",
                message="Authentication session store is temporarily unavailable.",
            ) from exc


class InMemoryAuthStore:
    """Deterministic in-memory AuthStore for isolated unit tests."""

    def __init__(self) -> None:
        self._counters: dict[str, tuple[int, float]] = {}
        self._active_challenges: dict[str, str] = {}
        self._challenges: dict[str, tuple[OTPChallengeRecord, float]] = {}
        self._families: dict[str, tuple[RefreshFamilyRecord, float]] = {}

    def _incr_counter(self, key: str, window_seconds: int) -> tuple[int, int]:
        now = time.monotonic()
        current = self._counters.get(key)
        if current is None or current[1] <= now:
            expires_at = now + window_seconds
            self._counters[key] = (1, expires_at)
            return 1, window_seconds
        new_count = current[0] + 1
        self._counters[key] = (new_count, current[1])
        return new_count, max(1, int(current[1] - now))

    async def check_and_increment_otp_rate_limit(
        self,
        *,
        phone_e164: str,
        ip_key: str,
        window_seconds: int,
        max_per_phone: int,
        max_per_ip: int,
    ) -> int | None:
        ip_count, ip_ttl = self._incr_counter(f"ip:{ip_key}", window_seconds)
        if ip_count > max_per_ip:
            return ip_ttl
        phone_count, phone_ttl = self._incr_counter(f"phone:{phone_e164}", window_seconds)
        if phone_count > max_per_phone:
            return phone_ttl
        return None

    async def save_otp_challenge(
        self, challenge: OTPChallengeRecord, *, ttl_seconds: int
    ) -> None:
        prev_id = self._active_challenges.get(challenge.phone_e164)
        if prev_id and prev_id != challenge.challenge_id:
            self._challenges.pop(prev_id, None)
        self._active_challenges[challenge.phone_e164] = challenge.challenge_id
        self._challenges[challenge.challenge_id] = (challenge, time.monotonic() + ttl_seconds)

    async def claim_otp_attempt(
        self,
        *,
        challenge_id: str,
        expected_phone: str,
        max_attempts: int,
    ) -> tuple[OTPClaimStatus, int]:
        entry = self._challenges.get(challenge_id)
        if entry is None:
            return "missing", 0
        record, expires_at = entry
        if expires_at <= time.monotonic():
            del self._challenges[challenge_id]
            return "missing", 0
        if record.phone_e164 != expected_phone:
            return "missing", 0
        if record.attempts >= max_attempts:
            del self._challenges[challenge_id]
            return "locked", record.attempts
        record.attempts += 1
        return "claimed", record.attempts

    async def consume_otp_challenge(self, challenge_id: str) -> bool:
        return self._challenges.pop(challenge_id, None) is not None

    async def is_phone_verify_locked(self, phone_e164: str, *, max_failures: int) -> int | None:
        now = time.monotonic()
        entry = self._counters.get(f"fail:{phone_e164}")
        if entry is None or entry[1] <= now or entry[0] < max_failures:
            return None
        return max(1, int(entry[1] - now))

    async def record_otp_verify_failure(
        self,
        *,
        phone_e164: str,
        window_seconds: int,
        max_failures: int,
    ) -> int | None:
        failures, ttl = self._incr_counter(f"fail:{phone_e164}", window_seconds)
        return ttl if failures >= max_failures else None

    async def clear_otp_verify_failures(self, phone_e164: str) -> None:
        self._counters.pop(f"fail:{phone_e164}", None)

    async def save_refresh_family(
        self, family: RefreshFamilyRecord, *, ttl_seconds: int
    ) -> None:
        self._families[family.family_id] = (family, time.monotonic() + ttl_seconds)

    async def get_refresh_family(self, family_id: str) -> RefreshFamilyRecord | None:
        entry = self._families.get(family_id)
        if entry is None:
            return None
        record, expires_at = entry
        if expires_at <= time.monotonic():
            del self._families[family_id]
            return None
        return record

    async def rotate_refresh_family(
        self,
        *,
        family_id: str,
        expected_user_id: str,
        expected_jti_hash: str,
        new_jti_hash: str,
        ttl_seconds: int,
    ) -> RefreshRotateStatus:
        record = await self.get_refresh_family(family_id)
        if record is None or record.user_id != expected_user_id:
            return "missing"
        if record.revoked:
            return "revoked"
        if record.active_jti_hash != expected_jti_hash:
            record.revoked = True
            await self.save_refresh_family(record, ttl_seconds=ttl_seconds)
            return "reused"
        record.active_jti_hash = new_jti_hash
        await self.save_refresh_family(record, ttl_seconds=ttl_seconds)
        return "rotated"

    async def revoke_refresh_family(self, family_id: str, *, ttl_seconds: int) -> None:
        existing = await self.get_refresh_family(family_id)
        if existing is None:
            return
        existing.revoked = True
        await self.save_refresh_family(existing, ttl_seconds=ttl_seconds)
