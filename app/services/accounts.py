import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AccountNotFound
from app.models import Account


def create_account(db: Session, name: str) -> Account:
    # Balance is always initialised by the server, never by the client.
    account = Account(name=name, balance=Decimal("0.00"))
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


def get_account(db: Session, account_id: uuid.UUID) -> Account:
    account = db.get(Account, account_id)
    if account is None:
        raise AccountNotFound(account_id)
    return account


def lock_account(db: Session, account_id: uuid.UUID) -> Account:
    """Load an account with a row-level lock (SELECT ... FOR UPDATE).

    Concurrent writers to the same account queue up behind this lock, so the
    balance check and balance update can never interleave.
    """
    account = db.execute(
        select(Account).where(Account.id == account_id).with_for_update()
    ).scalar_one_or_none()
    if account is None:
        raise AccountNotFound(account_id)
    return account
