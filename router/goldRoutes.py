# router/goldRoutes.py
import logging
import os
from datetime import date as dt_date
from datetime import datetime
from typing import List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, status, Response
from fastapi import Query
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from db.config_db import get_session
from db.models import GoldPurchase, GoldPurchaseCreate, GoldPurchaseUpdate, GoldPrice
from constants.schemas import PricePerGramResponse

router = APIRouter(tags=["gold"])


# --- Gold Purchases CRUD --- #

@router.get("/gold-purchases", response_model=List[GoldPurchase])
async def list_purchases(userId: Optional[str] = None, session: AsyncSession = Depends(get_session), ):
    """
    GET /api/gold-purchases?userId=abc (optional)
    """
    q = select(GoldPurchase)
    if userId:
        q = q.where(GoldPurchase.userId == userId)
    result = await session.exec(q)
    return result.all()


@router.post("/gold-purchases", response_model=GoldPurchase, status_code=status.HTTP_201_CREATED)
async def create_purchase(payload: GoldPurchaseCreate, session: AsyncSession = Depends(get_session), ):
    gp = GoldPurchase(**payload.dict())
    session.add(gp)
    await session.commit()
    await session.refresh(gp)
    return gp


@router.put("/gold-purchases/{purchase_id}", response_model=GoldPurchase)
async def update_purchase(purchase_id: str, payload: GoldPurchaseUpdate,
        session: AsyncSession = Depends(get_session), ):
    gp = await session.get(GoldPurchase, purchase_id)
    if not gp:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Purchase not found")

    update_data = payload.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(gp, key, value)

    session.add(gp)
    await session.commit()
    await session.refresh(gp)
    return gp


