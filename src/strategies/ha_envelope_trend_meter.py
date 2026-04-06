from core.models.enums import PositionSide, SignalType
from core.models.position import Position
from core.models.rule_result import RuleResult
from core.models.signal import Signal
from core.models.strategy_context import StrategyFrame
from rules.buy.body_below_nw_lower import BodyBelowNWLowerRule
from rules.buy.confirm_next_body_below_nw_lower import ConfirmNextBodyBelowNWLowerRule
from rules.buy.mkr_green import MKRGreenRule
from rules.buy.trend_meter_all_green import TrendMeterAllGreenRule
from rules.exit.close_buy_on_mkr_red import CloseBuyOnMKRRedRule
from rules.exit.close_sell_on_mkr_green import CloseSellOnMKRGreenRule
from rules.sell.body_above_nw_upper import BodyAboveNWUpperRule
from rules.sell.confirm_next_body_above_nw_upper import ConfirmNextBodyAboveNWUpperRule
from rules.sell.mkr_red import MKRRedRule
from rules.sell.trend_meter_all_red import TrendMeterAllRedRule


class HAEnvelopeTrendMeterStrategy:
    def __init__(
        self,
        *,
        require_confirmation: bool = True,
        require_trend_meter: bool = True,
        require_mkr_alignment: bool = True,
    ) -> None:
        self.buy_rules = [BodyBelowNWLowerRule()]
        if require_confirmation:
            self.buy_rules.append(ConfirmNextBodyBelowNWLowerRule())
        if require_mkr_alignment:
            self.buy_rules.append(MKRGreenRule())
        if require_trend_meter:
            self.buy_rules.append(TrendMeterAllGreenRule())

        self.sell_rules = [BodyAboveNWUpperRule()]
        if require_confirmation:
            self.sell_rules.append(ConfirmNextBodyAboveNWUpperRule())
        if require_mkr_alignment:
            self.sell_rules.append(MKRRedRule())
        if require_trend_meter:
            self.sell_rules.append(TrendMeterAllRedRule())

        self.close_buy_rule = CloseBuyOnMKRRedRule()
        self.close_sell_rule = CloseSellOnMKRGreenRule()

    def buy_rule_names(self) -> list[str]:
        return [rule.name for rule in self.buy_rules]

    def sell_rule_names(self) -> list[str]:
        return [rule.name for rule in self.sell_rules]

    @staticmethod
    def _evaluate_rules(
        rules: list,
        current: StrategyFrame,
        previous: StrategyFrame | None,
    ) -> list[RuleResult]:
        return [rule.evaluate(current=current, previous=previous) for rule in rules]

    @staticmethod
    def _build_signal(
        signal_type: SignalType,
        current: StrategyFrame,
        results: list[RuleResult],
    ) -> Signal:
        passed_or_context_reasons = [f"{result.name}: {result.reason}" for result in results]
        return Signal(
            signal_type=signal_type,
            symbol=current.candle.symbol,
            timestamp=current.candle.timestamp,
            price=current.candle.close,
            reasons=passed_or_context_reasons,
            indicator_snapshot=current.indicators,
        )

    def generate_signal(
        self,
        current: StrategyFrame,
        previous: StrategyFrame | None,
        position: Position | None,
    ) -> Signal:
        if position is not None:
            if position.side == PositionSide.LONG:
                result = self.close_buy_rule.evaluate(current=current, previous=previous)
                if result.passed:
                    return self._build_signal(SignalType.CLOSE_BUY, current, [result])
                return self._build_signal(SignalType.NONE, current, [result])

            if position.side == PositionSide.SHORT:
                result = self.close_sell_rule.evaluate(current=current, previous=previous)
                if result.passed:
                    return self._build_signal(SignalType.CLOSE_SELL, current, [result])
                return self._build_signal(SignalType.NONE, current, [result])

        buy_results = self._evaluate_rules(self.buy_rules, current, previous)
        sell_results = self._evaluate_rules(self.sell_rules, current, previous)

        buy_passed = all(result.passed for result in buy_results)
        sell_passed = all(result.passed for result in sell_results)

        if buy_passed and not sell_passed:
            return self._build_signal(SignalType.BUY, current, buy_results)
        if sell_passed and not buy_passed:
            return self._build_signal(SignalType.SELL, current, sell_results)

        reasons = buy_results + sell_results
        if buy_passed and sell_passed:
            reasons.append(
                RuleResult(
                    name="strategy.conflict",
                    passed=False,
                    reason="Buy and sell triggered simultaneously",
                )
            )
        return self._build_signal(SignalType.NONE, current, reasons)
