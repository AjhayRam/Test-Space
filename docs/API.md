# API Documentation

Base URL: `http://localhost:8000` · Interactive docs: `/docs` (Swagger UI), `/redoc`,
raw OpenAPI at `/openapi.json`.

All requests and responses are JSON. IDs are UUIDs. Timestamps are ISO-8601 UTC.

**Money** is accepted as a JSON number or string (`100`, `"100.50"`) with at most 2
decimal places, and is always **returned as a string** (`"100.50"`) to avoid
floating-point precision loss.

---

## Error format

Every error has the same shape:

```json
{
  "error": {
    "code": "INSUFFICIENT_BALANCE",
    "message": "Account balance is insufficient for this debit",
    "details": { "account_id": "…", "balance": "100.00", "requested_amount": "150" }
  }
}
```

| HTTP | `code` | When |
|---|---|---|
| 400 | `VALIDATION_ERROR` | Missing/invalid field, unknown field (e.g. `balance` on create) |
| 400 | `INVALID_REQUEST_BODY` | Body is not valid JSON / not an object |
| 400 | `INVALID_TRANSACTION_TYPE` | `type` missing or not `credit`/`debit` |
| 400 | `INVALID_AMOUNT` | `amount` missing, ≤ 0, non-numeric, or > 2 decimals |
| 400 | `INVALID_PAGINATION` | `page` < 1, `limit` < 1 or > 100, or non-integer |
| 400 | `INVALID_ACCOUNT_ID` | Account ID is not a valid UUID |
| 400 | `SAME_ACCOUNT_TRANSFER` | Transfer source = destination |
| 404 | `ACCOUNT_NOT_FOUND` | Account does not exist |
| 404 | `TRANSACTION_NOT_FOUND` | Transaction does not exist |
| 405 | `TRANSACTION_IMMUTABLE` | `PUT`/`PATCH`/`DELETE` on a transaction |
| 409 | `DUPLICATE_TRANSACTION` | `reference_id` already used on this account |
| 409 | `DUPLICATE_TRANSFER` | Transfer `reference_id` already used |
| 422 | `INSUFFICIENT_BALANCE` | Debit/transfer larger than the balance |
| 500 | `INTERNAL_ERROR` | Unexpected server error |

For validation errors, `details` lists each problem: `[{"field": "amount", "message": "…"}]`.

---

## 1. Create account

`POST /accounts`

| Field | Type | Rules |
|---|---|---|
| `name` | string | Required, 1–255 chars (trimmed) |

Any other field (including `balance`) is rejected with `400 VALIDATION_ERROR`.

```bash
curl -X POST http://localhost:8000/accounts \
  -H "Content-Type: application/json" -d '{"name": "Alice"}'
```

**201 Created**
```json
{
  "id": "abcb3e01-98d5-436f-b168-01f55bff9049",
  "name": "Alice",
  "balance": "0.00",
  "created_at": "2026-10-26T12:27:54.832060Z"
}
```

## 2. Get account

`GET /accounts/{account_id}` → **200** same shape as above. Errors: `400 INVALID_ACCOUNT_ID`, `404 ACCOUNT_NOT_FOUND`.

## 3. Get balance

`GET /accounts/{account_id}/balance`

**200 OK**
```json
{ "account_id": "abcb3e01-98d5-436f-b168-01f55bff9049", "balance": "70.00" }
```
Errors: `400 INVALID_ACCOUNT_ID`, `404 ACCOUNT_NOT_FOUND`.

## 4. Add transaction

`POST /accounts/{account_id}/transactions`

| Field | Type | Rules |
|---|---|---|
| `type` | string | Required: `credit` or `debit` |
| `amount` | number/string | Required, > 0, max 2 decimals |
| `reference_id` | string | Required, 1–100 chars, unique per account |
| `description` | string | Optional, ≤ 500 chars |

```bash
curl -X POST http://localhost:8000/accounts/{account_id}/transactions \
  -H "Content-Type: application/json" \
  -d '{"type": "credit", "amount": 100, "description": "Salary", "reference_id": "INV-1"}'
```

