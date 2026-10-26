# Assumptions & Design Decisions

## Domain

1. **Single currency.** All accounts share one implicit currency; no currency field or conversion.
2. **Money precision is 2 decimal places.** Amounts with more decimals are rejected (not rounded). Stored as `NUMERIC(18,2)`.
3. **Balances can never go negative.** No overdraft facility; a debit equal to the full balance is allowed.
4. **The stored balance is a materialised value** of the ledger, updated in the same DB transaction as each ledger row. It is not recomputed from history on every read (that would be slow), but it always equals Σcredits − Σdebits because both are written atomically.
5. **`description` is optional** for transactions (the brief lists it as a field but not as a required validation). Max 500 chars.
6. **`reference_id` is trimmed, 1–100 chars, case-sensitive.** Unique per account, as required; the same value may be reused on other accounts.
7. **Duplicate `reference_id` → `409 Conflict`**, regardless of whether the payload matches the original. The original transaction is returned in the error details so a retrying client can recover it. Duplicate detection runs *before* the balance check, so a retried debit reports "duplicate", not "insufficient balance".
8. **Account names need not be unique** (two people can be called "Alice"); names are trimmed and must not be blank.
9. **Accounts cannot be updated or deleted** — not required, and deleting an account with ledger history would break integrity (FKs use `ON DELETE RESTRICT`).

## API behaviour

10. **Transactions are created under the account path** (`POST /accounts/{id}/transactions`), so the account ID comes from the URL rather than the body.
11. **Unknown fields are rejected** (e.g. sending `balance` when creating an account returns `400`), rather than silently ignored, so clients learn they can't set it.
12. **Malformed IDs → `400 INVALID_ACCOUNT_ID`; well-formed but unknown IDs → `404 ACCOUNT_NOT_FOUND`.**
13. **Validation errors use `400`**, with specific codes (`INVALID_AMOUNT`, `INVALID_TRANSACTION_TYPE`, `INVALID_PAGINATION`, …). **Business-rule rejections** (insufficient balance) use `422`. **Conflicts** (duplicates) use `409`.
14. **Pagination:** `page` defaults to 1, `limit` defaults to 20 with a max of 100 (larger values are rejected, not clamped). A page past the end returns an empty list with accurate metadata. `total_pages` is `0` when there are no records.
15. **Ordering:** latest first by `created_at`, with `id` as a tie-breaker for a stable order. `created_at` uses `clock_timestamp()` so rows written within one DB transaction still get distinct times.
16. **Money is serialised as strings** in JSON to avoid float precision issues; inputs accept numbers or strings.

## Transfers (bonus)

17. A transfer is stored as a `transfers` record **plus two ordinary ledger transactions** (a debit on the source, a credit on the destination) linked via `transfer_id`. They therefore show up in each account's history and count towards the balance like any other transaction.
18. **Transfer `reference_id` is unique across all transfers**, and is also used as the `reference_id` of both legs — so it must not already be used by a transaction on either account (otherwise `409`, and nothing is written).
19. If no description is given, legs get `"Transfer to <id>"` / `"Transfer from <id>"`.

## Technical

20. **PostgreSQL** was chosen for real transactions, row-level locks, CHECK/UNIQUE/FK constraints and triggers. SQLite was rejected because it can't do row-level locking.
21. **Schema is created at startup** with SQLAlchemy `create_all` (plus the trigger DDL) for easy local setup. A production system would use versioned migrations (e.g. Alembic). Disable with `AUTO_CREATE_TABLES=false`.
22. **No authentication/authorisation** — out of scope for the brief.
23. **Concurrency model:** pessimistic row locking (`SELECT … FOR UPDATE`) at the default `READ COMMITTED` isolation level. Transfers lock both accounts in sorted-ID order to prevent deadlocks.
