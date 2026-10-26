from fastapi import status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Transaction, TransactionType, Transfer
from app.schemas import TransactionOut, TransferCreate, TransferOut
from app.services.accounts import lock_account
from app.services.transactions import apply_to_balance, duplicate_error, find_by_reference


def _transfer_out(transfer: Transfer, debit: Transaction, credit: Transaction, src_bal, dst_bal) -> TransferOut:
    return TransferOut(
        id=transfer.id,
        from_account_id=transfer.from_account_id,
        to_account_id=transfer.to_account_id,
        amount=transfer.amount,
        description=transfer.description,
        reference_id=transfer.reference_id,
        created_at=transfer.created_at,
        debit_transaction=TransactionOut.model_validate(debit),
        credit_transaction=TransactionOut.model_validate(credit),
        from_account_balance=src_bal,
        to_account_balance=dst_bal,
    )


def _duplicate_transfer(transfer: Transfer) -> AppError:
    return AppError(
        status.HTTP_409_CONFLICT,
        "DUPLICATE_TRANSFER",
        "A transfer with this reference_id already exists",
        {"existing_transfer_id": str(transfer.id)},
    )


def create_transfer(db: Session, data: TransferCreate) -> TransferOut:
    """Debit the source and credit the destination atomically.

    Both account rows are locked in a deterministic order (sorted by id), so two
    opposite transfers (A->B and B->A) running at once cannot deadlock. Any
    failure rolls back the whole unit: a partial transfer is impossible.
    """
    if data.from_account_id == data.to_account_id:
        raise AppError(
            status.HTTP_400_BAD_REQUEST,
            "SAME_ACCOUNT_TRANSFER",
            "Source and destination accounts must be different",
        )

    try:
        locked = {
            account_id: lock_account(db, account_id)
            for account_id in sorted({data.from_account_id, data.to_account_id}, key=str)
        }
        source = locked[data.from_account_id]
        destination = locked[data.to_account_id]

        existing = db.execute(
            select(Transfer).where(Transfer.reference_id == data.reference_id)
        ).scalar_one_or_none()
        if existing is not None:
            raise _duplicate_transfer(existing)

        # Each leg is also a ledger transaction, so its reference must be free on that account.
        for account in (source, destination):
            clash = find_by_reference(db, account.id, data.reference_id)
            if clash is not None:
                raise duplicate_error(clash)

        apply_to_balance(source, TransactionType.DEBIT, data.amount)
        apply_to_balance(destination, TransactionType.CREDIT, data.amount)

        transfer = Transfer(
            from_account_id=source.id,
            to_account_id=destination.id,
            amount=data.amount,
            description=data.description,
            reference_id=data.reference_id,
        )
        db.add(transfer)
        db.flush()

        debit = Transaction(
            account_id=source.id,
            type=TransactionType.DEBIT,
            amount=data.amount,
            description=data.description or f"Transfer to {destination.id}",
            reference_id=data.reference_id,
            transfer_id=transfer.id,
        )
        credit = Transaction(
            account_id=destination.id,
            type=TransactionType.CREDIT,
            amount=data.amount,
            description=data.description or f"Transfer from {source.id}",
            reference_id=data.reference_id,
            transfer_id=transfer.id,
        )
        db.add_all([debit, credit])
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.execute(
            select(Transfer).where(Transfer.reference_id == data.reference_id)
        ).scalar_one_or_none()
        if existing is not None:
            raise _duplicate_transfer(existing) from None
        raise
    except Exception:
        db.rollback()
        raise

    for obj in (transfer, debit, credit, source, destination):
        db.refresh(obj)
    return _transfer_out(transfer, debit, credit, source.balance, destination.balance)
