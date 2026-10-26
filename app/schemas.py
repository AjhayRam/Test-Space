import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.models import TransactionType

# Money is accepted as a JSON number or string and returned as a string
# (e.g. "150.00") so no precision is lost to floating point.
PositiveAmount = Annotated[
    Decimal,
    Field(gt=0, max_digits=18, decimal_places=2, examples=["100.00"]),
]
ReferenceId = Annotated[str, Field(min_length=1, max_length=100, examples=["INV-1001"])]
Description = Annotated[str | None, Field(default=None, max_length=500, examples=["Salary"])]


class _Input(BaseModel):
    # Unknown fields (e.g. "balance" on account creation) are rejected, not ignored.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class _Output(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- Accounts ---------------------------------------------------------------


class AccountCreate(_Input):
    name: str = Field(min_length=1, max_length=255, examples=["Alice"])


class AccountOut(_Output):
    id: uuid.UUID
    name: str
    balance: Decimal
    created_at: datetime


class BalanceOut(BaseModel):
    account_id: uuid.UUID
    balance: Decimal


# --- Transactions -----------------------------------------------------------


class TransactionCreate(_Input):
    type: TransactionType
    amount: PositiveAmount
    description: Description = None
    reference_id: ReferenceId


class TransactionOut(_Output):
    id: uuid.UUID
    account_id: uuid.UUID
    type: TransactionType
    amount: Decimal
    description: str | None
    reference_id: str
    transfer_id: uuid.UUID | None
    created_at: datetime


class PaginationMeta(BaseModel):
    page: int
    limit: int
    total_records: int
    total_pages: int


class TransactionPage(BaseModel):
    data: list[TransactionOut]
    pagination: PaginationMeta


# --- Transfers --------------------------------------------------------------


class TransferCreate(_Input):
    from_account_id: uuid.UUID
    to_account_id: uuid.UUID
    amount: PositiveAmount
    description: Description = None
    reference_id: ReferenceId


class TransferOut(_Output):
    id: uuid.UUID
    from_account_id: uuid.UUID
    to_account_id: uuid.UUID
    amount: Decimal
    description: str | None
    reference_id: str
    created_at: datetime
    debit_transaction: TransactionOut
    credit_transaction: TransactionOut
    from_account_balance: Decimal
    to_account_balance: Decimal


# --- Errors (for OpenAPI docs) ---------------------------------------------


class ErrorDetail(BaseModel):
    code: str = Field(examples=["ACCOUNT_NOT_FOUND"])
    message: str
    details: object | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail
