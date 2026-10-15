"""Minimal local API and browser dashboard for the paper account."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from pathlib import Path

from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from .config import get_settings
from .accounts import (
    AccountDataError,
    PolymarketPublicAccountSource,
    ReadOnlyAccountSource,
    persist_account_observation,
)
from .dashboard import DASHBOARD_HTML
from .database import SessionLocal, get_session, init_db
from .insights import analyze, rank
from .live import live_quotes
from .models import AccountActivityRecord, AccountReconciliationRecord, AccountSnapshotRecord, Market, PaperOrder, Position, ReplayDecision, ReplayRun, StrategyDecision, SystemHealth
from .paper import PaperTrading
from .replay import ReplayService
from .risk import RiskChecker, RiskLimits
from .runner import StrategyRunner
from .runtime_settings import apply_changes, describe, load_overrides, reset_all
from .strategy import CurrentBook, M1Strategy
from .trading import TradeError, clear_exit, market_trade, portfolio_view, set_exit
from .worker_control import worker_controller
from .worker_lock import WorkerAlreadyRunning


app = FastAPI(title="Polymarket Trading Lab", version="0.1.0")
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


class MarketCreate(BaseModel):
    market_key: str = Field(min_length=1, max_length=200)
    question: str = Field(min_length=1)
    end_time: datetime


class OrderCreate(BaseModel):
    market_id: int
    token: str
    side: str
    price: Decimal = Field(gt=0, le=1)
    quantity: Decimal = Field(gt=0)
    auto_fill: bool = False


class TradeCreate(BaseModel):
    market_id: int
    token: str = Field(pattern="^(?i:yes|no)$")
    side: str = Field(pattern="^(?i:buy|sell)$")
    quantity: Decimal = Field(gt=0)


class ExitSet(BaseModel):
    market_id: int
    token: str = Field(pattern="^(?i:yes|no)$")
    stop_loss_price: Decimal | None = None
    take_profit_price: Decimal | None = None


class BookEvaluate(BaseModel):
    observed_at: datetime
    yes_bid: Decimal | None = None
    yes_bid_size: Decimal = Field(default=0, ge=0)
    no_bid: Decimal | None = None
    no_bid_size: Decimal = Field(default=0, ge=0)
    now: datetime | None = None


class ReplayCreate(BaseModel):
    events: list[dict[str, Any]] = Field(min_length=1)
    name: str = Field(default="API replay", min_length=1, max_length=200)
    source: str = Field(default="api", min_length=1, max_length=300)


def get_account_source(account_id: str) -> ReadOnlyAccountSource:
    """FastAPI dependency kept injectable for mocked public account tests."""

    settings = get_settings()
    return PolymarketPublicAccountSource(
        account_id,
        base_url=settings.account_data_base_url,
        positions_path=settings.account_positions_path,
        activity_path=settings.account_activity_path,
    )


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _paper_broker(session: Session) -> PaperTrading:
    settings = get_settings()
    return PaperTrading(
        session,
        initial_cash=settings.initial_cash,
        risk_checker=RiskChecker(
            RiskLimits(
                max_order_exposure=settings.max_order_exposure,
                max_market_exposure=settings.max_market_exposure,
                max_total_exposure=settings.max_total_exposure,
                max_daily_loss=settings.max_daily_loss,
            )
        ),
    )


@app.on_event("startup")
def startup() -> None:
    init_db()
    with SessionLocal() as session:
        load_overrides(session)
        session.commit()


@app.get("/health")
def health(session: Session = Depends(get_session)) -> dict[str, object]:
    settings = get_settings()
    row = session.scalar(select(SystemHealth).where(SystemHealth.component == "api"))
    if row is None:
        row = SystemHealth(component="api", status="ok", details="paper-only local API")
        session.add(row)
    else:
        row.status = "ok"
        row.checked_at = datetime.now(timezone.utc)
    session.commit()
    return {
        "status": "ok",
        "mode": "paper" if settings.paper_only else "review-required",
        "database": settings.database_url.split(":", 1)[0],
        "queue_model": settings.paper_queue_model,
        "real_execution": False,
    }


@app.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    return DASHBOARD_HTML


@app.get("/settings")
def get_runtime_settings() -> dict[str, object]:
    return {"fields": describe(), "paper_only": True, "data_source": "Polymarket public CLOB/Gamma API (no API key required)"}


@app.put("/settings")
def put_runtime_settings(changes: dict[str, Any], session: Session = Depends(get_session)) -> dict[str, object]:
    try:
        apply_changes(session, changes)
    except ValueError as exc:  # includes pydantic ValidationError
        session.rollback()
        raise HTTPException(400, str(exc)) from exc
    session.commit()
    return {"fields": describe()}


@app.post("/settings/reset")
def reset_runtime_settings(session: Session = Depends(get_session)) -> dict[str, object]:
    reset_all(session)
    session.commit()
    return {"fields": describe()}


@app.get("/markets")
def markets(session: Session = Depends(get_session)) -> list[dict[str, object]]:
    return [
        {"id": m.id, "market_key": m.market_key, "question": m.question, "end_time": _iso(m.end_time), "status": m.status}
        for m in session.scalars(select(Market).order_by(desc(Market.created_at)))
    ]


@app.post("/markets", status_code=201)
def create_market(payload: MarketCreate, session: Session = Depends(get_session)) -> dict[str, object]:
    if payload.end_time.tzinfo is None:
        raise HTTPException(400, "end_time must include a timezone")
    market = Market(market_key=payload.market_key, question=payload.question, end_time=payload.end_time)
    session.add(market)
    session.commit()
    return {"id": market.id, "market_key": market.market_key, "status": market.status}


@app.get("/orders")
def orders(limit: int = 200, session: Session = Depends(get_session)) -> list[dict[str, object]]:
    return [
        {"id": o.id, "client_order_id": o.client_order_id, "market_id": o.market_id, "token": o.token,
         "side": o.side, "price": str(o.price), "quantity": str(o.quantity), "filled_quantity": str(o.filled_quantity),
         "status": o.status, "reject_reason": o.reject_reason, "simulation_model": o.simulation_model,
         "market_id": o.market_id, "average_fill_price": str(o.average_fill_price) if o.average_fill_price is not None else None,
         "created_at": _iso(o.created_at), "question": o.market.question,
         "queue_ahead_initial": str(o.queue_ahead_initial), "queue_ahead_remaining": str(o.queue_ahead_remaining),
         "queue_consumed": str(o.queue_consumed)}
        for o in session.scalars(select(PaperOrder).order_by(desc(PaperOrder.created_at)).limit(max(1, min(limit, 1000))))
    ]


@app.post("/paper/orders", status_code=201)
def create_paper_order(payload: OrderCreate, session: Session = Depends(get_session)) -> dict[str, object]:
    market = session.get(Market, payload.market_id)
    if market is None:
        raise HTTPException(404, "market not found")
    broker = _paper_broker(session)
    try:
        order = broker.submit_order(market, payload.token, payload.side, payload.price, payload.quantity, auto_fill=payload.auto_fill)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    session.commit()
    return {"id": order.id, "status": order.status, "client_order_id": order.client_order_id, "reject_reason": order.reject_reason}


@app.get("/portfolio")
def portfolio(session: Session = Depends(get_session)) -> dict[str, object]:
    return {"mode": "paper", **portfolio_view(session, _paper_broker(session))}


@app.get("/live/markets")
def live_markets(session: Session = Depends(get_session)) -> list[dict[str, object]]:
    """Markets with a live quote, soonest-ending first."""

    now = datetime.now(timezone.utc)
    rows = []
    for key in live_quotes.keys():
        market = session.scalar(select(Market).where(Market.market_key == key))
        quote = live_quotes.latest(key)
        if market is None or quote is None:
            continue
        rows.append({
            "id": market.id, "question": market.question, "status": market.status,
            "end_time": _iso(market.end_time),
            "seconds_left": int((market.end_time - now).total_seconds()),
            "quote": _quote_json(quote),
            "spark": [float(t.yes_bid) for t in live_quotes.ticks(key)[-60:] if t.yes_bid is not None],
        })
    return sorted(rows, key=lambda row: row["end_time"] or "")


def _quote_json(quote: Any) -> dict[str, object]:
    def text(value: Decimal | None) -> str | None:
        return None if value is None else str(value)

    return {
        "observed_at": _iso(quote.observed_at),
        "yes_bid": text(quote.yes_bid), "yes_ask": text(quote.yes_ask), "yes_bid_size": str(quote.yes_bid_size),
        "no_bid": text(quote.no_bid), "no_ask": text(quote.no_ask), "no_bid_size": str(quote.no_bid_size),
    }


@app.get("/live/discovery")
def live_discovery() -> dict[str, object]:
    """Last market-discovery result: which markets were kept or filtered out, and why."""

    found = live_quotes.discovery()
    settings = get_settings()
    return {
        "at": _iso(found["at"]) if found["at"] else None,
        "window_minutes": settings.max_market_duration_minutes + 2,
        "min_minutes": settings.min_market_duration_minutes, "max_minutes": settings.max_market_duration_minutes,
        "rows": found["rows"],
    }


@app.get("/insights")
def insights(session: Session = Depends(get_session)) -> dict[str, object]:
    """Per-market buy/wait/avoid verdicts from live quotes (rule-based, not a prediction)."""

    now = datetime.now(timezone.utc)
    settings = get_settings()
    equity = Decimal(str(portfolio_view(session, _paper_broker(session))["equity"]))
    items = []
    for key in live_quotes.keys():
        market = session.scalar(select(Market).where(Market.market_key == key))
        quote = live_quotes.latest(key)
        if market is None or quote is None or market.status != "open":
            continue
        items.append(analyze(
            market_id=market.id, question=market.question, end_time=market.end_time, now=now, quote=quote,
            ticks=live_quotes.ticks(key), settings=settings, equity=equity,
        ))
    return {"generated_at": _iso(now), "items": rank(items)}


@app.get("/live/markets/{market_id}/stream")
async def live_stream(market_id: int, request: Request) -> StreamingResponse:
    """Server-Sent Events: pushes every new quote for one market as soon as the worker receives it."""

    with SessionLocal() as session:
        market = session.get(Market, market_id)
        key = market.market_key if market else None
    if key is None:
        raise HTTPException(404, "market not found")

    async def events():
        last = None
        quiet = 0
        yield "retry: 2000\n\n"
        while not await request.is_disconnected():
            quote = live_quotes.latest(key)
            if quote is not None and quote is not last:
                last, quiet = quote, 0
                tick = {"t": _iso(quote.observed_at),
                        "yes": str(quote.yes_bid) if quote.yes_bid is not None else None,
                        "no": str(quote.no_bid) if quote.no_bid is not None else None}
                yield f"data: {json.dumps({'quote': _quote_json(quote), 'tick': tick})}\n\n"
            else:
                quiet += 1
                if quiet % 40 == 0:  # ~10 s keep-alive so proxies/browsers keep the stream open
                    yield ": keep-alive\n\n"
            await asyncio.sleep(0.25)

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/live/markets/{market_id}/ticks")
def live_ticks(market_id: int, session: Session = Depends(get_session)) -> dict[str, object]:
    market = session.get(Market, market_id)
    if market is None:
        raise HTTPException(404, "market not found")
    quote = live_quotes.latest(market.market_key)
    return {
        "market_id": market.id, "question": market.question, "end_time": _iso(market.end_time),
        "quote": _quote_json(quote) if quote else None,
        "m1": {"min": float(get_settings().m1_min_price), "max": float(get_settings().m1_max_price),
               "window": get_settings().m1_entry_window_seconds},
        "ticks": [
            {"t": _iso(tick.observed_at), "yes": str(tick.yes_bid) if tick.yes_bid is not None else None,
             "no": str(tick.no_bid) if tick.no_bid is not None else None}
            for tick in live_quotes.ticks(market.market_key)
        ],
    }


@app.post("/paper/trade", status_code=201)
def paper_trade(payload: TradeCreate, session: Session = Depends(get_session)) -> dict[str, object]:
    """Instant paper BUY (at ask) or SELL (at bid) against the live quote."""

    market = session.get(Market, payload.market_id)
    if market is None:
        raise HTTPException(404, "market not found")
    try:
        order = market_trade(session, _paper_broker(session), market, payload.token, payload.side, payload.quantity)
    except (TradeError, ValueError) as exc:
        session.rollback()
        raise HTTPException(400, str(exc)) from exc
    session.commit()
    return {"id": order.id, "status": order.status, "side": order.side, "token": order.token,
            "quantity": str(order.filled_quantity), "price": str(order.average_fill_price)}


@app.put("/paper/exits")
def put_exit(payload: ExitSet, session: Session = Depends(get_session)) -> dict[str, object]:
    market = session.get(Market, payload.market_id)
    if market is None:
        raise HTTPException(404, "market not found")
    try:
        row = set_exit(session, market, payload.token, payload.stop_loss_price, payload.take_profit_price)
    except TradeError as exc:
        session.rollback()
        raise HTTPException(400, str(exc)) from exc
    session.commit()
    return {"market_id": row.market_id, "token": row.token, "status": row.status,
            "stop_loss_price": str(row.stop_loss_price) if row.stop_loss_price is not None else None,
            "take_profit_price": str(row.take_profit_price) if row.take_profit_price is not None else None}


@app.delete("/paper/exits/{market_id}/{token}")
def delete_exit(market_id: int, token: str, session: Session = Depends(get_session)) -> dict[str, object]:
    market = session.get(Market, market_id)
    if market is None:
        raise HTTPException(404, "market not found")
    clear_exit(session, market, token)
    session.commit()
    return {"cleared": True}


def _replay_summary(run: ReplayRun) -> dict[str, object]:
    return {
        "id": run.id, "name": run.name, "source": run.source, "strategy": run.strategy_name,
        "status": run.status, "started_at": _iso(run.started_at), "completed_at": _iso(run.completed_at),
        "event_count": run.event_count, "market_count": run.market_count,
        "decision_count": run.decision_count, "actionable_decision_count": run.actionable_decision_count,
        "orders_created": run.orders_created, "fills": run.fills, "settlements": run.settlements,
        "initial_cash": str(run.initial_cash), "final_cash": str(run.final_cash),
        "realized_pnl": str(run.realized_pnl), "net_pnl": str(run.net_pnl),
        "positions": json.loads(run.positions_json or "[]"),
        "summary": json.loads(run.summary_json or "{}"), "error": run.error,
    }


@app.get("/ops/worker/status")
def worker_status(session: Session = Depends(get_session)) -> dict[str, object]:
    return worker_controller.status(session)


@app.post("/ops/worker/start")
async def start_worker() -> dict[str, object]:
    # The controller starts only PaperMarketWorker; live execution remains unavailable.
    try:
        return await worker_controller.start(SessionLocal)
    except WorkerAlreadyRunning as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/ops/worker/stop")
async def stop_worker() -> dict[str, object]:
    return await worker_controller.stop(SessionLocal)


@app.get("/ops/overview")
def operations_overview(session: Session = Depends(get_session)) -> dict[str, object]:
    return {
        "mode": "paper", "real_execution": False,
        "worker": worker_controller.status(session),
        "health": [{"component": row.component, "status": row.status, "checked_at": _iso(row.checked_at), "details": row.details}
                    for row in session.scalars(select(SystemHealth).order_by(SystemHealth.component))],
        "portfolio": portfolio(session),
        "stats": {
            "markets": session.scalar(select(func.count(Market.id))) or 0,
            "open_orders": session.scalar(select(func.count(PaperOrder.id)).where(PaperOrder.status.in_(("open", "partially_filled")))) or 0,
            "decisions": session.scalar(select(func.count(StrategyDecision.id))) or 0,
            "fills": session.scalar(select(func.count(PaperOrder.id)).where(PaperOrder.status == "filled")) or 0,
            "replay_runs": session.scalar(select(func.count(ReplayRun.id))) or 0,
        },
        "decisions": decisions(session)[:20],
        "replays": [_replay_summary(run) for run in session.scalars(select(ReplayRun).order_by(desc(ReplayRun.created_at)).limit(20))],
    }


@app.get("/decisions")
def decisions(session: Session = Depends(get_session)) -> list[dict[str, object]]:
    return [{"id": d.id, "market_id": d.market_id, "strategy": d.strategy_name, "decision_time": _iso(d.decision_time),
             "reason": d.reason, "intents": d.intents_json, "observations": d.observations_json}
             for d in session.scalars(select(StrategyDecision).order_by(desc(StrategyDecision.decision_time)).limit(100))]


@app.post("/replays", status_code=201)
def create_replay(payload: ReplayCreate, session: Session = Depends(get_session)) -> dict[str, object]:
    from .market_data import event_from_mapping

    try:
        events = [event_from_mapping(event) for event in payload.events]
        result = ReplayService().execute(session, events, name=payload.name, source=payload.source)
        session.commit()
        return _replay_summary(result.run)
    except (KeyError, TypeError, ValueError) as exc:
        session.rollback()
        raise HTTPException(400, f"invalid replay: {exc}") from exc


@app.get("/replays")
def replays(session: Session = Depends(get_session)) -> list[dict[str, object]]:
    return [_replay_summary(run) for run in session.scalars(select(ReplayRun).order_by(desc(ReplayRun.created_at)).limit(100))]


@app.get("/replays/{run_id}")
def replay_detail(run_id: int, session: Session = Depends(get_session)) -> dict[str, object]:
    run = session.get(ReplayRun, run_id)
    if run is None:
        raise HTTPException(404, "replay run not found")
    result = _replay_summary(run)
    result["decisions"] = [
        {"id": decision.id, "market_key": decision.market_key, "strategy": decision.strategy_name,
         "decision_time": _iso(decision.decision_time), "reason": decision.reason,
         "intents": json.loads(decision.intents_json or "[]"),
         "observations": json.loads(decision.observations_json or "{}")}
        for decision in session.scalars(select(ReplayDecision).where(ReplayDecision.run_id == run_id).order_by(ReplayDecision.decision_time))
    ]
    return result


@app.post("/paper/evaluate/{market_id}", status_code=201)
def evaluate_paper_strategy(market_id: int, payload: BookEvaluate, session: Session = Depends(get_session)) -> dict[str, object]:
    market = session.get(Market, market_id)
    if market is None:
        raise HTTPException(404, "market not found")
    if payload.observed_at.tzinfo is None or (payload.now is not None and payload.now.tzinfo is None):
        raise HTTPException(400, "timestamps must include a timezone")
    broker = _paper_broker(session)
    runner = StrategyRunner(session, M1Strategy(), broker)
    now = payload.now or datetime.now(timezone.utc)
    record = runner.evaluate(
        market,
        CurrentBook(payload.observed_at, payload.yes_bid, payload.yes_bid_size, payload.no_bid, payload.no_bid_size),
        now,
    )
    session.commit()
    return {"decision_id": record.id, "reason": record.reason, "intents": record.intents_json}


def _account_snapshot_json(record: AccountSnapshotRecord) -> dict[str, object]:
    return {
        "id": record.id,
        "provider": record.provider,
        "account_id": record.account_id,
        "observed_at": _iso(record.observed_at),
        "cash": str(record.cash) if record.cash is not None else None,
        "account_value": str(record.account_value) if record.account_value is not None else None,
        "metadata": json.loads(record.metadata_json),
        "positions": [
            {
                "market_id": position.market_id,
                "token": position.token,
                "quantity": str(position.quantity),
                "average_price": str(position.average_price),
                "current_price": str(position.current_price) if position.current_price is not None else None,
                "current_value": str(position.current_value) if position.current_value is not None else None,
            }
            for position in record.positions
        ],
    }


def _account_reconciliation_json(record: AccountReconciliationRecord) -> dict[str, object]:
    return {
        "id": record.id,
        "provider": record.provider,
        "account_id": record.account_id,
        "snapshot_id": record.snapshot_id,
        "reconciled_at": _iso(record.reconciled_at),
        "paper_cash": str(record.paper_cash) if record.paper_cash is not None else None,
        "observed_cash": str(record.observed_cash) if record.observed_cash is not None else None,
        "cash_difference": str(record.cash_difference) if record.cash_difference is not None else None,
        "status": record.status,
        "differences": json.loads(record.differences_json),
    }


@app.post("/accounts/{account_id}/sync", status_code=201)
def sync_account(
    account_id: str,
    session: Session = Depends(get_session),
    source: ReadOnlyAccountSource = Depends(get_account_source),
) -> dict[str, object]:
    """Fetch and persist public account observations without changing paper state."""

    if source is None or account_id.strip() == "":
        raise HTTPException(400, "account_id must not be empty")
    try:
        snapshot, reconciliation = persist_account_observation(
            session,
            source,
            provider=getattr(source, "provider", "unknown"),
        )
        session.commit()
    except (AccountDataError, ValueError) as exc:
        session.rollback()
        raise HTTPException(502, str(exc)) from exc
    return {
        "snapshot": _account_snapshot_json(snapshot),
        "reconciliation": _account_reconciliation_json(reconciliation),
        "paper_mutated": False,
    }


@app.get("/accounts/{account_id}")
def account(account_id: str, session: Session = Depends(get_session)) -> dict[str, object]:
    """Return the latest persisted observation and reconciliation."""

    snapshot = session.scalar(
        select(AccountSnapshotRecord)
        .where(AccountSnapshotRecord.account_id == account_id)
        .order_by(desc(AccountSnapshotRecord.observed_at))
    )
    if snapshot is None:
        raise HTTPException(404, "account has not been synced")
    reconciliation = session.scalar(
        select(AccountReconciliationRecord)
        .where(AccountReconciliationRecord.snapshot_id == snapshot.id)
        .order_by(desc(AccountReconciliationRecord.reconciled_at))
    )
    return {
        "snapshot": _account_snapshot_json(snapshot),
        "reconciliation": _account_reconciliation_json(reconciliation) if reconciliation else None,
    }


@app.get("/accounts/{account_id}/snapshots")
def account_snapshots(account_id: str, session: Session = Depends(get_session)) -> list[dict[str, object]]:
    records = session.scalars(
        select(AccountSnapshotRecord)
        .where(AccountSnapshotRecord.account_id == account_id)
        .order_by(desc(AccountSnapshotRecord.observed_at))
        .limit(100)
    )
    return [_account_snapshot_json(record) for record in records]


@app.get("/accounts/{account_id}/activities")
def account_activities(account_id: str, session: Session = Depends(get_session)) -> list[dict[str, object]]:
    records = session.scalars(
        select(AccountActivityRecord)
        .where(AccountActivityRecord.account_id == account_id)
        .order_by(desc(AccountActivityRecord.occurred_at))
        .limit(200)
    )
    return [
        {
            "id": record.id,
            "provider": record.provider,
            "account_id": record.account_id,
            "activity_id": record.activity_id,
            "occurred_at": _iso(record.occurred_at),
            "activity_type": record.activity_type,
            "market_id": record.market_id,
            "token": record.token,
            "side": record.side,
            "quantity": str(record.quantity) if record.quantity is not None else None,
            "price": str(record.price) if record.price is not None else None,
            "cash_amount": str(record.cash_amount) if record.cash_amount is not None else None,
            "transaction_hash": record.transaction_hash,
            "raw": record.raw_json,
        }
        for record in records
    ]


@app.get("/accounts/{account_id}/reconciliations")
def account_reconciliations(account_id: str, session: Session = Depends(get_session)) -> list[dict[str, object]]:
    records = session.scalars(
        select(AccountReconciliationRecord)
        .where(AccountReconciliationRecord.account_id == account_id)
        .order_by(desc(AccountReconciliationRecord.reconciled_at))
        .limit(100)
    )
    return [_account_reconciliation_json(record) for record in records]
