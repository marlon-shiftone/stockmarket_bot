from core.models.enums import TrendColor
from core.models.rule_result import RuleResult
from core.models.strategy_context import StrategyFrame


class CloseBuyOnMKRRedRule:
    name = "exit.close_buy_on_mkr_red"

    def evaluate(self, current: StrategyFrame, previous: StrategyFrame | None = None) -> RuleResult:
        passed = current.indicators.mkr_color == TrendColor.RED
        return RuleResult(
            name=self.name,
            passed=passed,
            reason="Close buy: MKR turned red" if passed else "MKR not red",
        )
