# Transaction Ledger API

A backend API for a simple transaction ledger: create accounts, post credit/debit
transactions, read balances and paginated transaction history, and transfer money
between accounts — with strong data-integrity guarantees.

**Stack:** Python 3.12+ · FastAPI · SQLAlchemy 2 · PostgreSQL 16 · Pytest · Docker Compose

| Document | Contents |
|---|---|
| [docs/API.md](docs/API.md) | Every endpoint, request/response examples, error codes |
| [docs/ASSUMPTIONS.md](docs/ASSUMPTIONS.md) | Design decisions and assumptions |
| `http://localhost:8000/docs` | Interactive Swagger UI (auto-generated OpenAPI) |

---

## Quick start (Docker — recommended)

Requires Docker Desktop.

```bash
docker compose up --build
```

- API: http://localhost:8000
- Swagger UI: http://localhost:8000/docs
- Postgres: `localhost:5433` (user/password/db: `ledger`/`ledger`/`ledger`)

Tables, constraints and triggers are created automatically on startup.

Stop with `Ctrl+C`; `docker compose down -v` also deletes the data volume.

## Run locally (without containerising the API)

Requires Python 3.12+ and Docker (only for Postgres).

```bash
docker compose up -d db

python -m venv .venv
# Windows:  .venv\Scripts\activate      macOS/Linux:  source .venv/bin/activate
pip install -r requirements-dev.txt

uvicorn app.main:app --reload
```

Defaults point at the Compose database. To use another Postgres instance, set
`DATABASE_URL` (see [.env.example](.env.example)), e.g.
`postgresql+psycopg://user:pass@host:5432/dbname`.

## Running tests

The tests run against a real PostgreSQL database (`ledger_test`, created automatically
by the Compose init script) because row locking, constraints and triggers are part of
what is being tested.

```bash
docker compose up -d db
pytest
```

50 tests cover: the balance examples from the brief, insufficient balance, duplicate
`reference_id` handling, validation errors, pagination/filtering/ordering, API- and
database-level immutability, transfer atomicity/rollback, and **concurrency**
(parallel debits never overdraw; parallel opposite transfers don't deadlock and
conserve money).

> If you created the Compose volume before `docker/init-test-db.sql` existed, run
> `docker compose down -v` once so the test database gets created.

---

## Endpoints at a glance

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/accounts` | Create account (balance starts at 0) |
| `GET` | `/accounts/{account_id}` | Get account |
| `GET` | `/accounts/{account_id}/balance` | Get current balance |
| `POST` | `/accounts/{account_id}/transactions` | Add credit/debit transaction |
| `GET` | `/accounts/{account_id}/transactions?type=&page=&limit=` | Transaction history (latest first) |
| `GET` | `/transactions/{transaction_id}` | Get a single transaction |
| `POST` | `/transfers` | **Bonus:** transfer between accounts |
| `GET` | `/health` | Health check |

Full details: [docs/API.md](docs/API.md).

## Project structure

```
app/
  main.py              FastAPI app, router + error-handler registration
  config.py            Environment-based settings
  database.py          Engine / session factory
  models.py            Tables, constraints, immutability triggers
  schemas.py           Request/response models (validation)
  errors.py            Domain errors + consistent error responses
  routers/             HTTP layer (accounts, transactions, transfers)
  services/            Business logic (locking, atomic writes, pagination)
tests/                 Pytest suite (runs against Postgres)
docs/                  API documentation and assumptions
docker/                Postgres init script (creates test DB)
```

Routers only parse HTTP input and delegate; all ledger rules live in `services/`.

## How data integrity is guaranteed

| Requirement | How |
|---|---|
| **Atomicity** | Transaction insert + balance update happen in one DB transaction; any error → rollback. Transfers write both legs + balances in one DB transaction. |
| **No overdraft, even under concurrency** | The account row is locked with `SELECT … FOR UPDATE` before checking the balance. Backed by `CHECK (balance >= 0)` in the database. |
| **Balance consistency** | Balance only changes inside the same DB transaction as its ledger row; rejected requests roll back. Tests assert balance = Σcredits − Σdebits. |
| **Duplicate protection** | `UNIQUE (account_id, reference_id)`; duplicate check happens after the lock, so concurrent retries return `409` and are never applied twice. |
| **Immutability** | No update/delete endpoints (`PUT/PATCH/DELETE /transactions/{id}` → `405`), **and** Postgres triggers reject any `UPDATE`/`DELETE` on `transactions` and `transfers`. |
| **No deadlocks in transfers** | Both accounts are locked in a deterministic order (sorted by ID). |
| **Exact money** | `NUMERIC(18,2)` in the DB, `Decimal` in Python, strings in JSON. |
| **Other constraints** | `CHECK (amount > 0)`, `CHECK (type IN ('credit','debit'))`, foreign keys with `ON DELETE RESTRICT`, non-blank account names. |
