from decimal import Decimal

import pytest

from app.execution import DisabledLiveExecutionAdapter, ExecutionIntent, LiveExecutionDisabled


def test_live_execution_is_explicitly_disabled() -> None:
    intent = ExecutionIntent(1, "YES", "BUY", Decimal("0.97"), Decimal("1"), "test")
    with pytest.raises(LiveExecutionDisabled):
        DisabledLiveExecutionAdapter().submit(intent)
