"""Deterministic strategy replay and isolated paper backtest execution."""

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from .config import Settings, get_settings
from .database import Base
from .market_data import BookSnapshot, MarketEvent, MarketSnapshot, Resolution
from .models import Market, Position, ReplayDecision, ReplayRun, StrategyDecision as StrategyDecisionRecord
from .paper import PaperTrading
from .strategy import CurrentBook, M1Strategy, StrategyDecision, StrategyMarket


@dataclass
class ReplayRunner:
    strategy: M1Strategy

    def run(self, events: list[MarketEvent]) -> list[StrategyDecision]:
        decisions: list[StrategyDecision] = []
        markets: dict[str, MarketSnapshot] = {}
        books: dict[str, BookSnapshot] = {}
        resolved: set[str] = set()
        for event in sorted(events, key=lambda item: item.occurred_at):
            if event.event_type == "market":
                market = event.payload
                assert isinstance(market, MarketSnapshot)
                markets[market.market_id] = market
            elif event.event_type == "book":
                book = event.payload
                assert isinstance(book, BookSnapshot)
                books[book.market_id] = book
                market = markets.get(book.market_id)
                if market is None or market.status != "open" or market.market_id in resolved:
                    continue
                decisions.append(
                    self.strategy.decide(
                        StrategyMarket(market.market_id, market.end_time),
                        CurrentBook(book.observed_at, book.yes_bid, book.yes_bid_size, book.no_bid, book.no_bid_size),
                        event.occurred_at,
                    )
                )
            elif event.event_type == "resolution":
                resolution = event.payload
                assert isinstance(resolution, Resolution)
                resolved.add(resolution.market_id)
        return decisions


@dataclass(frozen=True)
class ReplayExecutionResult:
    """Small result object used by callers that need an immediate run summary."""

    run: ReplayRun


class ReplayService:
    """Execute replay events through a disposable paper account.

    The disposable account is important: a backtest cannot alter the live
    local paper portfolio, while still exercising the same worker, strategy,
    fills, settlement, risk, and ledger code used by the paper worker.
    """

    def __init__(self, settings: Settings | None = None, strategy: M1Strategy | None = None) -> None:
        self.settings = settings or get_settings()
        self.strategy = strategy or M1Strategy()

    def execute(
        self,
        session: Session,
        events: list[MarketEvent],
        *,
        name: str = "API replay",
        source: str = "api",
    ) -> ReplayExecutionResult:
        from .worker import PaperMarketWorker, WorkerStats

        ordered = sorted(events, key=lambda item: item.occurred_at)
        started_at = datetime.now(timezone.utc)
        replay = ReplayRun(
            name=name,
            source=source,
            strategy_name=self.strategy.name,
            status="running",
            started_at=started_at,
            initial_cash=self.settings.initial_cash,
        )
        session.add(replay)
        session.flush()

        temporary_engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(temporary_engine)
        temporary_factory = sessionmaker(bind=temporary_engine, expire_on_commit=False, class_=Session)
        stats = WorkerStats()
        try:
            worker = PaperMarketWorker(
                session_factory=temporary_factory,
                settings=self.settings,
                strategy=self.strategy,
            )
            for event in ordered:
                stats = worker._add_stats(stats, worker.process_event(event))

            with temporary_factory() as temporary_session:
                broker = PaperTrading(
                    temporary_session,
                    initial_cash=self.settings.initial_cash,
                )
                final_cash = broker.cash_balance()
                realized_pnl = broker.realized_pnl()
                positions = [
                    {
                        "market_id": position.market_id,
                        "token": position.token,
                        "quantity": str(position.quantity),
                        "average_entry_price": str(position.average_entry_price),
                        "realized_pnl": str(position.realized_pnl),
                    }
                    for position in temporary_session.scalars(
                        select(Position).order_by(Position.market_id, Position.token)
                    )
                    if Decimal(str(position.quantity)) != 0
                ]
                decisions = list(
                    temporary_session.scalars(
                        select(StrategyDecisionRecord).order_by(
                            StrategyDecisionRecord.decision_time, StrategyDecisionRecord.id
                        )
                    )
                )
                for decision in decisions:
                    market = temporary_session.get(Market, decision.market_id)
                    if market is None:
                        continue
                    session.add(
                        ReplayDecision(
                            run_id=replay.id,
                            market_key=market.market_key,
                            strategy_name=decision.strategy_name,
                            decision_time=decision.decision_time,
                            reason=decision.reason,
                            intents_json=decision.intents_json,
                            observations_json=decision.observations_json,
                        )
                    )

            replay.status = "completed"
            replay.completed_at = datetime.now(timezone.utc)
            replay.event_count = len(ordered)
            replay.market_count = len(
                {event.payload.market_id for event in ordered if event.event_type == "market"}
            )
            replay.decision_count = stats.decisions
            replay.actionable_decision_count = sum(
                1
                for decision in decisions
                if decision.reason == "actionable live M1 signal"
            )
            replay.orders_created = stats.orders_created
            replay.fills = stats.fills
            replay.settlements = stats.settlements
            replay.final_cash = final_cash
            replay.realized_pnl = realized_pnl
            replay.net_pnl = final_cash - self.settings.initial_cash
            replay.positions_json = json.dumps(positions)
            replay.summary_json = json.dumps(
                {
                    "execution_mode": "isolated-paper",
                    "real_execution": False,
                    "event_types": {
                        event_type: sum(1 for event in ordered if event.event_type == event_type)
                        for event_type in {event.event_type for event in ordered}
                    },
                }
            )
            session.flush()
            return ReplayExecutionResult(replay)
        except Exception as exc:
            replay.status = "failed"
            replay.completed_at = datetime.now(timezone.utc)
            replay.error = str(exc)[:2000]
            session.flush()
            raise
        finally:
            temporary_engine.dispose()
