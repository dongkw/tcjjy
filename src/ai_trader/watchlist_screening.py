"""Transparent rule-based pre-market screening for selected watchlist symbols."""

from __future__ import annotations

import json
from typing import Any

from .portfolio import compact_now, now_iso


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _category(score: float, warnings: list[str], data_missing: bool) -> str:
    if data_missing:
        return "DATA_GAP"
    if any(item.startswith("RISK") for item in warnings):
        return "RISK"
    if score >= 3:
        return "CANDIDATE"
    if score >= 1:
        return "WATCH"
    return "NEUTRAL"


def evaluate_quote(row: dict[str, Any], position_symbols: set[str]) -> dict[str, Any]:
    symbol = str(row.get("symbol") or "")
    price = _as_float(row.get("price"))
    pct_change = _as_float(row.get("pct_change"))
    pe_ttm = _as_float(row.get("pe_ttm"))
    pb = _as_float(row.get("pb"))
    ma20 = _as_float(row.get("ma20"))
    ma60 = _as_float(row.get("ma60"))
    change_20d = _as_float(row.get("change_20d_pct"))
    score = 0.0
    rules: list[str] = []
    warnings: list[str] = []

    data_missing = price is None or row.get("trade_date") in (None, "")
    if data_missing:
        warnings.append("DATA_MISSING: 缺少价格或交易日")

    if price is not None and ma20 is not None and price >= ma20:
        score += 1
        rules.append("TREND_PRICE_ABOVE_MA20: 价格在 MA20 上方")
    if ma20 is not None and ma60 is not None and ma20 >= ma60:
        score += 1
        rules.append("TREND_MA20_ABOVE_MA60: MA20 不低于 MA60")
    if change_20d is not None:
        if 3 <= change_20d <= 25:
            score += 1
            rules.append("MOMENTUM_20D_HEALTHY: 20 日涨幅处于可观察区间")
        elif change_20d > 35:
            warnings.append("RISK_CHASE_HIGH_20D: 20 日涨幅过高，谨慎追高")
        elif change_20d < -15:
            warnings.append("RISK_WEAK_20D: 20 日跌幅较大，先观察风险")
    if pct_change is not None:
        if pct_change > 7:
            warnings.append("RISK_BIG_UP_DAY: 当日涨幅较大，避免情绪追高")
        elif pct_change < -7:
            warnings.append("RISK_BIG_DOWN_DAY: 当日跌幅较大，确认是否有利空")
    if pe_ttm is not None:
        if pe_ttm <= 0:
            warnings.append("RISK_NEGATIVE_PE: PE 为负或无效")
        elif pe_ttm > 80:
            warnings.append("RISK_HIGH_PE: PE 较高")
    if pb is not None and pb > 10:
        warnings.append("RISK_HIGH_PB: PB 较高")

    is_position = symbol in position_symbols
    if is_position:
        score += 0.5
        rules.append("POSITION_HOLDING: 当前持仓，优先关注")

    category = _category(score, warnings, data_missing)
    summary_parts = []
    if rules:
        summary_parts.append("；".join(rules[:2]))
    if warnings:
        summary_parts.append("风险：" + "；".join(warnings[:2]))
    summary = "；".join(summary_parts) or "未触发明显规则"
    return {
        "symbol": symbol,
        "name": row.get("name"),
        "category": category,
        "score": round(score, 2),
        "price": price,
        "pct_change": pct_change,
        "pe_ttm": pe_ttm,
        "pb": pb,
        "ma20": ma20,
        "ma60": ma60,
        "change_20d_pct": change_20d,
        "trade_date": row.get("trade_date"),
        "is_position": 1 if is_position else 0,
        "matched_rules": rules,
        "warnings": warnings,
        "summary": summary,
    }


def create_screen_run(conn: Any, *, tab_id: str, codes: list[str], params: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized_codes = []
    for code in codes:
        value = "".join(ch for ch in str(code).strip() if ch.isdigit())[:6]
        if value and value not in normalized_codes:
            normalized_codes.append(value)
    if not normalized_codes:
        raise ValueError("no symbols selected")

    placeholders = ",".join("?" for _ in normalized_codes)
    quote_rows = [
        dict(row)
        for row in conn.execute(
            f"""
            SELECT symbol, name, trade_date, price, pct_change, pe_ttm, pb,
                   ma20, ma60, change_20d_pct
            FROM market_quotes
            WHERE symbol IN ({placeholders})
            """,
            tuple(normalized_codes),
        ).fetchall()
    ]
    quote_by_symbol = {row["symbol"]: row for row in quote_rows}
    item_names = {
        row["symbol"]: row["name"]
        for row in conn.execute(
            f"SELECT symbol, name FROM watchlist_items WHERE symbol IN ({placeholders})",
            tuple(normalized_codes),
        ).fetchall()
    }
    position_symbols = {
        row["symbol"]
        for row in conn.execute(
            "SELECT symbol FROM positions WHERE COALESCE(position_status, 'ACTIVE') != 'CLOSED'"
        ).fetchall()
    }
    tab = conn.execute("SELECT name FROM watchlist_tabs WHERE tab_id=?", (tab_id,)).fetchone()
    created_at = now_iso()
    run_id = f"screen_{compact_now()}"
    results = []
    for symbol in normalized_codes:
        row = quote_by_symbol.get(symbol) or {"symbol": symbol, "name": item_names.get(symbol)}
        if not row.get("name"):
            row["name"] = item_names.get(symbol)
        results.append(evaluate_quote(row, position_symbols))

    counts = {
        "CANDIDATE": sum(1 for item in results if item["category"] == "CANDIDATE"),
        "WATCH": sum(1 for item in results if item["category"] == "WATCH"),
        "RISK": sum(1 for item in results if item["category"] == "RISK"),
        "DATA_GAP": sum(1 for item in results if item["category"] == "DATA_GAP"),
    }
    trade_date = next((item.get("trade_date") for item in results if item.get("trade_date")), None)
    conn.execute(
        """
        INSERT INTO watchlist_screen_runs (
            run_id, tab_id, tab_name, screen_type, trade_date, total_count,
            candidate_count, watch_count, risk_count, data_gap_count, created_at, params_json
        )
        VALUES (?, ?, ?, 'pre_market', ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            tab_id,
            tab["name"] if tab else tab_id,
            trade_date,
            len(results),
            counts["CANDIDATE"],
            counts["WATCH"],
            counts["RISK"],
            counts["DATA_GAP"],
            created_at,
            json.dumps(params or {}, ensure_ascii=False),
        ),
    )
    for index, item in enumerate(results, start=1):
        conn.execute(
            """
            INSERT INTO watchlist_screen_results (
                result_id, run_id, symbol, name, category, score, price, pct_change,
                pe_ttm, pb, ma20, ma60, change_20d_pct, trade_date, is_position,
                matched_rules_json, warnings_json, summary, created_at, review_status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'UNREVIEWED')
            """,
            (
                f"{run_id}_{index:04d}_{item['symbol']}",
                run_id,
                item["symbol"],
                item.get("name"),
                item["category"],
                item["score"],
                item.get("price"),
                item.get("pct_change"),
                item.get("pe_ttm"),
                item.get("pb"),
                item.get("ma20"),
                item.get("ma60"),
                item.get("change_20d_pct"),
                item.get("trade_date"),
                item.get("is_position"),
                json.dumps(item["matched_rules"], ensure_ascii=False),
                json.dumps(item["warnings"], ensure_ascii=False),
                item["summary"],
                created_at,
            ),
        )
    return {"run_id": run_id, "results": results, "counts": counts}
