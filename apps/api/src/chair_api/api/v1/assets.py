"""Private signed asset download endpoint with strict auth & tenant verification."""

from typing import Annotated

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import select

from chair_api.api.deps import DbSessionDep, StorageProviderDep
from chair_api.core.errors import ChairAPIError
from chair_api.db.models import Salon, SalonDocument, StylePhoto
from chair_api.domain.enums import UserRole
from chair_api.security.rbac import CurrentPrincipalDep

router = APIRouter()


@router.get("/signed")
async def download_signed_private_asset(
    key: Annotated[str, Query(min_length=3, max_length=512)],
    expires: Annotated[int, Query(gt=0)],
    sig: Annotated[str, Query(min_length=16, max_length=128)],
    principal: CurrentPrincipalDep,
    session: DbSessionDep,
    storage: StorageProviderDep,
) -> Response:
    """Serve private salon documents or style photos only with valid HMAC URL + RBAC access."""
    if not storage.verify_signed_url(object_key=key, expires=expires, signature=sig):
        raise ChairAPIError(
            status_code=status.HTTP_403_FORBIDDEN,
            code="INVALID_OR_EXPIRED_SIGNED_URL",
            message="Signed URL is invalid or has expired.",
        )

    doc = await session.scalar(select(SalonDocument).where(SalonDocument.storage_key == key))
    if doc is not None:
        is_admin = UserRole.ADMIN in principal.role_set
        if not is_admin:
            salon = await session.scalar(select(Salon).where(Salon.id == doc.salon_id))
            salon_owner_id = salon.owner_user_id if salon else None
            allowed = (
                principal.can_access_branch(
                    doc.branch_id, doc.salon_id, salon_owner_user_id=salon_owner_id
                )
                if doc.branch_id is not None
                else principal.can_access_salon(
                    doc.salon_id, salon_owner_user_id=salon_owner_id
                )
            )
            if not allowed:
                raise ChairAPIError(
                    status_code=status.HTTP_403_FORBIDDEN,
                    code="DOCUMENT_ACCESS_DENIED",
                    message="You are not authorized to access this private document.",
                )
        mime_type = doc.mime_type
    else:
        photo = await session.scalar(select(StylePhoto).where(StylePhoto.storage_key == key))
        if photo is None:
            raise ChairAPIError(
                status_code=status.HTTP_404_NOT_FOUND,
                code="ASSET_NOT_FOUND",
                message="Private asset was not found.",
            )
        if photo.user_id != principal.user.id and UserRole.ADMIN not in principal.role_set:
            raise ChairAPIError(
                status_code=status.HTTP_403_FORBIDDEN,
                code="ASSET_ACCESS_DENIED",
                message="You are not authorized to access this photo.",
            )
        mime_type = photo.mime_type

    try:
        content = storage.read_object(object_key=key)
    except (FileNotFoundError, ValueError) as exc:
        raise ChairAPIError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="ASSET_NOT_FOUND",
            message="Stored private object could not be read.",
        ) from exc

    return Response(
        content=content,
        media_type=mime_type,
        headers={
            "Content-Disposition": "inline",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )
