import os

# Point the app at the test database BEFORE any app module is imported.
os.environ["DATABASE_URL"] = os.getenv(
    "TEST_DATABASE_URL", "postgresql+psycopg://ledger:ledger@localhost:5433/ledger_test"
)
os.environ["AUTO_CREATE_TABLES"] = "false"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.database import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _schema():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    engine.dispose()


@pytest.fixture(autouse=True)
def _clean_tables():
    # TRUNCATE bypasses the row-level immutability triggers, which is what we want for test cleanup.
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE transactions, transfers, accounts CASCADE"))
    yield


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def make_account(client):
    def _make(name: str = "Alice", balance: str | None = None) -> str:
        resp = client.post("/accounts", json={"name": name})
        assert resp.status_code == 201, resp.text
        account_id = resp.json()["id"]
        if balance is not None:
            r = client.post(
                f"/accounts/{account_id}/transactions",
                json={"type": "credit", "amount": balance, "reference_id": f"seed-{account_id}"},
            )
            assert r.status_code == 201, r.text
        return account_id

    return _make


def balance_of(client, account_id: str) -> str:
    resp = client.get(f"/accounts/{account_id}/balance")
    assert resp.status_code == 200, resp.text
    return resp.json()["balance"]
