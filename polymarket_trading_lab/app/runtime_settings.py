"""Dashboard-editable runtime settings.

The process-wide ``Settings`` singleton is mutated in place so the API and the
worker (which share it) see changes immediately.  Overrides are persisted in
``app_settings`` and re-applied at startup.  Secrets and the paper-only flag
are deliberately not editable here.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .models import AppSetting

# name -> (group, label, help, applies)
EDITABLE: dict[str, tuple[str, str, str, str]] = {
    "max_order_exposure": ("Risk limits", "Max per order ($)", "Largest single order, price × shares. Also the M1 order size cap.", "instant"),
    "max_market_exposure": ("Risk limits", "Max per market ($)", "Total open exposure allowed in one market.", "instant"),
    "max_total_exposure": ("Risk limits", "Max total exposure ($)", "Total open exposure across all markets.", "instant"),
    "max_daily_loss": ("Risk limits", "Max daily loss ($)", "New buys are blocked once today's realized loss exceeds this.", "instant"),
    "auto_stop_loss_offset": ("Exits", "Auto stop loss (¢ below entry)", "Applied to strategy-opened positions. 0 disables. 0.05 = 5¢.", "instant"),
    "auto_take_profit_offset": ("Exits", "Auto take profit (¢ above entry)", "0 disables.", "instant"),
    "m1_min_price": ("M1 strategy", "Min bid to buy", "Strategy buys only when the bid is above this.", "instant"),
    "m1_max_price": ("M1 strategy", "Max bid to buy", "…and at or below this.", "instant"),
    "m1_entry_window_seconds": ("M1 strategy", "Entry window (seconds before end)", "Only trade in the last N seconds of a market.", "instant"),
    "max_market_data_age_seconds": ("M1 strategy", "Max quote age (s)", "Ignore books older than this.", "instant"),
    "paper_queue_model": ("M1 strategy", "Queue model", "optimistic / baseline / conservative fill assumptions.", "new orders"),
    "worker_require_crypto": ("Market selection", "Filter by keywords & duration", "Off = trade every market Polymarket returns.", "next refresh"),
    "market_keywords": ("Market selection", "Keywords (comma separated)", "A market is tracked if its title/slug contains one of these words.", "next refresh"),
    "min_market_duration_minutes": ("Market selection", "Min market length (min)", "Skip shorter markets.", "next refresh"),
    "max_market_duration_minutes": ("Market selection", "Max market length (min)", "Skip longer markets.", "next refresh"),
    "worker_stream_market_limit": ("Market selection", "Max markets streamed", "How many markets get live prices at once (1–100).", "worker restart"),
    "market_page_size": ("Data feed", "Markets per page", "Polymarket discovery page size.", "next refresh"),
    "market_pages": ("Data feed", "Pages to scan", "How many discovery pages to read.", "next refresh"),
    "worker_refresh_seconds": ("Data feed", "Market refresh (s)", "How often the market list is re-discovered.", "worker restart"),
    "worker_reconnect_seconds": ("Data feed", "Reconnect delay (s)", "Wait after a feed error before retrying.", "worker restart"),
}


def _text(value: object) -> str:
    return str(value).lower() if isinstance(value, bool) else str(value)


def describe(settings: Settings | None = None) -> list[dict[str, object]]:
    settings = settings or get_settings()
    out = []
    for name, (group, label, help_text, applies) in EDITABLE.items():
        value = getattr(settings, name)
        field = Settings.model_fields[name]
        kind = "bool" if isinstance(value, bool) else "number" if isinstance(value, (int, Decimal)) else "text"
        out.append({
            "key": name, "group": group, "label": label, "help": help_text, "applies": applies,
            "type": kind, "value": _text(value), "default": _text(field.default),
            **({"choices": ["optimistic", "baseline", "conservative"]} if name == "paper_queue_model" else {}),
        })
    return out


def apply_changes(session: Session, changes: dict[str, object], settings: Settings | None = None) -> None:
    """Validate and apply changes; raises ValueError (nothing changes) if invalid."""

    settings = settings or get_settings()
    unknown = set(changes) - set(EDITABLE)
    if unknown:
        raise ValueError(f"not editable: {', '.join(sorted(unknown))}")
    candidate = Settings.model_validate({**settings.model_dump(), **changes})  # raises on bad values
    if candidate.m1_min_price >= candidate.m1_max_price:
        raise ValueError("M1 min bid must be below max bid")
    if candidate.min_market_duration_minutes > candidate.max_market_duration_minutes:
        raise ValueError("min market length must not exceed max length")
    for name in changes:
        new = getattr(candidate, name)
        setattr(settings, name, new)
        row = session.get(AppSetting, name)
        if row is None:
            session.add(AppSetting(key=name, value=_text(new)))
        else:
            row.value = _text(new)
    session.flush()


def reset_all(session: Session, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    for name in EDITABLE:
        setattr(settings, name, Settings.model_fields[name].default)
    for row in session.scalars(select(AppSetting)):
        session.delete(row)
    session.flush()


def load_overrides(session: Session, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    stored = {row.key: row.value for row in session.scalars(select(AppSetting)) if row.key in EDITABLE}
    if stored:
        try:
            apply_changes(session, stored, settings)
        except ValueError:
            pass  # ignore a stale/invalid stored override; defaults stay in force
