from core.models.enums import TrendColor
from core.models.rule_result import RuleResult
from core.models.strategy_context import StrategyFrame


class CloseSellOnMKRGreenRule:
    name = "exit.close_sell_on_mkr_green"

    def evaluate(self, current: StrategyFrame, previous: StrategyFrame | None = None) -> RuleResult:
        passed = current.indicators.mkr_color == TrendColor.GREEN
        return RuleResult(
            name=self.name,
            passed=passed,
            reason="Close sell: MKR turned green" if passed else "MKR not green",
        )
