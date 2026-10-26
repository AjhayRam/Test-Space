import uuid

from tests.conftest import balance_of


def test_create_account_starts_with_zero_balance(client):
    resp = client.post("/accounts", json={"name": "  Alice  "})
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Alice"
    assert body["balance"] == "0.00"
    uuid.UUID(body["id"])
    assert body["created_at"]


def test_account_ids_are_unique(client):
    ids = {client.post("/accounts", json={"name": f"user{i}"}).json()["id"] for i in range(5)}
    assert len(ids) == 5


def test_client_cannot_set_initial_balance(client):
    resp = client.post("/accounts", json={"name": "Alice", "balance": 1000})
    assert resp.status_code == 400
    err = resp.json()["error"]
    assert err["code"] == "VALIDATION_ERROR"
    assert err["details"][0]["field"] == "balance"


def test_name_is_required(client):
    for payload in ({}, {"name": ""}, {"name": "   "}, {"name": None}, {"name": 123}):
        resp = client.post("/accounts", json=payload)
        assert resp.status_code == 400, payload
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_invalid_json_body(client):
    resp = client.post("/accounts", content="{not json", headers={"Content-Type": "application/json"})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_REQUEST_BODY"


def test_get_account_and_balance(client, make_account):
    account_id = make_account("Bob", balance="25.50")
    assert client.get(f"/accounts/{account_id}").json()["balance"] == "25.50"
    resp = client.get(f"/accounts/{account_id}/balance")
    assert resp.status_code == 200
    assert resp.json() == {"account_id": account_id, "balance": "25.50"}
    assert balance_of(client, account_id) == "25.50"


def test_unknown_account_returns_404(client):
    missing = uuid.uuid4()
    for path in (f"/accounts/{missing}", f"/accounts/{missing}/balance", f"/accounts/{missing}/transactions"):
        resp = client.get(path)
        assert resp.status_code == 404, path
        assert resp.json()["error"]["code"] == "ACCOUNT_NOT_FOUND"


def test_malformed_account_id_returns_400(client):
    resp = client.get("/accounts/not-a-uuid/balance")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_ACCOUNT_ID"
