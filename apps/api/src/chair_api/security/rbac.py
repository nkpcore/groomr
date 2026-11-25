"""Server-side RBAC, principal loading, and salon/branch tenant isolation guards."""

import ipaddress
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from chair_api.core.auth_store import AuthStore
from chair_api.core.config import Settings, get_settings
from chair_api.core.errors import ChairAPIError
from chair_api.db.models import Branch, Salon, User, UserRoleAssignment
from chair_api.db.session import get_db_session
from chair_api.domain.enums import UserRole
from chair_api.security.tokens import decode_token, hash_client_ip

_bearer_scheme = HTTPBearer(auto_error=False)
_OptionalBearerDep = Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)]
_SessionDep = Annotated[AsyncSession, Depends(get_db_session)]

ROLE_PRECEDENCE: tuple[UserRole, ...] = (
    UserRole.ADMIN,
    UserRole.PARTNER_OWNER,
    UserRole.PARTNER_STAFF,
    UserRole.CUSTOMER,
)


def highest_precedence_role(roles: Sequence[UserRole] | frozenset[UserRole]) -> str:
    """Return the highest-privilege role string for audit attribution."""
    role_set = frozenset(roles)
    for preferred in ROLE_PRECEDENCE:
        if preferred in role_set:
            return preferred.value
    return UserRole.CUSTOMER.value


@dataclass(frozen=True, slots=True)
class RoleScope:
    id: uuid.UUID
    role: UserRole
    salon_id: uuid.UUID | None
    branch_id: uuid.UUID | None


@dataclass(frozen=True, slots=True)
class AuthPrincipal:
    user: User
    roles: tuple[RoleScope, ...]
    role_set: frozenset[UserRole]
    request_id: str | None
    ip_address: str | None
    ip_hash: str | None
    user_agent: str | None

    @property
    def primary_role(self) -> str:
        return highest_precedence_role(self.role_set)

    def has_any_role(self, *allowed_roles: UserRole) -> bool:
        return bool(self.role_set.intersection(allowed_roles))

    def can_access_salon(
        self,
        salon_id: uuid.UUID,
        *,
        salon_owner_user_id: uuid.UUID | None = None,
        allowed_roles: tuple[UserRole, ...] = (UserRole.PARTNER_OWNER, UserRole.PARTNER_STAFF),
    ) -> bool:
        if UserRole.PARTNER_OWNER in allowed_roles and UserRole.PARTNER_OWNER in self.role_set:
            if salon_owner_user_id is not None and salon_owner_user_id == self.user.id:
                return True
        return any(
            scope.role in allowed_roles and scope.salon_id == salon_id and scope.branch_id is None
            for scope in self.roles
        )

    def can_access_branch(
        self,
        branch_id: uuid.UUID,
        salon_id: uuid.UUID,
        *,
        salon_owner_user_id: uuid.UUID | None = None,
        allowed_roles: tuple[UserRole, ...] = (UserRole.PARTNER_OWNER, UserRole.PARTNER_STAFF),
    ) -> bool:
        if UserRole.PARTNER_OWNER in allowed_roles and UserRole.PARTNER_OWNER in self.role_set:
            if salon_owner_user_id is not None and salon_owner_user_id == self.user.id:
                return True

        for scope in self.roles:
            if scope.role not in allowed_roles:
                continue
            if scope.branch_id == branch_id:
                return True
            if scope.salon_id == salon_id and scope.branch_id is None:
                return True
        return False


def extract_client_ip(request: Request, settings: Settings | None = None) -> str | None:
    """Resolve client IP, optionally trusting validated proxy X-Forwarded-For hops."""
    if settings is not None and settings.trust_proxy_headers:
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            first_hop = forwarded_for.split(",")[0].strip()
            try:
                return str(ipaddress.ip_address(first_hop))
            except ValueError:
                pass
    return request.client.host if request.client is not None else None


