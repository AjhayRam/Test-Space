from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import ErrorResponse, TransferCreate, TransferOut
from app.services import transfers as transfer_service

router = APIRouter(prefix="/transfers", tags=["Transfers"])


@router.post(
    "",
    response_model=TransferOut,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid request / same account"},
        404: {"model": ErrorResponse, "description": "Source or destination account not found"},
        409: {"model": ErrorResponse, "description": "Duplicate reference_id"},
        422: {"model": ErrorResponse, "description": "Insufficient balance"},
    },
)
def create_transfer(payload: TransferCreate, db: Annotated[Session, Depends(get_db)]):
    """Move money between two accounts. All-or-nothing: no partial transfers."""
    return transfer_service.create_transfer(db, payload)
