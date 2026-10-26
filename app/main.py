import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.database import engine
from app.errors import register_exception_handlers
from app.models import Base
from app.routers import accounts, transactions, transfers

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.auto_create_tables:
        Base.metadata.create_all(engine)
    yield


app = FastAPI(
    title="Transaction Ledger API",
    version="1.0.0",
    description="Accounts, immutable credit/debit transactions, balances, history and transfers.",
    lifespan=lifespan,
)

register_exception_handlers(app)

app.include_router(accounts.router)
app.include_router(transactions.router)
app.include_router(transfers.router)


@app.get("/health", tags=["Health"])
def health():
    return {"status": "ok"}