async def get_current_principal(
    request: Request,
    credentials: _OptionalBearerDep,
    session: _SessionDep,
) -> AuthPrincipal:
    """Verify access JWT, active session family, and live DB role assignments."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise ChairAPIError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="AUTHENTICATION_REQUIRED",
            message="Valid bearer authentication token is required.",
        )

    settings: Settings = getattr(request.app.state, "settings", None) or get_settings()
    claims = decode_token(credentials.credentials, settings=settings, expected_typ="access")

    if claims.fam is not None:
        auth_store: AuthStore | None = getattr(request.app.state, "auth_store", None)
        if auth_store is not None:
            family = await auth_store.get_refresh_family(claims.fam)
            if family is None or family.revoked or family.user_id != str(claims.sub):
                raise ChairAPIError(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    code="SESSION_REVOKED",
                    message="Session has been signed out or revoked.",
                )

    user = await session.scalar(select(User).where(User.id == claims.sub))
    if user is None or not user.is_active:
        raise ChairAPIError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="ACCOUNT_INACTIVE",
            message="User account does not exist or is inactive.",
        )

    role_rows = list(
        await session.scalars(
            select(UserRoleAssignment).where(UserRoleAssignment.user_id == user.id)
        )
    )
    scopes = tuple(
        RoleScope(
            id=row.id,
            role=UserRole(row.role),
            salon_id=row.salon_id,
            branch_id=row.branch_id,
        )
        for row in role_rows
    )
    role_set = frozenset(scope.role for scope in scopes)
    raw_ip = extract_client_ip(request, settings)
    return AuthPrincipal(
        user=user,
        roles=scopes,
        role_set=role_set,
        request_id=getattr(request.state, "request_id", None),
        ip_address=raw_ip,
        ip_hash=hash_client_ip(raw_ip, secret_key=settings.secret_key),
        user_agent=request.headers.get("User-Agent"),
    )


CurrentPrincipalDep = Annotated[AuthPrincipal, Depends(get_current_principal)]


def require_roles(
    *allowed_roles: UserRole,
) -> Callable[[AuthPrincipal], Awaitable[AuthPrincipal]]:
    """Create a FastAPI dependency requiring at least one explicitly allowed role."""

    async def dependency(
        principal: CurrentPrincipalDep,
    ) -> AuthPrincipal:
        if not principal.has_any_role(*allowed_roles):
            raise ChairAPIError(
                status_code=status.HTTP_403_FORBIDDEN,
                code="FORBIDDEN",
                message="You do not have permission to access this resource.",
            )
        return principal

    return dependency


async def assert_salon_access(
    session: AsyncSession,
    principal: AuthPrincipal,
    salon_id: uuid.UUID,
    *,
    allowed_roles: tuple[UserRole, ...] = (UserRole.PARTNER_OWNER, UserRole.PARTNER_STAFF),
) -> Salon:
    """Enforce tenant isolation for a salon resource before returning it."""
    salon = await session.scalar(select(Salon).where(Salon.id == salon_id))
    if salon is None or not principal.can_access_salon(
        salon.id,
        salon_owner_user_id=salon.owner_user_id,
        allowed_roles=allowed_roles,
    ):
        raise ChairAPIError(
            status_code=status.HTTP_403_FORBIDDEN,
            code="TENANT_ACCESS_DENIED",
            message="You are not authorized for this salon.",
        )
    return salon


async def assert_branch_access(
    session: AsyncSession,
    principal: AuthPrincipal,
    branch_id: uuid.UUID,
    *,
    allowed_roles: tuple[UserRole, ...] = (UserRole.PARTNER_OWNER, UserRole.PARTNER_STAFF),
) -> Branch:
    """Enforce tenant isolation for a branch resource before returning it."""
    row = (
        await session.execute(
            select(Branch, Salon.owner_user_id)
            .join(Salon, Salon.id == Branch.salon_id)
            .where(Branch.id == branch_id)
        )
    ).first()
    if row is None:
        raise ChairAPIError(
            status_code=status.HTTP_403_FORBIDDEN,
            code="TENANT_ACCESS_DENIED",
            message="You are not authorized for this branch.",
        )
    branch, owner_user_id = row
    if not principal.can_access_branch(
        branch.id,
        branch.salon_id,
        salon_owner_user_id=owner_user_id,
        allowed_roles=allowed_roles,
    ):
        raise ChairAPIError(
            status_code=status.HTTP_403_FORBIDDEN,
            code="TENANT_ACCESS_DENIED",
            message="You are not authorized for this branch.",
        )
    return branch
