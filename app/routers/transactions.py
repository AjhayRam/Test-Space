import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Path, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.schemas import ErrorResponse, TransactionOut
from app.services import transactions as transaction_service

router = APIRouter(prefix="/transactions", tags=["Transactions"])


def _parse_txn_id(transaction_id: Annotated[str, Path()]) -> uuid.UUID:
    try:
        return uuid.UUID(transaction_id)
    except ValueError:
        raise AppError(
            status.HTTP_400_BAD_REQUEST, "INVALID_TRANSACTION_ID", "Transaction ID must be a valid UUID"
        ) from None


@router.get(
    "/{transaction_id}",
    response_model=TransactionOut,
    responses={404: {"model": ErrorResponse, "description": "Transaction not found"}},
)
def get_transaction(txn_id: Annotated[uuid.UUID, Depends(_parse_txn_id)], db: Annotated[Session, Depends(get_db)]):
    txn = transaction_service.get_transaction(db, txn_id)
    if txn is None:
        raise AppError(status.HTTP_404_NOT_FOUND, "TRANSACTION_NOT_FOUND", f"Transaction {txn_id} was not found")
    return txn


@router.api_route("/{transaction_id}", methods=["PUT", "PATCH", "DELETE"], include_in_schema=False)
def reject_mutation():
    """Transactions are an append-only ledger: they can never be edited or deleted."""
    raise AppError(
        status.HTTP_405_METHOD_NOT_ALLOWED,
        "TRANSACTION_IMMUTABLE",
        "Transactions are immutable and cannot be modified or deleted",
    )
