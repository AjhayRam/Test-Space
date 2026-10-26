import pytest


@pytest.fixture
def account_with_history(client, make_account):
    acc = make_account()
    # 7 credits and 5 debits, created in a known order
    for i in range(7):
        client.post(f"/accounts/{acc}/transactions", json={"type": "credit", "amount": 10, "reference_id": f"c{i}"})
    for i in range(5):
        client.post(f"/accounts/{acc}/transactions", json={"type": "debit", "amount": 1, "reference_id": f"d{i}"})
    return acc


def test_default_pagination_and_latest_first(client, account_with_history):
    resp = client.get(f"/accounts/{account_with_history}/transactions")
    assert resp.status_code == 200
    body = resp.json()
    assert body["pagination"] == {"page": 1, "limit": 20, "total_records": 12, "total_pages": 1}
    refs = [t["reference_id"] for t in body["data"]]
    assert refs == ["d4", "d3", "d2", "d1", "d0", "c6", "c5", "c4", "c3", "c2", "c1", "c0"]
    stamps = [t["created_at"] for t in body["data"]]
    assert stamps == sorted(stamps, reverse=True)


def test_page_and_limit(client, account_with_history):
    resp = client.get(f"/accounts/{account_with_history}/transactions?page=2&limit=5")
    body = resp.json()
    assert body["pagination"] == {"page": 2, "limit": 5, "total_records": 12, "total_pages": 3}
    assert [t["reference_id"] for t in body["data"]] == ["c6", "c5", "c4", "c3", "c2"]

    last = client.get(f"/accounts/{account_with_history}/transactions?page=3&limit=5").json()
    assert [t["reference_id"] for t in last["data"]] == ["c1", "c0"]


def test_page_beyond_last_returns_empty(client, account_with_history):
    body = client.get(f"/accounts/{account_with_history}/transactions?page=99&limit=5").json()
    assert body["data"] == []
    assert body["pagination"]["total_pages"] == 3


@pytest.mark.parametrize("type_, expected", [("credit", 7), ("debit", 5)])
def test_filter_by_type(client, account_with_history, type_, expected):
    body = client.get(f"/accounts/{account_with_history}/transactions?type={type_}&limit=100").json()
    assert body["pagination"]["total_records"] == expected
    assert {t["type"] for t in body["data"]} == {type_}


def test_empty_history(client, make_account):
    body = client.get(f"/accounts/{make_account()}/transactions").json()
    assert body == {"data": [], "pagination": {"page": 1, "limit": 20, "total_records": 0, "total_pages": 0}}


@pytest.mark.parametrize(
    "query, code",
    [
        ("page=0", "INVALID_PAGINATION"),
        ("page=-1", "INVALID_PAGINATION"),
        ("page=abc", "INVALID_PAGINATION"),
        ("limit=0", "INVALID_PAGINATION"),
        ("limit=101", "INVALID_PAGINATION"),
        ("type=refund", "INVALID_TRANSACTION_TYPE"),
    ],
)
def test_invalid_query_params(client, make_account, query, code):
    resp = client.get(f"/accounts/{make_account()}/transactions?{query}")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == code
