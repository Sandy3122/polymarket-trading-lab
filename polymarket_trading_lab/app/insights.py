"""Rule-based, transparent buy/wait/avoid insights for live markets.

This is *not* a price predictor.  It checks whether a market fits the M1
setup (near-certain favourite, close to the end, tight spread, real depth,
price not weakening) and spells out the risk/reward of buying it.  A market
price already is the crowd's probability, so no rule here proves an edge.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from .config import Settings
from .live import Quote

MAX_SPREAD = Decimal("0.04")
GOOD_SPREAD = Decimal("0.02")
MIN_DEPTH = Decimal("20")
GOOD_DEPTH = Decimal("100")
STALE = timedelta(seconds=30)
LAST_SECONDS = 10


def _f(value: Decimal | float | None, places: int = 4) -> float | None:
    return None if value is None else round(float(value), places)


def momentum(ticks: list[Quote], token: str, seconds: int = 60) -> float | None:
    """Change in the token's bid over roughly the last ``seconds`` (None if too little history)."""

    series = [(t.observed_at, t.bid(token)) for t in ticks if t.bid(token) is not None]
    if len(series) < 2:
        return None
    last_time, last_bid = series[-1]
    cutoff = last_time - timedelta(seconds=seconds)
    past = [item for item in series if item[0] <= cutoff]
    if past:
        base = past[-1][1]
    elif (last_time - series[0][0]).total_seconds() >= seconds / 2:
        base = series[0][1]
    else:
        return None
    return float(last_bid - base)


def price_range(ticks: list[Quote], token: str, seconds: int = 120) -> float | None:
    series = [(t.observed_at, t.bid(token)) for t in ticks if t.bid(token) is not None]
    if len(series) < 2:
        return None
    cutoff = series[-1][0] - timedelta(seconds=seconds)
    values = [float(bid) for at, bid in series if at >= cutoff]
    return max(values) - min(values) if len(values) >= 2 else None


def _mmss(seconds: float) -> str:
    m, sec = divmod(max(0, int(seconds)), 60)
    return f"{m}m {sec:02d}s"


