"""Environment-backed application settings.

The defaults deliberately keep the project local and paper-only.  A live
execution adapter is outside the scope of this package.
"""

from functools import lru_cache
from decimal import Decimal
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings, overridable with environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="",
        extra="ignore",
    )

    database_url: str = "sqlite:///./paper_trading.db"
    paper_only: bool = True
    initial_cash: Decimal = Field(default=Decimal("10000"), gt=0)

    max_order_exposure: Decimal = Field(default=Decimal("250"), gt=0)
    max_market_exposure: Decimal = Field(default=Decimal("1000"), gt=0)
    max_total_exposure: Decimal = Field(default=Decimal("5000"), gt=0)
    max_daily_loss: Decimal = Field(default=Decimal("100"), gt=0)
    market_page_size: int = Field(default=100, ge=1, le=1000)
    market_pages: int = Field(default=5, ge=1, le=100)
    worker_refresh_seconds: int = Field(default=300, ge=10)
    worker_reconnect_seconds: int = Field(default=10, ge=1)
    max_market_data_age_seconds: int = Field(default=30, ge=1)
    worker_stream_market_limit: int = Field(default=25, ge=1, le=100)
    worker_require_crypto: bool = True
    min_market_duration_minutes: int = Field(default=10, ge=1)
    max_market_duration_minutes: int = Field(default=20, ge=1)
    m1_min_price: Decimal = Field(default=Decimal("0.95"), gt=0, lt=1)
    m1_max_price: Decimal = Field(default=Decimal("1.00"), gt=0, le=1)
    m1_entry_window_seconds: int = Field(default=120, ge=5, le=1200)
    market_keywords: str = "bitcoin,btc,ethereum,eth,solana,sol,xrp,doge,dogecoin,bnb,hype,zec,crypto"
    # Auto-guard for strategy-opened positions: stop = entry - offset (0 disables).
    auto_stop_loss_offset: Decimal = Field(default=Decimal("0.05"), ge=0, lt=1)
    auto_take_profit_offset: Decimal = Field(default=Decimal("0"), ge=0, lt=1)
    paper_queue_model: Literal["optimistic", "baseline", "conservative"] = "baseline"
    account_data_base_url: str = "https://data-api.polymarket.com"
    account_positions_path: str = "/positions"
    account_activity_path: str = "/activity"


@lru_cache
def get_settings() -> Settings:
    """Return the process settings singleton."""

    return Settings()
