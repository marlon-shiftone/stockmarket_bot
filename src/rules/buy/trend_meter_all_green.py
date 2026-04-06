from core.models.rule_result import RuleResult
from core.models.strategy_context import StrategyFrame


class TrendMeterAllGreenRule:
    name = "buy.trend_meter_all_green"

    def evaluate(self, current: StrategyFrame, previous: StrategyFrame | None = None) -> RuleResult:
        passed = current.indicators.trend_meter_all_green
        return RuleResult(
            name=self.name,
            passed=passed,
            reason="Trend meter all green" if passed else "Trend meter not all green",
        )
