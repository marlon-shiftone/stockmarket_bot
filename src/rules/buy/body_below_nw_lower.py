from core.models.rule_result import RuleResult
from core.models.strategy_context import StrategyFrame


class BodyBelowNWLowerRule:
    name = "buy.body_below_nw_lower"

    def evaluate(self, current: StrategyFrame, previous: StrategyFrame | None = None) -> RuleResult:
        passed = (
            current.indicators.ha_open < current.indicators.nw_lower
            and current.indicators.ha_close < current.indicators.nw_lower
        )
        return RuleResult(
            name=self.name,
            passed=passed,
            reason="HA body below NW lower" if passed else "HA body not below NW lower",
        )
