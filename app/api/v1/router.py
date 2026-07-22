from fastapi import APIRouter

from app.api.v1 import health, movements, products

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router, tags=["health"])
api_router.include_router(products.router, prefix="/products", tags=["products"])
api_router.include_router(movements.router, tags=["movements"])
