import math
import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import DuplicateTransaction, InsufficientBalance
from app.models import Account, Transaction, TransactionType
from app.schemas import PaginationMeta, TransactionCreate, TransactionOut, TransactionPage
from app.services.accounts import get_account, lock_account


def find_by_reference(db: Session, account_id: uuid.UUID, reference_id: str) -> Transaction | None:
    return db.execute(
        select(Transaction).where(
            Transaction.account_id == account_id,
            Transaction.reference_id == reference_id,
        )
    ).scalar_one_or_none()


def duplicate_error(txn: Transaction) -> DuplicateTransaction:
    return DuplicateTransaction(TransactionOut.model_validate(txn).model_dump(mode="json"))


def apply_to_balance(account: Account, txn_type: TransactionType, amount: Decimal) -> None:
    """Mutate the (locked) account balance, rejecting overdrafts."""
    if txn_type is TransactionType.CREDIT:
        account.balance += amount
    else:
        if account.balance < amount:
            raise InsufficientBalance(account.id, account.balance, amount)
        account.balance -= amount


def create_transaction(db: Session, account_id: uuid.UUID, data: TransactionCreate) -> Transaction:
    """Insert a transaction and update the balance as ONE database transaction.

    Order matters:
      1. lock the account row      -> serialises concurrent writers
      2. duplicate check           -> retries are idempotent, never double-applied
      3. balance check + update    -> no overdraft
      4. insert + commit           -> both changes persist, or neither does
    """
    try:
        account = lock_account(db, account_id)

        existing = find_by_reference(db, account_id, data.reference_id)
        if existing is not None:
            raise duplicate_error(existing)

        apply_to_balance(account, data.type, data.amount)

        txn = Transaction(
            account_id=account.id,
            type=data.type,
            amount=data.amount,
            description=data.description,
            reference_id=data.reference_id,
        )
        db.add(txn)
        db.commit()
    except IntegrityError:
        # Defensive: the unique constraint is the final guard against duplicates.
        db.rollback()
        existing = find_by_reference(db, account_id, data.reference_id)
        if existing is not None:
            raise duplicate_error(existing) from None
        raise
    except Exception:
        db.rollback()
        raise

    db.refresh(txn)
    return txn


def get_transaction(db: Session, transaction_id: uuid.UUID) -> Transaction | None:
    return db.get(Transaction, transaction_id)


def list_transactions(
    db: Session,
    account_id: uuid.UUID,
    txn_type: TransactionType | None,
    page: int,
    limit: int,
) -> TransactionPage:
    get_account(db, account_id)  # 404 if the account does not exist

    query = select(Transaction).where(Transaction.account_id == account_id)
    if txn_type is not None:
        query = query.where(Transaction.type == txn_type)

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    total_pages = math.ceil(total / limit) if total else 0

    offset = (page - 1) * limit
    rows: list[Transaction] = []
    if offset < total:
        rows = list(
            db.scalars(
                query.order_by(Transaction.created_at.desc(), Transaction.id.desc())
                .offset(offset)
                .limit(limit)
            )
        )

    return TransactionPage(
        data=[TransactionOut.model_validate(r) for r in rows],
        pagination=PaginationMeta(page=page, limit=limit, total_records=total, total_pages=total_pages),
    )