def build_checks(
    seconds_left: float,
    age: timedelta,
    bid: Decimal | None,
    spread: Decimal | None,
    depth: Decimal,
    change: float | None,
    rng: float | None,
    s: Settings,
) -> tuple[list[dict[str, Any]], list[str]]:
    """The individual tests behind the verdict, plus what would have to change to get a BUY."""

    checks: list[dict[str, Any]] = []
    steps: list[str] = []
    window = s.m1_entry_window_seconds

    def add(name: str, status: str, detail: str, step: str | None = None, info: bool = False) -> None:
        checks.append({"name": name, "status": status, "detail": detail, "info": info})
        if step and status != "pass":
            steps.append(step)

    if seconds_left <= 0:
        add("Timing", "fail", "The market has ended.")
    elif seconds_left > window:
        add("Timing", "warn", f"Entry window opens in {_mmss(seconds_left - window)} (last {window}s).", f"Wait {_mmss(seconds_left - window)} for the entry window.")
    elif seconds_left < LAST_SECONDS:
        add("Timing", "fail", f"Only {int(seconds_left)}s left — orders may not fill.")
    else:
        add("Timing", "pass", f"{_mmss(seconds_left)} left — inside the entry window.")

    add("Fresh data", "pass" if age <= STALE else "fail",
        f"Last price {int(age.total_seconds())}s ago." , "Wait for fresh price data." if age > STALE else None)

    if bid is None:
        add("Near-certain favourite", "fail", "No bid on the favourite side.")
    elif s.m1_min_price < bid <= s.m1_max_price:
        add("Near-certain favourite", "pass", f"Bid {float(bid):.2f} is inside {float(s.m1_min_price):.2f}–{float(s.m1_max_price):.2f}.")
    else:
        need = float(s.m1_min_price - bid) * 100
        add("Near-certain favourite", "fail", f"Bid {float(bid):.2f} is outside {float(s.m1_min_price):.2f}–{float(s.m1_max_price):.2f} — outcome not near-certain.",
            f"Favourite bid must rise above {float(s.m1_min_price):.2f} (needs +{need:.0f}¢)." if need > 0 else None)

    if spread is None:
        add("Spread", "fail", "No ask available.")
    elif spread <= GOOD_SPREAD:
        add("Spread", "pass", f"{float(spread)*100:.0f}¢ — cheap to enter.")
    elif spread <= MAX_SPREAD:
        add("Spread", "warn", f"{float(spread)*100:.0f}¢ — you lose this the moment you buy.")
    else:
        add("Spread", "fail", f"{float(spread)*100:.0f}¢ is too wide.", f"Spread must narrow below {float(MAX_SPREAD)*100:.0f}¢.")

    if depth >= GOOD_DEPTH:
        add("Depth", "pass", f"{float(depth):.0f} shares bid — easy to exit.")
    elif depth >= MIN_DEPTH:
        add("Depth", "warn", f"{float(depth):.0f} shares bid — okay for small size.")
    else:
        add("Depth", "fail", f"Only {float(depth):.0f} shares bid — thin book.", f"Needs at least {float(MIN_DEPTH):.0f} shares bid.")

    if change is None:
        add("Momentum", "warn", "Not enough history yet (needs ~30 s of ticks).")
    elif change <= -0.03:
        add("Momentum", "fail", f"Fell {abs(change)*100:.0f}¢ in the last minute — weakening.", "Wait for the price to stop falling.")
    elif change < 0:
        add("Momentum", "warn", f"Slipping {change*100:+.0f}¢ in 60 s.")
    else:
        add("Momentum", "pass", f"{change*100:+.0f}¢ in 60 s — steady or rising.")

    if rng is not None:
        add("Choppiness", "pass" if rng <= 0.03 else "warn" if rng <= 0.08 else "fail",
            f"Price moved {rng*100:.0f}¢ in the last 2 min." + (" Jumpy — stops can fill far below your level." if rng > 0.05 else ""), info=True)
    return checks, steps


def _verdict(
    seconds_left: float,
    age: timedelta,
    bid: Decimal | None,
    spread: Decimal | None,
    depth: Decimal,
    change: float | None,
    s: Settings,
) -> tuple[str, int, list[str]]:
    reasons: list[str] = []
    if seconds_left <= 0:
        return "AVOID", 0, ["This market has ended."]
    if age > STALE:
        return "AVOID", 0, [f"Price data is {int(age.total_seconds())}s old — wait for fresh data."]
    if bid is None or spread is None:
        return "AVOID", 0, ["No usable bid/ask on the favourite side."]
    if spread > MAX_SPREAD:
        return "AVOID", 10, [f"Spread is {float(spread)*100:.0f}¢: you would lose that much the moment you buy."]
    window = s.m1_entry_window_seconds
    if seconds_left > window:
        m, sec = divmod(int(seconds_left - window), 60)
        reasons.append(f"Too early: the M1 entry window opens in {m}m {sec:02d}s (last {window}s of the market).")
        return "WAIT", 20, reasons
    if seconds_left < LAST_SECONDS:
        return "WAIT", 25, [f"Only {int(seconds_left)}s left — an order may not get filled before the market ends."]
    if not (s.m1_min_price < bid <= s.m1_max_price):
        return "WAIT", 30, [
            f"Favourite bid is {float(bid):.2f}, outside M1's {float(s.m1_min_price):.2f}–{float(s.m1_max_price):.2f} range: "
            "the outcome is not near-certain yet, so the risk is much bigger than the 1–5¢ you could gain."
        ]
    score = 55
    if depth < MIN_DEPTH:
        return "WAIT", 35, [f"Only {float(depth):.0f} shares are bid — thin book, hard to exit."]
    reasons.append("Inside the M1 entry window with a near-certain favourite.")
    if bid >= Decimal("0.97"):
        score += 15
    if spread <= GOOD_SPREAD:
        score += 10
        reasons.append(f"Tight spread ({float(spread)*100:.0f}¢).")
    else:
        reasons.append(f"Spread is {float(spread)*100:.0f}¢ — acceptable but it costs you.")
    if depth >= GOOD_DEPTH:
        score += 10
        reasons.append(f"Good depth ({float(depth):.0f} shares bid).")
    if change is not None:
        if change <= -0.03:
            return "WAIT", 40, reasons + [f"Favourite fell {abs(change)*100:.0f}¢ in the last minute — it is weakening; wait for it to stabilise."]
        if change < 0:
            score -= 5
            reasons.append(f"Slightly weakening ({change*100:+.0f}¢ in 60s).")
        elif change > 0:
            score += 5
            reasons.append(f"Strengthening ({change*100:+.0f}¢ in 60s).")
        else:
            reasons.append("Price steady over the last minute.")
    return "BUY", max(0, min(100, score)), reasons


