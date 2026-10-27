"""Tencent daily bars, with explicit source and data-availability boundaries."""

from __future__ import annotations

import math
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import requests

from .models import DailyBar, MarketData, validate_symbol


TENCENT_DAILY_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
_SHANGHAI = ZoneInfo("Asia/Shanghai")


class MarketDataError(RuntimeError):
    """The configured source did not supply usable market data."""


class TencentDailyProvider:
    """Daily OHLC are CNY/share; volume is shares; unavailable amount is None.

    Tencent's daily endpoint returns volume in lots of 100 shares. Its current
    day is removed before Shanghai 15:00. This is a daily research adapter, not
    a live execution-price feed or a complete exchange trading calendar.
    """

    def __init__(self, timeout: float = 15) -> None:
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or not 0 < timeout <= 120
        ):
            raise ValueError("行情请求超时必须在 0～120 秒之间")
        self.timeout = timeout

    def fetch(self, symbol: str, limit: int = 120, end_date: date | None = None) -> MarketData:
        validate_symbol(symbol)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 20 <= limit <= 640:
            raise ValueError("腾讯日线 limit 必须是 20～640 的整数")
        now = _now_shanghai()
        if end_date is not None and (
            not isinstance(end_date, date) or isinstance(end_date, datetime)
        ):
            raise ValueError("end_date 必须是日期")
        if end_date is not None and end_date > now.date():
            raise ValueError("end_date 不能晚于今天")
        cutoff = end_date or now.date()
        if cutoff == now.date() and now.time() < time(15):
            cutoff -= timedelta(days=1)
        security = ("sh" if symbol.startswith("6") else "sz") + symbol
        try:
            response = requests.get(
                TENCENT_DAILY_URL,
                params={"param": f"{security},day,,{cutoff.isoformat()},{limit},qfq"},
                headers={"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"},
                timeout=self.timeout,
            )
            response.raise_for_status()
            raw = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise MarketDataError("腾讯日线请求失败或未返回有效 JSON") from exc

        if not isinstance(raw, dict) or isinstance(raw.get("code"), bool) or raw.get("code") not in (0, "0"):
            raise MarketDataError("腾讯日线返回失败状态")
        data = raw.get("data")
        node = data.get(security) if isinstance(data, dict) else None
        if not isinstance(node, dict):
            raise MarketDataError(f"腾讯日线缺少股票 {symbol} 的数据")
        rows = node.get("qfqday")
        adjustment = "qfq"
        if rows is None or rows == []:
            rows = node.get("day")
            adjustment = "none"
        if not isinstance(rows, list) or not rows:
            raise MarketDataError(f"腾讯日线未返回股票 {symbol} 的有效日线")

        bars: list[DailyBar] = []
        try:
            for row in rows:
                if not isinstance(row, list) or len(row) < 6:
                    raise ValueError("日线行格式不正确")
                trade_date = date.fromisoformat(str(row[0]))
                if trade_date > cutoff:
                    continue
                bars.append(_parse_bar(row, trade_date))
            bars.sort(key=lambda bar: bar.trade_date)
            bars = bars[-limit:]
            quote = node.get("qt")
            fields = quote.get(security) if isinstance(quote, dict) else None
            name = str(fields[1]) if isinstance(fields, list) and len(fields) > 1 and fields[1] else symbol
            return MarketData(
                symbol=symbol,
                name=name,
                source="tencent",
                mode="live",
                adjustment=adjustment,
                fetched_at=now.astimezone(timezone.utc),
                bars=bars,
            )
        except (ValueError, TypeError, OverflowError, IndexError) as exc:
            raise MarketDataError(f"腾讯日线数据无效：{exc}") from exc


def _parse_bar(row: list[Any], trade_date: date) -> DailyBar:
    # [date, open, close, high, low, volume(lots), ...]; no reliable amount here.
    if any(isinstance(value, bool) for value in row[1:6]):
        raise ValueError("日线价格和成交量必须是数字")
    return DailyBar(
        trade_date=trade_date,
        open=float(row[1]),
        close=float(row[2]),
        high=float(row[3]),
        low=float(row[4]),
        volume=float(row[5]) * 100,
        amount=None,
    )


def _now_shanghai() -> datetime:
    return datetime.now(_SHANGHAI)
