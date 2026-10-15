"""Glue between observable strategy decisions and paper execution."""

import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from .execution import ExecutionIntent, PaperExecutionAdapter
from .models import Market, StrategyDecision
from .paper import PaperTrading
from .strategy import CurrentBook, M1Strategy, StrategyMarket


class StrategyRunner:
    def __init__(self, session: Session, strategy: M1Strategy, broker: PaperTrading) -> None:
        self.session = session
        self.strategy = strategy
        self.execution = PaperExecutionAdapter(session, broker)

    def evaluate(self, market: Market, book: CurrentBook, now: datetime) -> StrategyDecision:
        decision = self.strategy.decide(StrategyMarket(market.market_key, market.end_time), book, now)
        record = StrategyDecision(
            market_id=market.id,
            strategy_name=decision.strategy_name,
            decision_time=decision.decision_time.astimezone(timezone.utc),
            reason=decision.reason,
            intents_json=json.dumps([intent.__dict__ for intent in decision.intents], default=str),
            observations_json=json.dumps(decision.observations),
        )
        self.session.add(record)
        self.session.flush()
        for intent in decision.intents:
            self.execution.submit(
                ExecutionIntent(market.id, intent.token, intent.side, intent.price, intent.quantity, intent.reason),
                now=now,
            )
        return record
