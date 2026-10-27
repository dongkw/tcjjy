"""One runnable path: data source -> rule evaluation -> PostgreSQL."""

from __future__ import annotations

from datetime import date
from typing import Any

from .database import Database
from .fixtures import make_fixture
from .market import TencentDailyProvider
from .models import MarketData, validate_symbol
from .strategy import evaluate_trend


class ResearchService:
    def __init__(self, database: Database, provider: TencentDailyProvider | None = None) -> None:
        self.database = database
        self.provider = provider or TencentDailyProvider()

    def analyze(
        self, symbol: str, *, mode: str, limit: int = 120, end_date: date | None = None,
    ) -> dict[str, Any]:
        validate_symbol(symbol)
        if mode == "fixture":
            dataset = make_fixture(symbol=symbol, count=limit)
            if end_date is not None:
                visible = [bar for bar in dataset.bars if bar.trade_date <= end_date]
                if not visible:
                    raise ValueError("所选日期之前没有样例日线")
                dataset = MarketData(
                    symbol=dataset.symbol, name=dataset.name, source=dataset.source,
                    mode=dataset.mode, adjustment=dataset.adjustment,
                    fetched_at=dataset.fetched_at, bars=visible,
                )
        elif mode == "live":
            dataset = self.provider.fetch(symbol, limit=limit, end_date=end_date)
        else:
            raise ValueError("mode 仅支持 fixture 或 live")
        result = evaluate_trend(dataset.bars)
        run_id = self.database.save_analysis(dataset, result)
        saved = self.database.get_analysis(run_id)
        if saved is None:
            raise RuntimeError("研究记录保存后无法读取")
        return saved
