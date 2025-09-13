# models.py
import uuid
from datetime import date
from typing import Optional

from sqlmodel import SQLModel, Field

from constants.constants import DB_SCHEMA


class Base(SQLModel):
    __table_args__ = {"schema": DB_SCHEMA}


class GoldPurchase(Base, table=True):
    __tablename__ = "gold_purchases"

    # frontend uses string id — use UUID4 string here
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True, index=True)

    grams: float
    amountPaid: float
    date: date  # FastAPI will accept ISO date strings and convert
    pricePerGram: float
    userId: Optional[str] = None  # optional, frontend may send or omit


# Request / update models
class GoldPurchaseCreate(SQLModel):
    grams: float
    amountPaid: float
    date: date
    pricePerGram: float
    userId: Optional[str] = None


class GoldPurchaseUpdate(SQLModel):
    grams: Optional[float] = None
    amountPaid: Optional[float] = None
    date: Optional[date] = None
    pricePerGram: Optional[float] = None
    userId: Optional[str] = None


# --- New: cached gold prices ---
class GoldPrice(Base, table=True):
    """
    Cached gold price per day and currency.
    Composite primary key: (date, currency).
    This allows storing price for multiple currencies per date.
    """
    __tablename__ = "gold_prices"

    # Primary key on date + currency to support per-currency caching
    fetch_date: date = Field(primary_key=True, index=True)
    currency: str = Field(primary_key=True, index=True, max_length=3)
    price_per_gram: float
