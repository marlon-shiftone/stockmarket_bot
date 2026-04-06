from core.models.rule_result import RuleResult
from core.models.strategy_context import StrategyFrame


class TrendMeterAllRedRule:
    name = "sell.trend_meter_all_red"

    def evaluate(self, current: StrategyFrame, previous: StrategyFrame | None = None) -> RuleResult:
        passed = current.indicators.trend_meter_all_red
        return RuleResult(
            name=self.name,
            passed=passed,
            reason="Trend meter all red" if passed else "Trend meter not all red",
        )
