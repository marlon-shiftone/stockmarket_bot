from core.models.enums import TrendColor
from core.models.rule_result import RuleResult
from core.models.strategy_context import StrategyFrame


class MKRGreenRule:
    name = "buy.mkr_green"

    def evaluate(self, current: StrategyFrame, previous: StrategyFrame | None = None) -> RuleResult:
        passed = current.indicators.mkr_color == TrendColor.GREEN
        return RuleResult(
            name=self.name,
            passed=passed,
            reason="MKR is green" if passed else "MKR is not green",
        )
