from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import TransactionType
from app.routers.deps import AccountIdPath
from app.schemas import (
    AccountCreate,
    AccountOut,
    BalanceOut,
    ErrorResponse,
    TransactionCreate,
    TransactionOut,
    TransactionPage,
)
from app.services import accounts as account_service
from app.services import transactions as transaction_service

router = APIRouter(prefix="/accounts", tags=["Accounts"])

DB = Annotated[Session, Depends(get_db)]

_400 = {400: {"model": ErrorResponse, "description": "Invalid request"}}
_404 = {404: {"model": ErrorResponse, "description": "Account not found"}}


@router.post("", response_model=AccountOut, status_code=status.HTTP_201_CREATED, responses=_400)
def create_account(payload: AccountCreate, db: DB):
    """Create an account. Balance always starts at 0 and cannot be set by the client."""
    return account_service.create_account(db, payload.name)


@router.get("/{account_id}", response_model=AccountOut, responses={**_400, **_404})
def get_account(acct_id: AccountIdPath, db: DB):
    return account_service.get_account(db, acct_id)


@router.get("/{account_id}/balance", response_model=BalanceOut, responses={**_400, **_404})
def get_balance(acct_id: AccountIdPath, db: DB):
    account = account_service.get_account(db, acct_id)
    return BalanceOut(account_id=account.id, balance=account.balance)


@router.post(
    "/{account_id}/transactions",
    response_model=TransactionOut,
    status_code=status.HTTP_201_CREATED,
    responses={
        **_400,
        **_404,
        409: {"model": ErrorResponse, "description": "Duplicate reference_id for this account"},
        422: {"model": ErrorResponse, "description": "Insufficient balance"},
    },
)
def create_transaction(acct_id: AccountIdPath, payload: TransactionCreate, db: DB):
    """Credit or debit an account. The balance update and the insert are atomic."""
    return transaction_service.create_transaction(db, acct_id, payload)


@router.get(
    "/{account_id}/transactions",
    response_model=TransactionPage,
    responses={**_400, **_404},
)
def list_transactions(
    acct_id: AccountIdPath,
    db: DB,
    txn_type: Annotated[
        TransactionType | None, Query(alias="type", description="Filter by credit or debit")
    ] = None,
    page: Annotated[int, Query(ge=1, description="1-based page number")] = 1,
    limit: Annotated[
        int, Query(ge=1, le=settings.max_page_size, description="Page size")
    ] = settings.default_page_size,
):
    """Transaction history, latest first (by created_at)."""
    return transaction_service.list_transactions(db, acct_id, txn_type, page, limit)
