from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ProductCreate(BaseModel):
    sku: str = Field(..., min_length=1, max_length=64, examples=["SKU-001"])
    name: str = Field(..., min_length=1, max_length=255, examples=["Widget Pro"])
    quantity_on_hand: int = Field(default=0, ge=0, examples=[0])


class ProductUpdate(BaseModel):
    sku: str | None = Field(default=None, min_length=1, max_length=64, examples=["SKU-001-NEW"])
    name: str | None = Field(default=None, min_length=1, max_length=255, examples=["Widget Pro v2"])
    version: int = Field(..., ge=1, examples=[1], description="Expected version for optimistic locking")


class ProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    sku: str
    name: str
    quantity_on_hand: int
    version: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


from app.schemas.pagination import PaginationMeta


class ProductListResponse(BaseModel):
    items: list[ProductResponse]
    meta: PaginationMeta
