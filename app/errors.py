"""Application errors and a single, consistent error response format:

    {"error": {"code": "SOME_CODE", "message": "Human readable", "details": ...}}
"""

import logging
import uuid
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("ledger")


class AppError(Exception):
    def __init__(self, status_code: int, code: str, message: str, details: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


class AccountNotFound(AppError):
    def __init__(self, account_id: uuid.UUID):
        super().__init__(
            status.HTTP_404_NOT_FOUND,
            "ACCOUNT_NOT_FOUND",
            f"Account {account_id} was not found",
            {"account_id": str(account_id)},
        )


class InvalidAccountId(AppError):
    def __init__(self, raw: str):
        super().__init__(
            status.HTTP_400_BAD_REQUEST,
            "INVALID_ACCOUNT_ID",
            "Account ID must be a valid UUID",
            {"account_id": raw},
        )


class InsufficientBalance(AppError):
    def __init__(self, account_id: uuid.UUID, balance, amount):
        super().__init__(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "INSUFFICIENT_BALANCE",
            "Account balance is insufficient for this debit",
            {"account_id": str(account_id), "balance": str(balance), "requested_amount": str(amount)},
        )


class DuplicateTransaction(AppError):
    def __init__(self, existing: dict):
        super().__init__(
            status.HTTP_409_CONFLICT,
            "DUPLICATE_TRANSACTION",
            "A transaction with this reference_id already exists for this account",
            {"existing_transaction": existing},
        )


def error_body(code: str, message: str, details: Any = None) -> dict:
    return {"error": {"code": code, "message": message, "details": details}}


def _field_name(loc: tuple) -> str:
    parts = [str(p) for p in loc[1:]] if len(loc) > 1 else [str(p) for p in loc]
    return ".".join(parts)


def _classify_validation(errors: list[dict]) -> tuple[str, str]:
    """Pick the most specific error code for a set of pydantic errors."""
    for err in errors:
        loc = err.get("loc", ())
        field = loc[-1] if loc else None
        if err.get("type") == "json_invalid":
            return "INVALID_REQUEST_BODY", "Request body is not valid JSON"
        if loc == ("body",):
            return "INVALID_REQUEST_BODY", "Request body is missing or not a JSON object"
        if loc and loc[0] == "query" and field in {"page", "limit"}:
            return "INVALID_PAGINATION", "Invalid pagination parameters"
        if field == "type":
            return "INVALID_TRANSACTION_TYPE", "Transaction type must be 'credit' or 'debit'"
        if field == "amount":
            return "INVALID_AMOUNT", "Amount must be a positive number with at most 2 decimal places"
        if field in {"from_account_id", "to_account_id"}:
            return "INVALID_ACCOUNT_ID", "Account ID must be a valid UUID"
    return "VALIDATION_ERROR", "Request validation failed"


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        return JSONResponse(status_code=exc.status_code, content=error_body(exc.code, exc.message, exc.details))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError):
        errors = exc.errors()
        code, message = _classify_validation(errors)
        details = [{"field": _field_name(tuple(e.get("loc", ()))), "message": e.get("msg")} for e in errors]
        return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content=error_body(code, message, details))

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException):
        codes = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(codes.get(exc.status_code, "HTTP_ERROR"), str(exc.detail)),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(IntegrityError)
    async def _integrity_error(_: Request, exc: IntegrityError):
        # Safety net: services translate expected violations themselves.
        logger.warning("Unhandled integrity error: %s", exc.orig)
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=error_body("CONFLICT", "The request conflicts with existing data"),
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):
        logger.exception("Unhandled error", exc_info=exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_body("INTERNAL_ERROR", "An unexpected error occurred"),
        )
