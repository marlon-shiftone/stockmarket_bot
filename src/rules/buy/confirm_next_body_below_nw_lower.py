from core.models.rule_result import RuleResult
from core.models.strategy_context import StrategyFrame


class ConfirmNextBodyBelowNWLowerRule:
    name = "buy.confirm_next_body_below_nw_lower"

    def evaluate(self, current: StrategyFrame, previous: StrategyFrame | None = None) -> RuleResult:
        if previous is None:
            return RuleResult(name=self.name, passed=False, reason="No previous candle")

        previous_passed = (
            previous.indicators.ha_open < previous.indicators.nw_lower
            and previous.indicators.ha_close < previous.indicators.nw_lower
        )
        current_passed = (
            current.indicators.ha_open < current.indicators.nw_lower
            and current.indicators.ha_close < current.indicators.nw_lower
        )
        passed = previous_passed and current_passed
        return RuleResult(
            name=self.name,
            passed=passed,
            reason="Two-candle confirmation below NW lower" if passed else "No two-candle confirmation",
        )
