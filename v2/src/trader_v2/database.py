"""PostgreSQL storage for the first runnable V2 research workflow."""

from __future__ import annotations

from importlib.resources import files
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .models import MarketData, validate_symbol


SCHEMA_VERSION = 4


class DatabaseNotReadyError(RuntimeError):
    """The reachable database does not contain the current V2 schema."""

_ANALYSIS_SELECT = """
    SELECT
        a.id::text AS id,
        s.id::text AS snapshot_id,
        s.symbol, s.name, s.mode, s.source, s.adjustment, s.fetched_at,
        s.first_trade_date, s.last_trade_date, s.bar_count,
        a.created_at, a.strategy_id, a.strategy_version, a.status,
        a.summary, a.missing_fields, a.indicators, a.rules
    FROM analysis_runs AS a
    JOIN market_snapshots AS s ON s.id = a.snapshot_id
"""


class Database:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def _connect(self) -> psycopg.Connection[dict[str, Any]]:
        return psycopg.connect(self._dsn, connect_timeout=3, row_factory=dict_row)

    def initialize(self) -> None:
        """Install pgvector and create the initial tables without dropping data."""
        migrations = sorted(files("trader_v2").joinpath("sql").iterdir(), key=lambda entry: entry.name)
        with self._connect() as conn:
            for migration in migrations:
                if migration.name.endswith(".sql"):
                    conn.execute(migration.read_text(encoding="utf-8"), prepare=False)

    def health(self) -> dict[str, Any]:
        """Expose database readiness facts, never connection credentials."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT current_database() AS database,
                       (SELECT extversion FROM pg_extension WHERE extname = 'vector')
                           AS pgvector_version,
                       (SELECT max(version) FROM schema_migrations) AS schema_version
                """
            ).fetchone()
        assert row is not None
        if not row["pgvector_version"] or row["schema_version"] != SCHEMA_VERSION:
            raise DatabaseNotReadyError("数据库尚未就绪，请运行 trader-v2 init-db 并检查 schema 版本。")
        return dict(row)

    def save_analysis(self, data: MarketData, result: dict[str, Any]) -> str:
        """Save source metadata, the exact input bars, and their rule result."""
        snapshot_id, run_id = uuid4(), uuid4()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO market_snapshots (
                    id, symbol, name, mode, source, adjustment, fetched_at,
                    first_trade_date, last_trade_date, bar_count
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    snapshot_id, data.symbol, data.name, data.mode, data.source,
                    data.adjustment, data.fetched_at, data.bars[0].trade_date,
                    data.bars[-1].trade_date, len(data.bars),
                ),
            )
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO daily_bars (
                        snapshot_id, trade_date, open, high, low, close, volume, amount
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    [
                        (
                            snapshot_id, bar.trade_date, bar.open, bar.high, bar.low,
                            bar.close, bar.volume, bar.amount,
                        )
                        for bar in data.bars
                    ],
                )
            conn.execute(
                """
                INSERT INTO analysis_runs (
                    id, snapshot_id, strategy_id, strategy_version, status,
                    summary, missing_fields, indicators, rules
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    run_id, snapshot_id, result["strategy_id"], result["strategy_version"],
                    result["status"], result["summary"], result["missing_fields"],
                    Jsonb(result["indicators"]), Jsonb(result["rules"]),
                ),
            )
        return str(run_id)

    def get_analysis(self, run_id: str) -> dict[str, Any] | None:
        parsed_id = UUID(run_id)
        with self._connect() as conn:
            return conn.execute(_ANALYSIS_SELECT + " WHERE a.id = %s", (parsed_id,)).fetchone()

    def list_analyses(
        self, symbol: str | None = None, mode: str | None = None, limit: int = 20,
    ) -> list[dict[str, Any]]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("limit 必须是 1～100 的整数")
        filters: list[str] = []
        params: list[Any] = []
        if symbol is not None:
            filters.append("s.symbol = %s")
            params.append(validate_symbol(symbol))
        if mode is not None:
            if mode not in {"live", "fixture"}:
                raise ValueError("mode 必须是 live 或 fixture")
            filters.append("s.mode = %s")
            params.append(mode)
        query = _ANALYSIS_SELECT
        if filters:
            query += " WHERE " + " AND ".join(filters)
        query += " ORDER BY a.created_at DESC, a.id DESC LIMIT %s"
        params.append(limit)
        with self._connect() as conn:
            return conn.execute(query, params).fetchall()

    def get_watchlist(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            return conn.execute("SELECT symbol, name FROM watchlist ORDER BY symbol").fetchall()