@router.delete("/gold-purchases/{purchase_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_purchase(purchase_id: str, session: AsyncSession = Depends(get_session), ):
    gp = await session.get(GoldPurchase, purchase_id)
    if not gp:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Purchase not found")

    await session.delete(gp)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------
# Price endpoint (DB-first, then upstream with multiple API-key fallbacks)
# ---------------------------------------------------------------------
logger = logging.getLogger(__name__)


@router.get("/gold-price", response_model=PricePerGramResponse, response_model_by_alias=True,
    summary="Current gold price per gram (24k)", )
async def get_current_gold_price(currency: Optional[str] = Query("INR", min_length=3, max_length=3),
        session: AsyncSession = Depends(get_session), ):
    """
    Returns cached price from DB if available for today's date and currency.
    Otherwise falls back to external GoldAPI using multiple keys and stores the successful result.
    """
    currency = currency.upper()
    today = dt_date.today()

    # 1) Try DB cache first
    q = select(GoldPrice).where(GoldPrice.fetch_date == today).where(GoldPrice.currency == currency)
    result = await session.exec(q)
    cached = result.one_or_none()
    if cached:
        # Return cached value (aliasing handled by Pydantic schema)
        return PricePerGramResponse(price_per_gram=float(cached.price_per_gram))

    # 2) No cached value -> call upstream (existing logic)
    api_keys: List[Optional[str]] = [os.getenv("GOLDAPI_API_KEY"), os.getenv("GOLDAPI_API_KEY_2"),
        os.getenv("GOLDAPI_API_KEY_3"), os.getenv("GOLDAPI_API_KEY_4"), ]
    api_keys = [k for k in api_keys if k]

    if not api_keys:
        logger.error("No GoldAPI keys configured (GOLDAPI_API_KEY* env vars missing)")
        raise HTTPException(status_code=500, detail="Server misconfiguration: no API keys available")

    url = f"https://www.goldapi.io/api/XAU/{currency}"
    headers_template = {"Content-Type": "application/json"}
    price_key = "price_gram_24k"

    for idx, api_key in enumerate(api_keys, start=1):
        headers = {**headers_template, "x-access-token": api_key}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
                data = resp.json()
        except httpx.RequestError as exc:
            logger.warning("GoldAPI request error with key #%d: %s", idx, exc)
            continue
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            text_preview = exc.response.text[:200] if exc.response.text else ""
            logger.warning("GoldAPI returned status %s for key #%d. Response preview: %s", status_code, idx,
                text_preview)
            continue
        except Exception as exc:
            logger.exception("Unexpected error using GoldAPI key #%d: %s", idx, exc)
            continue

        if not isinstance(data, dict) or price_key not in data:
            logger.warning("GoldAPI payload missing '%s' with key #%d; payload: %s", price_key, idx, str(data)[:200])
            continue

        try:
            price_val = float(data[price_key])
        except (TypeError, ValueError) as exc:
            logger.warning("Invalid '%s' value from GoldAPI with key #%d: %s", price_key, idx, exc)
            continue

        # Persist to DB for future requests (upsert behaviour)
        try:
            gp = GoldPrice(fetch_date=today, currency=currency, price_per_gram=price_val)
            session.add(gp)
            await session.commit()  # no need to await session.refresh(gp) for this small cache but ok to do if you prefer
        except Exception:
            # Non-fatal: log but still return the value
            logger.exception("Failed to persist gold price for %s %s to DB", currency, today)

        return PricePerGramResponse(price_per_gram=price_val)

    logger.error("All GoldAPI keys exhausted or failed for URL=%s", url)
    raise HTTPException(status_code=503, detail="Upstream gold price service unavailable")


# place this function in router/goldRoutes.py along with your other endpoints
@router.get("/gold-price/historical", response_model=PricePerGramResponse, response_model_by_alias=True)
async def get_historical_price(date: str, currency: Optional[str] = Query("INR", min_length=3, max_length=3),
        session: AsyncSession = Depends(get_session), ):
    """
    Returns pricePerGram for the requested date (YYYY-MM-DD) and currency.
    1) Try DB cache first (gold_prices table).
    2) If missing, call upstream GoldAPI historical endpoint (multiple keys fallback).
    3) Persist successful result to DB and return it.
    """
    currency = currency.upper()

    # validate/parse date param (expecting YYYY-MM-DD)
    try:
        target_date_obj = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid date format; use YYYY-MM-DD")

    # 1) DB lookup (note: model field name below assumes `fetch_date` in GoldPrice)
    q = select(GoldPrice).where(GoldPrice.fetch_date == target_date_obj).where(GoldPrice.currency == currency)
    result = await session.exec(q)
    cached = result.one_or_none()
    if cached:
        return PricePerGramResponse(price_per_gram=float(cached.price_per_gram))

    # 2) Upstream: try GoldAPI historical endpoint with multiple keys
    api_keys: List[Optional[str]] = [os.getenv("GOLDAPI_API_KEY"), os.getenv("GOLDAPI_API_KEY_2"),
        os.getenv("GOLDAPI_API_KEY_3"), os.getenv("GOLDAPI_API_KEY_4"), ]
    api_keys = [k for k in api_keys if k]
    if not api_keys:
        logger.error("No GoldAPI keys configured (GOLDAPI_API_KEY* env vars missing)")
        raise HTTPException(status_code=500, detail="Server misconfiguration: no API keys available")

    # GoldAPI historical expects YYYYMMDD appended (example: /api/XAU/INR/20250508)
    ymd = target_date_obj.strftime("%Y%m%d")
    url = f"https://www.goldapi.io/api/XAU/{currency}/{ymd}"
    headers_template = {"Content-Type": "application/json"}
    price_key = "price_gram_24k"

    for idx, api_key in enumerate(api_keys, start=1):
        headers = {**headers_template, "x-access-token": api_key}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
                data = resp.json()
        except httpx.RequestError as exc:
            logger.warning("GoldAPI request error (historical) with key #%d: %s", idx, exc)
            continue
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            text_preview = exc.response.text[:200] if exc.response.text else ""
            logger.warning("GoldAPI historical returned status %s for key #%d. Response preview: %s", status_code, idx,
                text_preview)
            continue
        except Exception as exc:
            logger.exception("Unexpected error using GoldAPI key #%d (historical): %s", idx, exc)
            continue

        # verify payload contains expected price key
        if not isinstance(data, dict) or price_key not in data:
            logger.warning("GoldAPI historical payload missing '%s' with key #%d; payload: %s", price_key, idx,
                           str(data)[:200])
            continue

        try:
            price_val = float(data[price_key])
        except (TypeError, ValueError) as exc:
            logger.warning("Invalid '%s' value from GoldAPI historical with key #%d: %s", price_key, idx, exc)
            continue

        # Persist to DB for future requests (non-fatal)
        try:
            gp = GoldPrice(fetch_date=target_date_obj, currency=currency, price_per_gram=price_val)
            session.add(gp)
            await session.commit()
        except Exception:
            logger.exception("Failed to persist historical gold price for %s %s to DB", currency, target_date_obj)

        return PricePerGramResponse(price_per_gram=price_val)

    # All keys tried and failed
    logger.error("All GoldAPI historical keys exhausted or failed for URL=%s", url)
    raise HTTPException(status_code=503, detail="Upstream historical gold price service unavailable")
