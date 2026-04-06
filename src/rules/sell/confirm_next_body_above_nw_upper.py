from core.models.rule_result import RuleResult
from core.models.strategy_context import StrategyFrame


class ConfirmNextBodyAboveNWUpperRule:
    name = "sell.confirm_next_body_above_nw_upper"

    def evaluate(self, current: StrategyFrame, previous: StrategyFrame | None = None) -> RuleResult:
        if previous is None:
            return RuleResult(name=self.name, passed=False, reason="No previous candle")

        previous_passed = (
            previous.indicators.ha_open > previous.indicators.nw_upper
            and previous.indicators.ha_close > previous.indicators.nw_upper
        )
        current_passed = (
            current.indicators.ha_open > current.indicators.nw_upper
            and current.indicators.ha_close > current.indicators.nw_upper
        )
        passed = previous_passed and current_passed
        return RuleResult(
            name=self.name,
            passed=passed,
            reason="Two-candle confirmation above NW upper" if passed else "No two-candle confirmation",
        )