def analyze(
    *,
    market_id: int,
    question: str,
    end_time: datetime,
    now: datetime,
    quote: Quote,
    ticks: list[Quote],
    settings: Settings,
    equity: Decimal,
) -> dict[str, Any]:
    token = "YES" if (quote.yes_bid or Decimal(0)) >= (quote.no_bid or Decimal(0)) else "NO"
    bid, ask = quote.bid(token), quote.ask(token)
    spread = ask - bid if bid is not None and ask is not None else None
    depth = quote.yes_bid_size if token == "YES" else quote.no_bid_size
    seconds_left = (end_time - now).total_seconds()
    change = momentum(ticks, token)
    verdict, score, reasons = _verdict(seconds_left, now - quote.observed_at, bid, spread, depth, change, settings)

    rng = price_range(ticks, token)
    checks, next_steps = build_checks(seconds_left, now - quote.observed_at, bid, spread, depth, change, rng, settings)

    suggestion = None
    if ask is not None and ask > 0 and verdict in {"BUY", "WAIT"}:
        stop_off = settings.auto_stop_loss_offset
        tp_off = settings.auto_take_profit_offset
        risk_per_share = stop_off if stop_off > 0 else ask
        budget = equity * Decimal("0.01")  # risk at most 1% of equity per trade
        shares = min(budget / risk_per_share, settings.max_order_exposure / ask)
        shares = max(Decimal(1), Decimal(math.floor(shares)))
        gain = Decimal(1) - ask
        suggestion = {
            "token": token, "shares": int(shares), "entry": _f(ask), "cost": _f(shares * ask, 2),
            "limit_at_bid": _f(bid),
            "stop": _f(ask - stop_off) if stop_off > 0 and ask - stop_off > 0 else None,
            "target": _f(ask + tp_off) if tp_off > 0 and ask + tp_off < 1 else None,
            "max_loss_at_stop": _f(shares * stop_off, 2) if stop_off > 0 else None,
            "max_loss_if_wrong": _f(shares * ask, 2), "max_gain": _f(shares * gain, 2),
            "break_even_win_rate": _f(ask, 3),  # holding to the end, you must be right this often
            "needed_win_rate_with_stop": _f(stop_off / (stop_off + gain), 3) if stop_off > 0 and gain > 0 else None,
        }
    return {
        "market_id": market_id, "question": question, "verdict": verdict, "score": score, "reasons": reasons,
        "seconds_left": int(seconds_left), "favourite": token,
        "metrics": {
            "bid": _f(bid), "ask": _f(ask), "spread_cents": _f(spread * 100, 1) if spread is not None else None,
            "depth": _f(depth, 1), "change_60s_cents": round(change * 100, 1) if change is not None else None,
            "implied_probability": _f(bid, 3),
            "range_2m_cents": round(rng * 100, 1) if rng is not None else None,
        },
        "checks": checks, "next_steps": next_steps,
        "suggestion": suggestion,
    }


PRIORITY = {"BUY": 0, "WAIT": 1, "AVOID": 2}


def rank(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(items, key=lambda i: (PRIORITY[i["verdict"]], -i["score"], i["seconds_left"]))
