"""Continuous public-data paper-trading worker.

The worker has one deliberately narrow responsibility: turn public market and
trade/resolution events into paper decisions, paper fills, and settlements.
It never has credentials and never calls a live execution adapter.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from .config import Settings, get_settings
from .database import SessionLocal, init_db
from .live import Quote, live_quotes
from .market_data import (
    BookSnapshot,
    MarketEvent,
    MarketSnapshot,
    PolymarketMarketStream,
    PolymarketPublicClient,
    Resolution,
    TradeSnapshot,
)
from .models import Market, PaperFill, PaperOrder, SystemHealth
from .paper import PaperTrading
from .queue import QueueModel, QueueState, consume_queue, initial_queue_ahead
from .risk import RiskChecker, RiskLimits
from .runner import StrategyRunner
from .strategy import CurrentBook, M1Config, M1Strategy
from .trading import apply_auto_exit, evaluate_exits
from .worker_lock import WorkerAlreadyRunning, WorkerLock  # noqa: F401

log = logging.getLogger(__name__)

CRYPTO_KEYWORDS = frozenset({
    "bitcoin", "btc", "ethereum", "eth", "solana", "sol", "xrp", "doge", "dogecoin",
    "bnb", "hype", "zec", "crypto",
})


@dataclass(frozen=True)
class WorkerStats:
    markets_seen: int = 0
    decisions: int = 0
    orders_created: int = 0
    fills: int = 0
    settlements: int = 0


class PaperMarketWorker:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session] = SessionLocal,
        client: PolymarketPublicClient | None = None,
        settings: Settings | None = None,
        strategy: M1Strategy | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.session_factory = session_factory
        self.client = client or PolymarketPublicClient()
        self._strategy_override = strategy
        self._seen_trades: set[tuple[str, str, str, str, str]] = set()
        self._last_book: dict[str, tuple[object, ...]] = {}

    @property
    def strategy(self) -> M1Strategy:
        """Built per decision so dashboard setting changes apply immediately."""

        if self._strategy_override is not None:
            return self._strategy_override
        cfg = self.settings
        return M1Strategy(M1Config(
            min_price=cfg.m1_min_price, max_price=cfg.m1_max_price, max_order_size=cfg.max_order_exposure,
            max_book_age=timedelta(seconds=cfg.max_market_data_age_seconds),
            entry_window=timedelta(seconds=cfg.m1_entry_window_seconds),
        ))

    def _broker(self, session: Session) -> PaperTrading:
        return PaperTrading(
            session,
            initial_cash=self.settings.initial_cash,
            risk_checker=RiskChecker(
                RiskLimits(
                    max_order_exposure=self.settings.max_order_exposure,
                    max_market_exposure=self.settings.max_market_exposure,
                    max_total_exposure=self.settings.max_total_exposure,
                    max_daily_loss=self.settings.max_daily_loss,
                )
            ),
        )

    @staticmethod
    def _upsert_market(session: Session, snapshot: MarketSnapshot) -> Market:
        market = session.scalar(select(Market).where(Market.market_key == snapshot.market_id))
        if market is None:
            market = Market(
                market_key=snapshot.market_id,
                question=snapshot.question,
                end_time=snapshot.end_time,
            )
            session.add(market)
        market.question = snapshot.question
        market.end_time = snapshot.end_time
        market.status = snapshot.status
        market.yes_token_id = snapshot.yes_token_id
        market.no_token_id = snapshot.no_token_id
        market.condition_id = snapshot.condition_id
        market.slug = snapshot.slug
        market.start_time = snapshot.start_time
        market.category = snapshot.category
        session.flush()
        return market

    def sync_markets(self) -> tuple[list[MarketSnapshot], WorkerStats]:
        now = datetime.now(timezone.utc)
        discovered = self.client.list_markets(
            limit=self.settings.market_page_size,
            max_pages=self.settings.market_pages,
            closed=False,
            active=True,
            end_date_min=now,
            end_date_max=now + timedelta(minutes=self.settings.max_market_duration_minutes + 2),
            order="endDate",
            ascending=True,
        )
        snapshots = []
        excluded: Counter[str] = Counter()
        rows: list[dict[str, object]] = []
        kept_open = 0
        for snapshot in discovered:
            reason = self._exclusion_reason(snapshot)
            status = reason or "kept"
            if reason is None:
                snapshots.append(snapshot)
                if snapshot.status == "open":
                    kept_open += 1
                    if kept_open > self.settings.worker_stream_market_limit:
                        status = "over_stream_limit"
            else:
                excluded[reason] += 1
                log.debug("excluded market %s: %s", snapshot.slug, reason)
            minutes = (snapshot.end_time - snapshot.start_time).total_seconds() / 60 if snapshot.start_time else None
            rows.append({
                "market_key": snapshot.market_id, "question": snapshot.question,
                "end_time": snapshot.end_time.isoformat(), "minutes": round(minutes, 1) if minutes is not None else None,
                "status": status,
            })
        live_quotes.set_discovery(now, rows)
        excluded_summary = ", ".join(f"{k}={v}" for k, v in sorted(excluded.items())) or "none"
        with self.session_factory() as session:
            for snapshot in snapshots:
                self._upsert_market(session, snapshot)
            self._health(
                session,
                "market_data",
                "ok",
                f"discovered {len(discovered)}; selected {len(snapshots)} markets; excluded: {excluded_summary}; queue_model={self.settings.paper_queue_model}",
            )
            session.commit()
        return snapshots, WorkerStats(markets_seen=len(snapshots))

    def _is_supported_market(self, snapshot: MarketSnapshot) -> bool:
        return self._exclusion_reason(snapshot) is None

    def _exclusion_reason(self, snapshot: MarketSnapshot) -> str | None:
        if not self.settings.worker_require_crypto:
            return None
        if snapshot.start_time is None:
            return "missing_start_time"
        duration_minutes = (snapshot.end_time - snapshot.start_time).total_seconds() / 60
        if not self.settings.min_market_duration_minutes <= duration_minutes <= self.settings.max_market_duration_minutes:
            return "duration_outside_window"
        text = f"{snapshot.question} {snapshot.slug or ''} {snapshot.category or ''}".lower()
        tokens = set(re.split(r"[^a-z0-9]+", text))
        keywords = {k.strip().lower() for k in self.settings.market_keywords.split(",") if k.strip()}
        if keywords and not tokens & keywords:
            return "not_crypto"
        return None

    def process_event(self, event: MarketEvent) -> WorkerStats:
        with self.session_factory() as session:
            broker = self._broker(session)
            stats = self._process_event(session, broker, event)
            session.commit()
            return stats

    def _process_event(self, session: Session, broker: PaperTrading, event: MarketEvent) -> WorkerStats:
        if event.event_type == "market":
            snapshot = event.payload
            assert isinstance(snapshot, MarketSnapshot)
            self._upsert_market(session, snapshot)
            return WorkerStats(markets_seen=1)

        payload = event.payload
        market_key = getattr(payload, "market_id", None)
        market = session.scalar(select(Market).where(Market.market_key == market_key)) if market_key else None
        if market is None:
            return WorkerStats()

        if event.event_type == "book":
            book = payload
            assert isinstance(book, BookSnapshot)
            book_key = (book.observed_at, book.yes_bid, book.yes_bid_size, book.no_bid, book.no_bid_size)
            if self._last_book.get(market.market_key) == book_key:
                # The stream emits one identical snapshot per token update; one
                # decision per distinct book is enough.
                return WorkerStats()
            self._last_book[market.market_key] = book_key
            quote = Quote(book.observed_at, book.yes_bid, book.yes_bid_size, book.no_bid, book.no_bid_size)
            live_quotes.record(market.market_key, quote)
            if market.status != "open":
                return WorkerStats()
            if event.occurred_at >= market.end_time:
                # End time is not settlement. Stop making decisions and cancel
                # resting paper orders, but wait for an explicit resolution
                # event before paying out positions.
                for order in session.scalars(
                    select(PaperOrder).where(
                        PaperOrder.market_id == market.id,
                        PaperOrder.status.in_(("open", "partially_filled")),
                    )
                ):
                    order.status = "cancelled"
                market.status = "closed"
                return WorkerStats()
            age = event.occurred_at - book.observed_at
            if age.total_seconds() > self.settings.max_market_data_age_seconds:
                self._health(session, "market_data", "stale", f"book for {market.market_key} is {age.total_seconds():.1f}s old")
                return WorkerStats()
            evaluate_exits(session, broker, market, quote, event.occurred_at)
            before = self._open_order_ids(session, market.id)
            decision = StrategyRunner(session, self.strategy, broker).evaluate(
                market,
                CurrentBook(book.observed_at, book.yes_bid, book.yes_bid_size, book.no_bid, book.no_bid_size),
                event.occurred_at,
            )
            after = self._open_order_ids(session, market.id)
            for order_id in after - before:
                order = session.get(PaperOrder, order_id)
                if order is None:
                    continue
                visible_size = book.yes_bid_size if order.token == "YES" else book.no_bid_size
                self._configure_queue(order, visible_size)
            # A single market/token may have only one active paper maker order.
            # StrategyRunner already submitted intents; cancel duplicate intents
            # created by repeated book snapshots before they can be filled.
            created = self._cancel_duplicate_orders(session, market.id)
            return WorkerStats(decisions=1, orders_created=created, markets_seen=0)

        if event.event_type == "trade":
            trade = payload
            assert isinstance(trade, TradeSnapshot)
            if not self._new_trade(trade):
                return WorkerStats()
            fills = self._fill_from_trade(session, broker, market, trade)
            return WorkerStats(fills=fills)

        if event.event_type == "resolution":
            resolution = payload
            assert isinstance(resolution, Resolution)
            broker.settle_market(market, resolution.winning_token, now=resolution.resolved_at)
            return WorkerStats(settlements=1)

        return WorkerStats()

    @staticmethod
    def _open_order_ids(session: Session, market_id: int) -> set[int]:
        return {
            order.id
            for order in session.scalars(
                select(PaperOrder).where(
                    PaperOrder.market_id == market_id,
                    PaperOrder.status.in_(("open", "partially_filled")),
                )
            )
        }

    def _configure_queue(self, order: PaperOrder, visible_bid_size: Decimal) -> None:
        model = QueueModel(self.settings.paper_queue_model)
        ahead = initial_queue_ahead(model, visible_bid_size)
        order.simulation_model = model.value
        order.queue_ahead_initial = ahead
        order.queue_ahead_remaining = ahead
        order.queue_consumed = Decimal("0")

    @staticmethod
    def _cancel_duplicate_orders(session: Session, market_id: int) -> int:
        active = list(
            session.scalars(
                select(PaperOrder).where(
                    PaperOrder.market_id == market_id,
                    PaperOrder.status.in_(("open", "partially_filled")),
                ).order_by(PaperOrder.created_at, PaperOrder.id)
            )
        )
        seen_tokens: set[str] = set()
        created = 0
        for order in active:
            if order.token in seen_tokens:
                order.status = "cancelled"
            else:
                seen_tokens.add(order.token)
                created += 1
        return created

    def _fill_from_trade(self, session: Session, broker: PaperTrading, market: Market, trade: TradeSnapshot) -> int:
        if trade.side != "SELL" or trade.size <= 0:
            return 0
        orders = list(
            session.scalars(
                select(PaperOrder).where(
                    PaperOrder.market_id == market.id,
                    PaperOrder.token == self._token_for_trade(market, trade.token_id),
                    PaperOrder.side == "BUY",
                    PaperOrder.status.in_(("open", "partially_filled")),
                    PaperOrder.price >= trade.price,
                ).order_by(PaperOrder.created_at, PaperOrder.id)
            )
        )
        remaining_trade = trade.size
        filled = 0
        event_id = trade.event_id or hashlib.sha256(
            f"{trade.market_id}|{trade.token_id}|{trade.side}|{trade.price}|{trade.size}|{trade.observed_at.isoformat()}".encode()
        ).hexdigest()
        for order in orders:
            if remaining_trade <= 0:
                break
            remaining_order = Decimal(str(order.quantity)) - Decimal(str(order.filled_quantity))
            if remaining_order <= 0:
                continue
            state = QueueState(
                QueueModel(order.simulation_model),
                Decimal(str(order.queue_ahead_initial)),
                Decimal(str(order.queue_ahead_remaining)),
            )
            new_state, fillable_trade = consume_queue(state, remaining_trade)
            consumed = state.remaining_ahead - new_state.remaining_ahead
            order.queue_ahead_remaining = new_state.remaining_ahead
            order.queue_consumed = Decimal(str(order.queue_consumed)) + consumed
            quantity = min(fillable_trade, remaining_order)
            if quantity <= 0:
                remaining_trade = fillable_trade
                continue
            order_event_id = f"{event_id}:{order.id}"
            if session.scalar(select(PaperFill.id).where(PaperFill.event_id == order_event_id)) is not None:
                continue
            broker.fill_order(order, now=trade.observed_at, price=order.price, quantity=quantity, event_id=order_event_id)
            remaining_trade -= quantity
            filled += 1
            apply_auto_exit(
                session, market, order.token,
                self.settings.auto_stop_loss_offset, self.settings.auto_take_profit_offset,
            )
        return filled

    def _new_trade(self, trade: TradeSnapshot) -> bool:
        key = (trade.market_id, trade.token_id, trade.side, str(trade.price), str(trade.observed_at))
        if key in self._seen_trades:
            return False
        self._seen_trades.add(key)
        return True

    @staticmethod
    def _token_for_trade(market: Market, token_id: str) -> str:
        if token_id == market.yes_token_id:
            return "YES"
        if token_id == market.no_token_id:
            return "NO"
        return "UNKNOWN"

    @staticmethod
    def _health(session: Session, component: str, status: str, details: str) -> None:
        row = session.scalar(select(SystemHealth).where(SystemHealth.component == component))
        if row is None:
            row = SystemHealth(component=component, status=status, details=details)
            session.add(row)
        else:
            row.status = status
            row.details = details
            row.checked_at = datetime.now(timezone.utc)

    async def run_once(self) -> WorkerStats:
        snapshots, stats = self.sync_markets()
        total = stats
        for snapshot in snapshots:
            if snapshot.status != "open":
                continue
            try:
                for event in self.client.market_events(snapshot):
                    current = self.process_event(event)
                    total = self._add_stats(total, current)
            except Exception as exc:
                log.warning("market %s skipped: %s", snapshot.market_id, exc)
        return total

    async def run_forever(self) -> None:
        # Two workers on one database double-fill orders and corrupt balances.
        lock = WorkerLock(self.settings.database_url)
        lock.acquire()
        try:
            await self._run_forever()
        finally:
            lock.release()

    async def _run_forever(self) -> None:
        init_db()
        from .runtime_settings import load_overrides

        with self.session_factory() as session:
            load_overrides(session)
        while True:
            delay = self.settings.worker_refresh_seconds
            try:
                snapshots, _ = self.sync_markets()
                await self._stream_cycle(snapshots)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                delay = self.settings.worker_reconnect_seconds
                log.warning("paper worker cycle failed; retrying in %ss: %s", delay, exc)
                with self.session_factory() as session:
                    self._health(session, "market_data", "error", str(exc)[:500])
                    session.commit()
            await asyncio.sleep(delay)

    async def _stream_cycle(self, snapshots: list[MarketSnapshot]) -> None:
        active = [snapshot for snapshot in snapshots if snapshot.status == "open"][: self.settings.worker_stream_market_limit]
        if not active:
            await asyncio.sleep(self.settings.worker_refresh_seconds)
            return
        stream = PolymarketMarketStream(active)
        iterator = stream.events().__aiter__()
        queue: asyncio.Queue[MarketEvent | None] = asyncio.Queue(maxsize=2048)
        producer_error: list[BaseException] = []

        async def receive() -> None:
            try:
                async for event in iterator:
                    await queue.put(event)
            except asyncio.CancelledError:
                raise
            except BaseException as exc:
                producer_error.append(exc)
            finally:
                try:
                    queue.put_nowait(None)
                except asyncio.QueueFull:
                    # The consumer is shutting down or the stream is too
                    # busy; cancellation/timeout will close the socket.
                    pass

        receiver = asyncio.create_task(receive(), name="polymarket-market-receiver")
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=self.settings.worker_refresh_seconds)
                except asyncio.TimeoutError:
                    return
                if event is None:
                    if producer_error:
                        raise producer_error[0]
                    return
                # Database work is synchronous. Keep the event-loop receiver
                # draining the socket while one event is being persisted.
                await asyncio.to_thread(self.process_event, event)
        finally:
            receiver.cancel()
            await asyncio.gather(receiver, return_exceptions=True)
            close = getattr(iterator, "aclose", None)
            if close is not None:
                await close()

    @staticmethod
    def _add_stats(left: WorkerStats, right: WorkerStats) -> WorkerStats:
        return WorkerStats(
            markets_seen=left.markets_seen + right.markets_seen,
            decisions=left.decisions + right.decisions,
            orders_created=left.orders_created + right.orders_created,
            fills=left.fills + right.fills,
            settlements=left.settlements + right.settlements,
        )
