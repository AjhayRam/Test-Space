import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    DDL,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
    event,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# 18 digits, 2 decimal places: up to 9,999,999,999,999,999.99
MONEY = Numeric(18, 2)


class Base(DeclarativeBase):
    pass


class TransactionType(str, enum.Enum):
    CREDIT = "credit"
    DEBIT = "debit"


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        CheckConstraint("balance >= 0", name="ck_accounts_balance_non_negative"),
        CheckConstraint("length(trim(name)) > 0", name="ck_accounts_name_not_blank"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    balance: Mapped[Decimal] = mapped_column(
        MONEY, nullable=False, default=Decimal("0.00"), server_default=text("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Transfer(Base):
    __tablename__ = "transfers"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_transfers_amount_positive"),
        CheckConstraint("from_account_id <> to_account_id", name="ck_transfers_distinct_accounts"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    from_account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    to_account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))
    reference_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp()
    )


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint("account_id", "reference_id", name="uq_transactions_account_reference"),
        CheckConstraint("amount > 0", name="ck_transactions_amount_positive"),
        Index("ix_transactions_account_created", "account_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
    )
    type: Mapped[TransactionType] = mapped_column(
        Enum(
            TransactionType,
            name="transaction_type",
            native_enum=False,
            create_constraint=True,
            length=10,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))
    reference_id: Mapped[str] = mapped_column(String(100), nullable=False)
    transfer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("transfers.id", ondelete="RESTRICT"), index=True
    )
    # clock_timestamp() (not now()) so rows written in the same DB transaction
    # still get distinct, ordered timestamps.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp()
    )


# --- Immutability enforced by the database itself --------------------------
# Even if application code (or someone with SQL access through the app's role)
# tries to UPDATE or DELETE a ledger row, Postgres rejects it.

_prevent_mutation_fn = DDL(
    """
    CREATE OR REPLACE FUNCTION prevent_ledger_mutation() RETURNS trigger AS $$
    BEGIN
        RAISE EXCEPTION USING
            MESSAGE = TG_TABLE_NAME || ' rows are immutable; ' || TG_OP || ' is not allowed',
            ERRCODE = 'restrict_violation';
    END;
    $$ LANGUAGE plpgsql;
    """
)

for _table in (Transaction.__table__, Transfer.__table__):
    event.listen(_table, "after_create", _prevent_mutation_fn)
    event.listen(
        _table,
        "after_create",
        DDL(
            f"CREATE TRIGGER trg_{_table.name}_immutable "
            f"BEFORE UPDATE OR DELETE ON {_table.name} "
            "FOR EACH ROW EXECUTE FUNCTION prevent_ledger_mutation();"
        ),
    )
