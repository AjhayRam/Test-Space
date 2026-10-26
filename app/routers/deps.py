import uuid
from typing import Annotated

from fastapi import Depends, Path

from app.errors import InvalidAccountId


def _account_id_path(account_id: Annotated[str, Path(description="Account UUID")]) -> uuid.UUID:
    try:
        return uuid.UUID(account_id)
    except ValueError:
        raise InvalidAccountId(account_id) from None


# Malformed IDs -> 400 INVALID_ACCOUNT_ID; well-formed but unknown IDs -> 404 in the service layer.
AccountIdPath = Annotated[uuid.UUID, Depends(_account_id_path)]
