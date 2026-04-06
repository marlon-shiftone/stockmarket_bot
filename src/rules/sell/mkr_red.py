from core.models.enums import TrendColor
from core.models.rule_result import RuleResult
from core.models.strategy_context import StrategyFrame


class MKRRedRule:
    name = "sell.mkr_red"

    def evaluate(self, current: StrategyFrame, previous: StrategyFrame | None = None) -> RuleResult:
        passed = current.indicators.mkr_color == TrendColor.RED
        return RuleResult(
            name=self.name,
            passed=passed,
            reason="MKR is red" if passed else "MKR is not red",
        )
