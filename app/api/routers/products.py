from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import ProductIn, ProductOut
from app.db import get_session
from app.models import Product
from app.services.qr import product_link, qr_png

router = APIRouter(prefix="/products", tags=["products"])


@router.get("", response_model=list[ProductOut])
async def list_products(session: AsyncSession = Depends(get_session)):
    return (await session.scalars(select(Product).order_by(Product.id))).all()


@router.post("", response_model=ProductOut, status_code=201)
async def create_product(data: ProductIn, session: AsyncSession = Depends(get_session)):
    product = Product(**data.model_dump())
    session.add(product)
    await session.commit()
    return product


@router.put("/{product_id}", response_model=ProductOut)
async def update_product(product_id: int, data: ProductIn, session: AsyncSession = Depends(get_session)):
    product = await session.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    for key, value in data.model_dump().items():
        setattr(product, key, value)
    await session.commit()
    return product


@router.get("/{product_id}/qr.png", response_class=Response)
async def product_qr(product_id: int, session: AsyncSession = Depends(get_session)):
    """QR-код для упаковки: ведёт в бота, который поблагодарит за покупку этого товара."""
    product = await session.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return Response(qr_png(await product_link(product.qr_token)), media_type="image/png")


@router.delete("/{product_id}", status_code=204)
async def delete_product(product_id: int, session: AsyncSession = Depends(get_session)):
    product = await session.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    await session.delete(product)
    await session.commit()
