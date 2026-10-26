import threading
import uuid
from decimal import Decimal

from app.database import SessionLocal
from app.errors import InsufficientBalance
from app.schemas import TransferCreate
from app.services.transfers import create_transfer
from tests.conftest import balance_of


def transfer(client, src, dst, amount, ref="T-1", **extra):
    return client.post(
        "/transfers",
        json={"from_account_id": str(src), "to_account_id": str(dst), "amount": amount, "reference_id": ref, **extra},
    )


def history_count(client, acc):
    return client.get(f"/accounts/{acc}/transactions").json()["pagination"]["total_records"]


def test_transfer_example_from_spec(client, make_account):
    a, b = make_account("A", balance="100"), make_account("B", balance="50")
    resp = transfer(client, a, b, 30, description="Rent share")
    assert resp.status_code == 201
    body = resp.json()
    assert body["from_account_balance"] == "70.00"
    assert body["to_account_balance"] == "80.00"
    assert body["debit_transaction"]["type"] == "debit"
    assert body["credit_transaction"]["type"] == "credit"
    assert body["debit_transaction"]["transfer_id"] == body["id"]
    assert balance_of(client, a) == "70.00"
    assert balance_of(client, b) == "80.00"


def test_transfer_insufficient_balance_changes_nothing(client, make_account):
    a, b = make_account("A", balance="100"), make_account("B", balance="50")
    resp = transfer(client, a, b, 150)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "INSUFFICIENT_BALANCE"
    assert (balance_of(client, a), balance_of(client, b)) == ("100.00", "50.00")
    assert (history_count(client, a), history_count(client, b)) == (1, 1)


def test_transfer_unknown_account(client, make_account):
    a = make_account("A", balance="100")
    for src, dst in ((a, uuid.uuid4()), (uuid.uuid4(), a)):
        resp = transfer(client, src, dst, 10)
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "ACCOUNT_NOT_FOUND"
    assert balance_of(client, a) == "100.00"


def test_transfer_to_same_account_rejected(client, make_account):
    a = make_account("A", balance="100")
    resp = transfer(client, a, a, 10)
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "SAME_ACCOUNT_TRANSFER"


def test_transfer_validation(client, make_account):
    a, b = make_account("A", balance="100"), make_account("B")
    assert transfer(client, a, b, 0).json()["error"]["code"] == "INVALID_AMOUNT"
    assert transfer(client, "nope", b, 10).json()["error"]["code"] == "INVALID_ACCOUNT_ID"


def test_duplicate_transfer_reference(client, make_account):
    a, b = make_account("A", balance="100"), make_account("B")
    assert transfer(client, a, b, 10, ref="dup").status_code == 201
    resp = transfer(client, a, b, 10, ref="dup")
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "DUPLICATE_TRANSFER"
    assert (balance_of(client, a), balance_of(client, b)) == ("90.00", "10.00")


def test_failed_leg_rolls_back_entire_transfer(client, make_account):
    """If the credit leg cannot be written (its reference already exists on the
    destination), the debit on the source must not persist either."""
    a, b = make_account("A", balance="100"), make_account("B")
    client.post(f"/accounts/{b}/transactions", json={"type": "credit", "amount": 1, "reference_id": "clash"})

    resp = transfer(client, a, b, 30, ref="clash")
    assert resp.status_code == 409
    assert (balance_of(client, a), balance_of(client, b)) == ("100.00", "1.00")
    assert (history_count(client, a), history_count(client, b)) == (1, 1)


def test_opposite_concurrent_transfers_no_deadlock_and_money_conserved(client, make_account):
    a = uuid.UUID(make_account("A", balance="1000"))
    b = uuid.UUID(make_account("B", balance="1000"))
    errors: list[Exception] = []

    def worker(i: int):
        src, dst = (a, b) if i % 2 == 0 else (b, a)
        db = SessionLocal()
        try:
            create_transfer(db, TransferCreate(from_account_id=src, to_account_id=dst, amount=Decimal("7"), reference_id=f"t{i}"))
        except InsufficientBalance:
            pass
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            db.close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, errors
    total = Decimal(balance_of(client, str(a))) + Decimal(balance_of(client, str(b)))
    assert total == Decimal("2000.00")
