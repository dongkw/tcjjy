"""Import manually prepared real-account shadow data."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Any

from .cost_model import money
from .portfolio import (
    ensure_account_positions,
    load_accounts,
    load_positions,
    now_iso,
    save_accounts,
    save_positions,
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _float(value: Any, default: float | None = None) -> float | None:
    if value in (None, ""):
        return default
    return float(str(value).replace(",", ""))


def _int(value: Any, default: int = 0) -> int:
    if value in (None, ""):
        return default
    return int(float(str(value).replace(",", "")))


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _bool(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "是"}


def import_real_account(args: argparse.Namespace) -> dict[str, Any]:
    output_root = Path(args.output_dir)
    account_rows = _read_csv(Path(args.account_csv))
    position_rows = _read_csv(Path(args.positions_csv))
    if not account_rows:
        raise ValueError(f"account csv is empty: {args.account_csv}")

    account_id = args.account or account_rows[0].get("account_id")
    if not account_id:
        raise ValueError("account_id is required")

    account_row = next((row for row in account_rows if row.get("account_id") == account_id), account_rows[0])
    positions_for_account = [row for row in position_rows if row.get("account_id") == account_id]
    if not positions_for_account:
        raise ValueError(f"no positions found for account: {account_id}")

    imported_at = now_iso()
    total_assets = _float(account_row.get("total_assets"), 0.0) or 0.0
    market_value = _float(account_row.get("market_value"), 0.0) or 0.0
    available_cash = _float(account_row.get("available_cash"), 0.0) or 0.0
    cash_pct = round(available_cash / total_assets * 100, 4) if total_assets > 0 else None

    accounts = load_accounts(output_root)
    previous = accounts.get(account_id, {})
    account = {
        **previous,
        "account_id": account_id,
        "account_name": account_row.get("account_name") or previous.get("account_name") or "真实影子账户",
        "account_type": account_row.get("account_type") or previous.get("account_type") or "PAPER_SHADOW",
        "base_currency": account_row.get("currency") or previous.get("base_currency") or "CNY",
        "initial_cash": money(_float(account_row.get("initial_cash"), total_assets) or total_assets),
        "available_cash": money(available_cash),
        "frozen_cash": money(_float(account_row.get("frozen_cash"), 0.0) or 0.0),
        "market_value": money(market_value),
        "total_assets": money(total_assets),
        "cash_reserve_pct": _float(account_row.get("cash_reserve_pct"), previous.get("cash_reserve_pct") or 20.0),
        "max_single_position_pct": _float(account_row.get("max_single_position_pct"), previous.get("max_single_position_pct") or 30.0),
        "max_daily_buy_amount": money(_float(account_row.get("max_daily_buy_amount"), previous.get("max_daily_buy_amount") or available_cash) or 0.0),
        "today_buy_used": money(_float(account_row.get("today_buy_used"), 0.0) or 0.0),
        "today_sell_amount": money(_float(account_row.get("today_sell_amount"), 0.0) or 0.0),
        "last_rollover_trade_date": args.trade_date or previous.get("last_rollover_trade_date"),
        "equity_position_pct": _float(account_row.get("position_pct")),
        "cash_pct": cash_pct,
        "position_count": len(positions_for_account),
        "withdrawable_cash": money(_float(account_row.get("withdrawable_cash"), 0.0) or 0.0),
        "holding_pnl": money(_float(account_row.get("holding_pnl"), 0.0) or 0.0),
        "today_pnl": money(_float(account_row.get("today_pnl"), 0.0) or 0.0),
        "today_pnl_pct": _float(account_row.get("today_pnl_pct")),
        "source": account_row.get("source"),
        "source_time": account_row.get("source_time"),
        "need_confirm": _bool(account_row.get("need_confirm")),
        "created_at": previous.get("created_at") or imported_at,
        "updated_at": imported_at,
    }
    accounts[account_id] = account
    save_accounts(output_root, accounts)

    positions = load_positions(output_root)
    account_positions = ensure_account_positions(positions, account_id)
    account_positions.clear()
    for row in positions_for_account:
        symbol = row.get("symbol")
        if not symbol:
            continue
        total_quantity = _int(row.get("total_quantity"))
        available_quantity = _int(row.get("available_quantity"))
        market_price = _float(row.get("market_price"), 0.0) or 0.0
        avg_cost = _float(row.get("avg_cost"), 0.0) or 0.0
        market_value_row = _float(row.get("market_value"), total_quantity * market_price) or 0.0
        position = {
            "account_id": account_id,
            "symbol": symbol,
            "name": row.get("name"),
            "asset_type": row.get("asset_type") or "A_STOCK",
            "total_quantity": total_quantity,
            "available_quantity": available_quantity,
            "locked_quantity": max(total_quantity - available_quantity, 0),
            "avg_cost": avg_cost,
            "market_price": market_price,
            "market_value": money(market_value_row),
            "unrealized_pnl": money(_float(row.get("unrealized_pnl"), market_value_row - total_quantity * avg_cost) or 0.0),
            "unrealized_pnl_pct": _float(row.get("unrealized_pnl_pct")),
            "position_pct": round(market_value_row / total_assets * 100, 4) if total_assets > 0 else None,
            "first_buy_date": _text(row.get("first_buy_date")),
            "last_trade_date": args.trade_date,
            "buy_logic": _text(row.get("buy_logic")),
            "invalidation_point": _text(row.get("invalidation_point")),
            "stop_loss_price": _float(row.get("stop_loss_price")),
            "planned_position_pct": _float(row.get("planned_position_pct")),
            "position_status": row.get("position_status") or "ACTIVE",
            "source": row.get("source"),
            "source_time": row.get("source_time"),
            "need_confirm": _bool(row.get("need_confirm")),
            "note": row.get("note"),
            "updated_at": imported_at,
        }
        account_positions[symbol] = position
    save_positions(output_root, positions)

    return {
        "account_id": account_id,
        "positions": len(account_positions),
        "total_assets": account["total_assets"],
        "market_value": account["market_value"],
        "available_cash": account["available_cash"],
    }


def import_command(args: argparse.Namespace) -> None:
    result = import_real_account(args)
    print(f"account: {result['account_id']}")
    print(f"positions: {result['positions']}")
    print(f"total_assets: {result['total_assets']}")
    print(f"market_value: {result['market_value']}")
    print(f"available_cash: {result['available_cash']}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import manually prepared real-account shadow data.")
    parser.add_argument("--output-dir", default="data")
    parser.add_argument("--account", default="real_shadow")
    parser.add_argument("--account-csv", default="data/imports/real_account_summary.csv")
    parser.add_argument("--positions-csv", default="data/imports/real_positions.csv")
    parser.add_argument("--trade-date", help="As-of trade date for the imported account state.")
    parser.set_defaults(func=import_command)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
