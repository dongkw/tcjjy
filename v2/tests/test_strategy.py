from datetime import date, timedelta

import pytest

from trader_v2.models import DailyBar
from trader_v2.strategy import evaluate_trend


def make_bars(closes: list[float], half_range: float = 1) -> list[DailyBar]:
    return [
        DailyBar(
            trade_date=date(2026, 1, 1) + timedelta(days=index),
            open=close,
            high=close + half_range,
            low=close - half_range,
            close=close,
        )
        for index, close in enumerate(closes)
    ]


def rule(result: dict, rule_id: str) -> dict:
    return next(item for item in result["rules"] if item["rule_id"] == rule_id)


def test_rising_prices_have_hand_calculable_indicators():
    result = evaluate_trend(make_bars([float(price) for price in range(100, 161)]))
    indicators = result["indicators"]

    # The last 20 closes are 141..160; the last 60 are 101..160.
    assert indicators["ma20"] == 150.5
    assert indicators["ma60"] == 130.5
    assert indicators["previous_ma20"] == 149.5
    assert indicators["previous_ma60"] == 129.5
    assert indicators["change_20d_pct"] == pytest.approx((160 / 140 - 1) * 100)
    assert indicators["atr14_pct"] == 1.25
    assert indicators["high_20d"] == 161
    assert indicators["low_20d"] == 140
    assert result["status"] == "PASS"
    assert result["missing_fields"] == []
    assert "未评估基本面" in result["summary"]
    assert result["strategy_version"] == "1.0.0"


@pytest.mark.parametrize("count", [0, 14, 20, 60])
def test_not_enough_history_blocks_a_full_conclusion(count):
    result = evaluate_trend(make_bars([100.0] * count))

    assert result["status"] == "BLOCKED"
    assert f"daily_bars:need_61:have_{count}" in result["missing_fields"]
    assert "ma60_slope_up" in result["missing_fields"]
    assert rule(result, "TF_MA60_SLOPE")["status"] == "BLOCKED"
    assert result["indicators"]["ma60_slope_up"] is None


def test_declining_prices_are_watch_without_an_order_instruction():
    result = evaluate_trend(make_bars([float(price) for price in range(160, 99, -1)]))

    assert result["status"] == "WATCH"
    assert rule(result, "TF_PRICE_MA20")["status"] == "FAIL"
    assert rule(result, "TF_MA60_SLOPE")["value"] is False
    assert "action" not in result
    assert "quantity" not in result


def test_atr_counts_an_overnight_gap_rather_than_only_intraday_range():
    result = evaluate_trend(make_bars([100.0] * 60 + [110.0]))

    # Thirteen ordinary ranges of 2, followed by a true range of 111 - 100.
    expected = (13 * 2 + 11) / 14 / 110 * 100
    assert result["indicators"]["atr14_pct"] == pytest.approx(expected)


@pytest.mark.parametrize("last_close, expected", [(130.0, "PASS"), (131.0, "WARN"), (181.0, "FAIL")])
def test_twenty_day_chase_thresholds(last_close, expected):
    result = evaluate_trend(make_bars([100.0] * 60 + [last_close]))

    assert rule(result, "TF_CHASE_RISK")["status"] == expected
    if expected != "PASS":
        assert result["status"] == "WATCH"


@pytest.mark.parametrize("range_pct, expected", [(5.0, "PASS"), (6.0, "WARN"), (8.0, "WARN"), (9.0, "FAIL")])
def test_atr_thresholds_in_percent(range_pct, expected):
    result = evaluate_trend(make_bars([100.0] * 61, half_range=range_pct / 2))

    assert result["indicators"]["atr14_pct"] == range_pct
    assert rule(result, "TF_VOLATILITY")["status"] == expected


@pytest.mark.parametrize("duplicate", [False, True])
def test_dates_are_not_silently_sorted_or_deduplicated(duplicate):
    bars = make_bars([100.0] * 61)
    if duplicate:
        bars[-1] = bars[-2]
    else:
        bars[-2], bars[-1] = bars[-1], bars[-2]

    with pytest.raises(ValueError, match="distinct trade dates"):
        evaluate_trend(bars)


@pytest.mark.parametrize("bad_price", [float("nan"), float("inf"), 0.0, -1.0])
def test_invalid_prices_cannot_produce_a_trend_conclusion(bad_price):
    bars = make_bars([100.0] * 61)
    # Exercise the strategy boundary even if a caller bypasses dataclass setup.
    object.__setattr__(bars[-1], "close", bad_price)

    with pytest.raises(ValueError, match="finite and positive"):
        evaluate_trend(bars)
