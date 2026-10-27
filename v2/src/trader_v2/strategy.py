"""A transparent daily trend baseline, without account or trading side effects."""

from __future__ import annotations

from math import fsum, isfinite
from typing import Any

from .models import DailyBar


STRATEGY_ID = "trend-following-lite"
STRATEGY_VERSION = "1.0.0"
MINIMUM_BARS = 61
TECHNICAL_SCOPE = "仅描述技术趋势，未评估基本面、估值或可执行交易条件。"


def evaluate_trend(bars: list[DailyBar]) -> dict[str, Any]:
    """Evaluate ascending, distinct daily bars; reject malformed price inputs.

    MA slopes compare today's average with the previous day's average. ATR14
    uses a simple average of true ranges, including overnight gaps. Both are
    intentionally explicit rather than delegated to an opaque score.
    """
    _validate_bars(bars)
    closes = [bar.close for bar in bars]
    ma20 = _mean(closes, 20)
    ma60 = _mean(closes, 60)
    previous_ma20 = _mean(closes[:-1], 20)
    previous_ma60 = _mean(closes[:-1], 60)
    close = closes[-1] if closes else None
    change_20d_pct = (close - closes[-21]) / closes[-21] * 100 if len(closes) >= 21 else None
    atr14_pct = _atr14_pct(bars)

    indicators: dict[str, Any] = {
        "bar_count": len(bars),
        "source_bar_end_date": bars[-1].trade_date.isoformat() if bars else None,
        "close": close,
        "ma20": ma20,
        "ma60": ma60,
        "previous_ma20": previous_ma20,
        "previous_ma60": previous_ma60,
        "above_ma20": close > ma20 if close is not None and ma20 is not None else None,
        "above_ma60": close > ma60 if close is not None and ma60 is not None else None,
        "ma20_slope_up": ma20 > previous_ma20 if previous_ma20 is not None else None,
        "ma60_slope_up": ma60 > previous_ma60 if previous_ma60 is not None else None,
        "change_20d_pct": change_20d_pct,
        "atr14_pct": atr14_pct,
        "high_20d": max(bar.high for bar in bars[-20:]) if len(bars) >= 20 else None,
        "low_20d": min(bar.low for bar in bars[-20:]) if len(bars) >= 20 else None,
    }
    rules = [
        _boolean_rule("TF_PRICE_MA20", "收盘价站上 MA20", indicators["above_ma20"]),
        _boolean_rule("TF_PRICE_MA60", "收盘价站上 MA60", indicators["above_ma60"]),
        _boolean_rule("TF_MA20_SLOPE", "MA20 方向向上", indicators["ma20_slope_up"]),
        _boolean_rule("TF_MA60_SLOPE", "MA60 方向向上", indicators["ma60_slope_up"]),
        _ceiling_rule("TF_CHASE_RISK", "20 日涨幅", change_20d_pct, 30, 80),
        _ceiling_rule("TF_VOLATILITY", "ATR14 占收盘价百分比", atr14_pct, 5, 8),
    ]
    required = (
        "ma20", "ma60", "ma20_slope_up", "ma60_slope_up", "above_ma20",
        "above_ma60", "change_20d_pct", "atr14_pct", "high_20d", "low_20d",
    )
    missing_fields = [name for name in required if indicators[name] is None]
    if len(bars) < MINIMUM_BARS:
        missing_fields.insert(0, f"daily_bars:need_{MINIMUM_BARS}:have_{len(bars)}")

    if missing_fields:
        status = "BLOCKED"
        summary = f"日线不足，至少需要 {MINIMUM_BARS} 根，当前 {len(bars)} 根，暂不形成完整趋势结论。"
    elif all(rule["status"] == "PASS" for rule in rules):
        status = "PASS"
        summary = "价格与均线方向满足当前趋势规则，涨幅与波动未超过本规则的观察阈值。"
    else:
        status = "WATCH"
        summary = "部分趋势条件未满足，或涨幅、波动已触发观察条件。"

    return {
        "strategy_id": STRATEGY_ID,
        "strategy_version": STRATEGY_VERSION,
        "status": status,
        "indicators": {key: _rounded(value) for key, value in indicators.items()},
        "rules": rules,
        "missing_fields": missing_fields,
        "summary": f"{summary}{TECHNICAL_SCOPE}",
    }


def _validate_bars(bars: list[DailyBar]) -> None:
    for index, bar in enumerate(bars):
        if index and bar.trade_date <= bars[index - 1].trade_date:
            raise ValueError("daily bars must have distinct trade dates in ascending order")
        prices = (bar.open, bar.high, bar.low, bar.close)
        if any(not isfinite(value) or value <= 0 for value in prices):
            raise ValueError("daily bar prices must be finite and positive")
        if bar.low > min(bar.open, bar.close) or bar.high < max(bar.open, bar.close) or bar.high < bar.low:
            raise ValueError("daily bar OHLC values are inconsistent")


def _mean(values: list[float], window: int) -> float | None:
    return fsum(values[-window:]) / window if len(values) >= window else None


def _atr14_pct(bars: list[DailyBar]) -> float | None:
    if len(bars) < 15:
        return None
    true_ranges = []
    for index in range(len(bars) - 14, len(bars)):
        bar, previous_close = bars[index], bars[index - 1].close
        true_ranges.append(max(bar.high - bar.low, abs(bar.high - previous_close), abs(bar.low - previous_close)))
    return fsum(true_ranges) / 14 / bars[-1].close * 100


def _boolean_rule(rule_id: str, label: str, value: bool | None) -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        "label": label,
        "status": "BLOCKED" if value is None else "PASS" if value else "FAIL",
        "value": value,
        "threshold": True,
        "reason": "缺少计算所需日线" if value is None else label if value else f"未满足：{label}",
    }


def _ceiling_rule(
    rule_id: str, label: str, value: float | None, warn_above: float, fail_above: float,
) -> dict[str, Any]:
    if value is None:
        status, reason = "BLOCKED", "缺少计算所需日线"
    elif value > fail_above:
        status, reason = "FAIL", f"{label}超过 {fail_above}%，超出本规则范围"
    elif value > warn_above:
        status, reason = "WARN", f"{label}超过 {warn_above}%，需要继续观察"
    else:
        status, reason = "PASS", f"{label}未超过 {warn_above}%"
    return {
        "rule_id": rule_id,
        "label": label,
        "status": status,
        "value": _rounded(value),
        "threshold": {"warn_above_pct": warn_above, "fail_above_pct": fail_above},
        "reason": reason,
    }


def _rounded(value: Any) -> Any:
    return round(value, 6) if isinstance(value, float) else value
