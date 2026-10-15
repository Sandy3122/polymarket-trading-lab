"""Continuous public-data paper-trading worker.

The worker has one deliberately narrow responsibility: turn public market and
trade/resolution events into paper decisions, paper fills, and settlements.
It never has credentials and never calls a live execution adapter.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from .config import Settings, get_settings
from .database import SessionLocal, init_db
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

log = logging.getLogger(__name__)


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
        self.strategy = strategy or M1Strategy(M1Config(max_order_size=self.settings.max_order_exposure))
        self._seen_trades: set[tuple[str, str, str, str, str]] = set()

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
        snapshots = [snapshot for snapshot in discovered if self._is_supported_market(snapshot)]
        with self.session_factory() as session:
            for snapshot in snapshots:
                self._upsert_market(session, snapshot)
            self._health(
                session,
                "market_data",
                "ok",
                f"discovered {len(discovered)}; selected {len(snapshots)} markets; queue_model={self.settings.paper_queue_model}",
            )
            session.commit()
        return snapshots, WorkerStats(markets_seen=len(snapshots))

    def _is_supported_market(self, snapshot: MarketSnapshot) -> bool:
        if not self.settings.worker_require_crypto:
            return True
        if snapshot.start_time is None:
            return False
        duration_minutes = (snapshot.end_time - snapshot.start_time).total_seconds() / 60
        if not self.settings.min_market_duration_minutes <= duration_minutes <= self.settings.max_market_duration_minutes:
            return False
        text = f"{snapshot.question} {snapshot.slug or ''} {snapshot.category or ''}".lower()
        return any(keyword in text for keyword in ("bitcoin", "btc", "ethereum", "eth", "solana", "sol", "crypto"))

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
            if market.status != "open":
                return WorkerStats()
            age = event.occurred_at - book.observed_at
            if age.total_seconds() > self.settings.max_market_data_age_seconds:
                self._health(session, "market_data", "stale", f"book for {market.market_key} is {age.total_seconds():.1f}s old")
                return WorkerStats()
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
        init_db()
        while True:
            delay = self.settings.worker_refresh_seconds
            try:
                snapshots, _ = self.sync_markets()
                await self._stream_cycle(snapshots)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                delay = self.settings.worker_reconnect_seconds
                log.exception("paper worker cycle failed: %s", exc)
                with self.session_factory() as session:
                    self._health(session, "market_data", "error", str(exc)[:500])
                    session.commit()
            await asyncio.sleep(delay)

    async def _stream_cycle(self, snapshots: list[MarketSnapshot]) -> None:
        active = [snapshot for snapshot in snapshots if snapshot.status == "open"]
        if not active:
            await asyncio.sleep(self.settings.worker_refresh_seconds)
            return
        stream = PolymarketMarketStream(active)
        iterator = stream.events().__aiter__()
        try:
            while True:
                try:
                    event = await asyncio.wait_for(
                        iterator.__anext__(), timeout=self.settings.worker_refresh_seconds
                    )
                except asyncio.TimeoutError:
                    return
                except StopAsyncIteration:
                    return
                self.process_event(event)
        finally:
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
