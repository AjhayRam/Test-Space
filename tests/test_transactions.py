import threading
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.database import SessionLocal, engine
from app.errors import InsufficientBalance
from app.models import TransactionType
from app.schemas import TransactionCreate
from app.services.transactions import create_transaction
from tests.conftest import balance_of


def post_txn(client, account_id, type_, amount, ref, description=None):
    payload = {"type": type_, "amount": amount, "reference_id": ref}
    if description is not None:
        payload["description"] = description
    return client.post(f"/accounts/{account_id}/transactions", json=payload)


def test_balance_example_from_spec(client, make_account):
    acc = make_account()
    for i, (t, amt) in enumerate([("credit", 100), ("credit", 50), ("debit", 30), ("debit", 20)]):
        assert post_txn(client, acc, t, amt, f"ref-{i}").status_code == 201
    assert balance_of(client, acc) == "100.00"


def test_transaction_response_shape(client, make_account):
    acc = make_account()
    resp = post_txn(client, acc, "credit", "150.25", "INV-1", "Salary")
    assert resp.status_code == 201
    body = resp.json()
    assert body["account_id"] == acc
    assert body["type"] == "credit"
    assert body["amount"] == "150.25"
    assert body["description"] == "Salary"
    assert body["reference_id"] == "INV-1"
    assert body["transfer_id"] is None
    assert body["created_at"]


def test_debit_rejected_when_insufficient_balance(client, make_account):
    acc = make_account(balance="100")
    resp = post_txn(client, acc, "debit", 150, "too-much")
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "INSUFFICIENT_BALANCE"
    assert balance_of(client, acc) == "100.00"
    # The rejected transaction was not recorded.
    history = client.get(f"/accounts/{acc}/transactions").json()
    assert history["pagination"]["total_records"] == 1


def test_debit_of_exact_balance_is_allowed(client, make_account):
    acc = make_account(balance="40")
    assert post_txn(client, acc, "debit", "40.00", "all").status_code == 201
    assert balance_of(client, acc) == "0.00"


def test_duplicate_reference_id_same_account(client, make_account):
    acc = make_account()
    first = post_txn(client, acc, "credit", 100, "dup")
    assert first.status_code == 201

    second = post_txn(client, acc, "credit", 100, "dup")
    assert second.status_code == 409
    err = second.json()["error"]
    assert err["code"] == "DUPLICATE_TRANSACTION"
    assert err["details"]["existing_transaction"]["id"] == first.json()["id"]

    assert balance_of(client, acc) == "100.00"
    assert client.get(f"/accounts/{acc}/transactions").json()["pagination"]["total_records"] == 1


def test_same_reference_id_allowed_on_different_accounts(client, make_account):
    a, b = make_account("A"), make_account("B")
    assert post_txn(client, a, "credit", 10, "shared").status_code == 201
    assert post_txn(client, b, "credit", 10, "shared").status_code == 201


def test_unknown_account(client):
    resp = post_txn(client, uuid.uuid4(), "credit", 10, "x")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "ACCOUNT_NOT_FOUND"


@pytest.mark.parametrize(
    "payload, code",
    [
        ({"type": "refund", "amount": 10, "reference_id": "r"}, "INVALID_TRANSACTION_TYPE"),
        ({"amount": 10, "reference_id": "r"}, "INVALID_TRANSACTION_TYPE"),
        ({"type": "credit", "amount": 0, "reference_id": "r"}, "INVALID_AMOUNT"),
        ({"type": "credit", "amount": -5, "reference_id": "r"}, "INVALID_AMOUNT"),
        ({"type": "credit", "amount": "abc", "reference_id": "r"}, "INVALID_AMOUNT"),
        ({"type": "credit", "amount": 10.555, "reference_id": "r"}, "INVALID_AMOUNT"),
        ({"type": "credit", "reference_id": "r"}, "INVALID_AMOUNT"),
        ({"type": "credit", "amount": 10}, "VALIDATION_ERROR"),
        ({"type": "credit", "amount": 10, "reference_id": "  "}, "VALIDATION_ERROR"),
        ({"type": "credit", "amount": 10, "reference_id": "r", "account_id": "x"}, "VALIDATION_ERROR"),
    ],
)
def test_validation_errors(client, make_account, payload, code):
    acc = make_account()
    resp = client.post(f"/accounts/{acc}/transactions", json=payload)
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == code
    assert balance_of(client, acc) == "0.00"


def test_transactions_cannot_be_modified_via_api(client, make_account):
    acc = make_account()
    txn_id = post_txn(client, acc, "credit", 10, "r").json()["id"]
    assert client.get(f"/transactions/{txn_id}").status_code == 200
    for method in ("PUT", "PATCH", "DELETE"):
        resp = client.request(method, f"/transactions/{txn_id}", json={"amount": 999})
        assert resp.status_code == 405
        assert resp.json()["error"]["code"] == "TRANSACTION_IMMUTABLE"
    assert balance_of(client, acc) == "10.00"


def test_database_rejects_update_and_delete_of_transactions(client, make_account):
    acc = make_account()
    txn_id = post_txn(client, acc, "credit", 10, "r").json()["id"]
    for stmt in ("UPDATE transactions SET amount = 1 WHERE id = :id", "DELETE FROM transactions WHERE id = :id"):
        with pytest.raises(DBAPIError, match="immutable"):
            with engine.begin() as conn:
                conn.execute(text(stmt), {"id": txn_id})


def test_database_rejects_negative_balance(client, make_account):
    acc = make_account()
    with pytest.raises(DBAPIError, match="ck_accounts_balance_non_negative"):
        with engine.begin() as conn:
            conn.execute(text("UPDATE accounts SET balance = -1 WHERE id = :id"), {"id": acc})


def test_concurrent_debits_never_overdraw(client, make_account):
    """10 parallel debits of 30 against a balance of 100: exactly 3 may succeed."""
    acc = uuid.UUID(make_account(balance="100"))
    results: list[str] = []
    lock = threading.Lock()

    def worker(i: int):
        db = SessionLocal()
        try:
            create_transaction(
                db, acc, TransactionCreate(type=TransactionType.DEBIT, amount=Decimal("30"), reference_id=f"c-{i}")
            )
            outcome = "ok"
        except InsufficientBalance:
            outcome = "rejected"
        finally:
            db.close()
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results.count("ok") == 3
    assert results.count("rejected") == 7
    assert balance_of(client, str(acc)) == "10.00"


def test_concurrent_duplicate_reference_creates_one_transaction(client, make_account):
    acc = uuid.UUID(make_account())
    outcomes: list[str] = []

    def worker():
        db = SessionLocal()
        try:
            create_transaction(
                db, acc, TransactionCreate(type=TransactionType.CREDIT, amount=Decimal("5"), reference_id="same")
            )
            outcomes.append("ok")
        except Exception as exc:  # noqa: BLE001
            outcomes.append(type(exc).__name__)
        finally:
            db.close()

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert outcomes.count("ok") == 1
    assert outcomes.count("DuplicateTransaction") == 7
    assert balance_of(client, str(acc)) == "5.00"
