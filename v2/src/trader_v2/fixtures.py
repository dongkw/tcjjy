"""Deterministic synthetic sample bars; no real-market performance claims."""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone

from .models import DailyBar, MarketData, validate_symbol


def make_fixture(symbol: str = "601138", count: int = 90) -> MarketData:
    """Build synthetic weekday bars ending 2026-10-23, not an exchange calendar."""
    validate_symbol(symbol)
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 1000:
        raise ValueError("样例日线 count 必须是 1～1000 的整数")
    dates: list[date] = []
    day = date(2026, 10, 23)
    while len(dates) < count:
        if day.weekday() < 5:
            dates.append(day)
        day -= timedelta(days=1)
    dates.reverse()

    bars: list[DailyBar] = []
    base = 18.0 + int(symbol[-3:]) / 100
    previous_close = base
    for index, day in enumerate(dates):
        close = round(base + index * 0.06 + math.sin(index / 3) * 0.45, 4)
        opening = round(previous_close * (1 + math.sin(index) * 0.002), 4)
        volume = float(1_000_000 + index * 3000 + int(math.sin(index / 4) * 80_000))
        bars.append(DailyBar(
            trade_date=day,
            open=opening,
            high=round(max(opening, close) * 1.009, 4),
            low=round(min(opening, close) * 0.991, 4),
            close=close,
            volume=volume,
            amount=round(volume * (opening + close) / 2, 2),
        ))
        previous_close = close
    return MarketData(
        symbol=symbol,
        name=f"合成样例-{symbol}",
        source="fixture",
        mode="fixture",
        adjustment="none",
        fetched_at=datetime(2026, 10, 23, 8, tzinfo=timezone.utc),
        bars=bars,
    )