**201 Created**
```json
{
  "id": "b146859a-9483-4743-92ec-cef1315de5f7",
  "account_id": "abcb3e01-98d5-436f-b168-01f55bff9049",
  "type": "credit",
  "amount": "100.00",
  "description": "Salary",
  "reference_id": "INV-1",
  "transfer_id": null,
  "created_at": "2026-10-26T12:27:55.134259Z"
}
```

- **credit** adds to the balance, **debit** subtracts.
- A debit larger than the balance → **422 `INSUFFICIENT_BALANCE`**; nothing is recorded and the balance is unchanged.
- Same `reference_id` again on the same account → **409 `DUPLICATE_TRANSACTION`**; no new transaction, balance unchanged. The original transaction is returned in `details.existing_transaction` so a client retrying a request can recover it.
- The same `reference_id` on a *different* account is allowed.
- Errors: `400` (validation codes above), `404 ACCOUNT_NOT_FOUND`, `409`, `422`.

## 5. Transaction history

`GET /accounts/{account_id}/transactions`

| Query | Default | Rules |
|---|---|---|
| `type` | (both) | `credit` or `debit` |
| `page` | `1` | integer ≥ 1 |
| `limit` | `20` | integer 1–100 |

Sorted **latest first** by `created_at`.

```bash
curl "http://localhost:8000/accounts/{account_id}/transactions?type=debit&page=1&limit=10"
```

**200 OK**
```json
{
  "data": [
    {
      "id": "7e51e7f1-6d46-4459-ab2c-f9f3fd7fee9c",
      "account_id": "abcb3e01-98d5-436f-b168-01f55bff9049",
      "type": "debit",
      "amount": "30.00",
      "description": "Transfer to bb08da36-4d5f-4085-957f-54900f3b5133",
      "reference_id": "TRF-1",
      "transfer_id": "41a1db4d-26f3-4a40-ac8c-f2dbacd95aae",
      "created_at": "2026-10-26T12:27:55.232702Z"
    }
  ],
  "pagination": { "page": 1, "limit": 10, "total_records": 1, "total_pages": 1 }
}
```

A page beyond the last page returns `"data": []` with correct `pagination` metadata.
Errors: `400 INVALID_PAGINATION`, `400 INVALID_TRANSACTION_TYPE`, `400 INVALID_ACCOUNT_ID`, `404 ACCOUNT_NOT_FOUND`.

## 6. Get transaction

`GET /transactions/{transaction_id}` → **200** a single transaction, or `404 TRANSACTION_NOT_FOUND`.

`PUT`, `PATCH`, `DELETE /transactions/{transaction_id}` → **405 `TRANSACTION_IMMUTABLE`**.

## 7. Transfer (bonus)

`POST /transfers`

| Field | Type | Rules |
|---|---|---|
| `from_account_id` | UUID | Required, must exist |
| `to_account_id` | UUID | Required, must exist, ≠ `from_account_id` |
| `amount` | number/string | Required, > 0, max 2 decimals |
| `reference_id` | string | Required, unique across transfers |
| `description` | string | Optional |

```bash
curl -X POST http://localhost:8000/transfers \
  -H "Content-Type: application/json" \
  -d '{"from_account_id": "<A>", "to_account_id": "<B>", "amount": 30, "reference_id": "TRF-1"}'
```

**201 Created** (A: 100 → 70, B: 50 → 80)
```json
{
  "id": "41a1db4d-26f3-4a40-ac8c-f2dbacd95aae",
  "from_account_id": "<A>",
  "to_account_id": "<B>",
  "amount": "30.00",
  "description": null,
  "reference_id": "TRF-1",
  "created_at": "2026-10-26T12:27:55.231033Z",
  "debit_transaction":  { "type": "debit",  "account_id": "<A>", "amount": "30.00", "transfer_id": "41a1…", "...": "..." },
  "credit_transaction": { "type": "credit", "account_id": "<B>", "amount": "30.00", "transfer_id": "41a1…", "...": "..." },
  "from_account_balance": "70.00",
  "to_account_balance": "80.00"
}
```

The debit, the credit and both balance updates commit together or not at all.
Errors: `400` validation / `SAME_ACCOUNT_TRANSFER`, `404 ACCOUNT_NOT_FOUND`,
`409 DUPLICATE_TRANSFER` / `DUPLICATE_TRANSACTION`, `422 INSUFFICIENT_BALANCE`.

## 8. Health

`GET /health` → `{"status": "ok"}`
