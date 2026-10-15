from decimal import Decimal

from app.queue import QueueModel, QueueState, consume_queue, initial_queue_ahead


def test_queue_models_make_assumptions_explicit() -> None:
    visible = Decimal("10")
    assert initial_queue_ahead(QueueModel.OPTIMISTIC, visible) == Decimal("0")
    assert initial_queue_ahead(QueueModel.BASELINE, visible) == Decimal("10")
    assert initial_queue_ahead(QueueModel.CONSERVATIVE, visible) == Decimal("20")


def test_trade_consumes_ahead_volume_before_our_fill() -> None:
    state = QueueState(QueueModel.BASELINE, Decimal("5"), Decimal("5"))

    after_queue, first_fill = consume_queue(state, Decimal("3"))
    assert first_fill == Decimal("0")
    assert after_queue.remaining_ahead == Decimal("2")

    after_queue, second_fill = consume_queue(after_queue, Decimal("4"))
    assert second_fill == Decimal("2")
    assert after_queue.remaining_ahead == Decimal("0")
