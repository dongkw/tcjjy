"""Small, explicit market-data contracts shared by the V2 service."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, datetime


_SYMBOL = re.compile(r"(?:000|001|002|003|600|601|603|605)[0-9]{3}\Z")


def validate_symbol(symbol: str) -> str:
    """Accept six-digit ordinary Shanghai/Shenzhen main-board stock codes."""
    if not isinstance(symbol, str) or _SYMBOL.fullmatch(symbol) is None:
        raise ValueError("仅支持六位沪深主板股票代码，例如 000001、600519、601138")
    return symbol


@dataclass(frozen=True)
class DailyBar:
    trade_date: date
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None
    amount: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.trade_date, date) or isinstance(self.trade_date, datetime):
            raise ValueError("trade_date 必须是日期")
        for field in ("open", "high", "low", "close"):
            value = _number(getattr(self, field), field)
            if value <= 0:
                raise ValueError(f"{field} 必须大于零")
            object.__setattr__(self, field, value)
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close):
            raise ValueError("日线 high/low 未覆盖 open/close")
        if self.low > self.high:
            raise ValueError("日线 low 不能大于 high")
        for field in ("volume", "amount"):
            raw = getattr(self, field)
            if raw is not None:
                value = _number(raw, field)
                if value < 0:
                    raise ValueError(f"{field} 不能为负数")
                object.__setattr__(self, field, value)


@dataclass(frozen=True)
class MarketData:
    symbol: str
    name: str
    source: str
    mode: str
    adjustment: str
    fetched_at: datetime
    bars: list[DailyBar]

    def __post_init__(self) -> None:
        validate_symbol(self.symbol)
        if not self.name or not self.source:
            raise ValueError("行情必须包含名称和来源")
        if self.mode not in {"live", "fixture"}:
            raise ValueError("行情 mode 必须是 live 或 fixture")
        if self.adjustment not in {"qfq", "none"}:
            raise ValueError("不支持的复权方式")
        if not isinstance(self.fetched_at, datetime) or self.fetched_at.utcoffset() is None:
            raise ValueError("fetched_at 必须包含时区")
        if not self.bars:
            raise ValueError("行情日线不能为空")
        if any(not isinstance(bar, DailyBar) for bar in self.bars):
            raise ValueError("bars 必须包含 DailyBar")
        dates = [bar.trade_date for bar in self.bars]
        if dates != sorted(set(dates)):
            raise ValueError("日线日期必须递增且不重复")


def _number(raw: object, field: str) -> float:
    if isinstance(raw, (bool, str, bytes)):
        raise ValueError(f"{field} 必须是有限数字")
    try:
        value = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field} 必须是有限数字") from exc
    if not math.isfinite(value):
        raise ValueError(f"{field} 必须是有限数字")
    return value
