from __future__ import annotations

from datetime import datetime, date as date_cls, timezone
from typing import Optional, Union

from sqlalchemy import (
    String,
    Integer,
    Float,
    DateTime,
    Date,
    Enum,
    UniqueConstraint,
    ForeignKey,
    Boolean,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator
import enum


class Base(DeclarativeBase):
    pass


# --- Enums
class CryptoCurrency(str, enum.Enum):
    USDT = "USDT"
    USDC = "USDC"
    ETH = "ETH"
    BTC = "BTC"


class FiatCurrency(str, enum.Enum):
    EUR = "EUR"


# Deprecated: MarketType and TradeExecutionType removed in favor of explicit Spot vs Derivative models

class TradeSide(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"


# --- Currency union type for SQLAlchemy
CurrencyValue = Union[CryptoCurrency, FiatCurrency, str]


class CurrencyType(TypeDecorator):
    """Store a union of CryptoCurrency and FiatCurrency as an uppercase string.

    - Accepts CryptoCurrency, FiatCurrency, or string values on bind; validates membership.
    - Returns string values on read (e.g., "ETH", "EUR").
    """

    impl = String(10)
    cache_ok = True

    def process_bind_param(self, value: CurrencyValue, dialect):  # type: ignore[override]
        if value is None:
            return None
        if isinstance(value, (CryptoCurrency, FiatCurrency)):
            return value.value
        if isinstance(value, str):
            v = value.upper()
            if v in {c.value for c in CryptoCurrency} | {f.value for f in FiatCurrency}:
                return v
        raise ValueError(f"Invalid currency value: {value!r}")

    def process_result_value(self, value: Optional[str], dialect):  # type: ignore[override]
        return None if value is None else value


# --- Models
class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    api_key: Mapped[str] = mapped_column(String(255), nullable=False)
    api_secret: Mapped[str] = mapped_column(String(255), nullable=False)
    fiat_currency: Mapped[FiatCurrency] = mapped_column(Enum(FiatCurrency), nullable=False, default=FiatCurrency.EUR)

    # Backref to spot executions
    spot_executions: Mapped[list["SpotExecution"]] = relationship(
        back_populates="account",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    # Backref to derivative closed PnL rows
    derivative_closed_pnls: Mapped[list["DerivativeClosedPnl"]] = relationship(
        back_populates="account",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class HistoricalFiatPrice(Base):
    __tablename__ = "historical_fiat_prices"
    __table_args__ = (
        UniqueConstraint("coin", "fiat", "timestamp", name="uq_hfp_coin_fiat_ts"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    coin: Mapped[CryptoCurrency] = mapped_column(Enum(CryptoCurrency), nullable=False)
    fiat: Mapped[FiatCurrency] = mapped_column(Enum(FiatCurrency), nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    # Timestamp for the kline start (UTC). Use timezone-aware DateTime.
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class SpotExecution(Base):
    __tablename__ = "spot_executions"

    # execId serves as a unique identifier (use as primary key)
    exec_id: Mapped[str] = mapped_column("exec_id", String(100), primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    account: Mapped[Account] = relationship(back_populates="spot_executions")
    base: Mapped[str] = mapped_column(CurrencyType, nullable=False)
    quote: Mapped[str] = mapped_column(CurrencyType, nullable=False)
    side: Mapped[TradeSide] = mapped_column(Enum(TradeSide), nullable=False)
    qty: Mapped[float] = mapped_column(Float, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    fees: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    # Optional flag to indicate this execution was manually entered (not downloaded)
    is_manual: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")


class DerivativeClosedPnl(Base):
    __tablename__ = "derivative_closed_pnls"

    # Prefer unique ID from API if available; fallback to composite key string
    pnl_id: Mapped[str] = mapped_column("pnl_id", String(120), primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    account: Mapped[Account] = relationship(back_populates="derivative_closed_pnls")

    symbol: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    side: Mapped[TradeSide] = mapped_column(Enum(TradeSide), nullable=False)
    qty: Mapped[float] = mapped_column(Float, nullable=False)
    closed_pnl: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    fees: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    entry_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    exit_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
