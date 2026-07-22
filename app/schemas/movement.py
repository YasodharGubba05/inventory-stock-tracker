from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.product import MovementType
from app.schemas.pagination import PaginationMeta


class MovementCreate(BaseModel):
    movement_type: MovementType = Field(..., examples=["RESTOCK"])
    quantity: int = Field(
        ...,
        examples=[10],
        description="Unsigned magnitude for RESTOCK/SALE; signed delta for ADJUSTMENT",
    )
    reason: str | None = Field(default=None, examples=["Cycle count correction"])

    @model_validator(mode="after")
    def validate_quantity_and_reason(self) -> "MovementCreate":
        if self.movement_type == MovementType.ADJUSTMENT:
            if self.quantity == 0:
                raise ValueError("ADJUSTMENT quantity cannot be zero")
            if not self.reason or not self.reason.strip():
                raise ValueError("reason is required for ADJUSTMENT movements")
        else:
            if self.quantity <= 0:
                raise ValueError("quantity must be positive for RESTOCK and SALE")
            if self.reason is not None:
                raise ValueError("reason must not be provided for RESTOCK or SALE")
        return self


class MovementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    product_id: UUID
    movement_type: MovementType
    quantity_delta: int
    reason: str | None
    resulting_quantity: int
    sequence: int
    created_at: datetime


class MovementListResponse(BaseModel):
    items: list[MovementResponse]
    meta: PaginationMeta


class MovementSummaryItem(BaseModel):
    movement_type: MovementType
    count: int
    net_quantity: int


class MovementSummaryResponse(BaseModel):
    product_id: UUID
    from_date: datetime | None
    to_date: datetime | None
    summary: list[MovementSummaryItem]
