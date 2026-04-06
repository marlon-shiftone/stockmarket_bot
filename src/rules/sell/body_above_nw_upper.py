from core.models.rule_result import RuleResult
from core.models.strategy_context import StrategyFrame


class BodyAboveNWUpperRule:
    name = "sell.body_above_nw_upper"

    def evaluate(self, current: StrategyFrame, previous: StrategyFrame | None = None) -> RuleResult:
        passed = (
            current.indicators.ha_open > current.indicators.nw_upper
            and current.indicators.ha_close > current.indicators.nw_upper
        )
        return RuleResult(
            name=self.name,
            passed=passed,
            reason="HA body above NW upper" if passed else "HA body not above NW upper",
        )
