"""Utilities for local watchlist preparation."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from .stock_decision_data import build_payload


def read_watchlist(path: Path) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(f"watchlist not found: {path}")
    codes: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        code = line.strip()
        if code and code not in codes:
            codes.append(code)
    return codes


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def check_watchlist(args: argparse.Namespace) -> dict[str, Any]:
    watchlist_path = Path(args.watchlist)
    data_dir = Path(args.data_dir)
    codes = read_watchlist(watchlist_path)
    rows: list[dict[str, Any]] = []
    for code in codes:
        stock_path = data_dir / f"stock_data_{code}.json"
        stock_data = _load_json(stock_path) if stock_path.exists() else {}
        quote = stock_data.get("quote") or {}
        meta = stock_data.get("meta") or {}
        rows.append(
            {
                "code": code,
                "exists": stock_path.exists(),
                "path": str(stock_path),
                "name": quote.get("name"),
                "trade_date": quote.get("trade_date"),
                "generated_at": meta.get("generated_at"),
            }
        )
    existing = [row for row in rows if row["exists"]]
    missing = [row for row in rows if not row["exists"]]
    return {
        "watchlist": str(watchlist_path),
        "data_dir": str(data_dir),
        "total": len(codes),
        "existing_count": len(existing),
        "missing_count": len(missing),
        "rows": rows,
        "missing_codes": [row["code"] for row in missing],
    }


def check_command(args: argparse.Namespace) -> None:
    result = check_watchlist(args)
    print(f"watchlist: {result['watchlist']}")
    print(f"data_dir: {result['data_dir']}")
    print(f"total: {result['total']}")
    print(f"existing: {result['existing_count']}")
    print(f"missing: {result['missing_count']}")
    if args.detail:
        print("items:")
        for row in result["rows"]:
            status = "OK" if row["exists"] else "MISSING"
            print(
                "  "
                f"{row['code']} {status} "
                f"name={row.get('name') or '-'} "
                f"trade_date={row.get('trade_date') or '-'}"
            )
    if result["missing_codes"]:
        print("missing_codes:")
        print("  " + ",".join(result["missing_codes"]))


def refresh_watchlist(args: argparse.Namespace) -> dict[str, Any]:
    watchlist_path = Path(args.watchlist)
    data_dir = Path(args.data_dir)
    codes = read_watchlist(watchlist_path)
    return refresh_codes(codes, data_dir, period=args.period, sleep=args.sleep, stop_on_error=args.stop_on_error, source=str(watchlist_path))


def refresh_codes(
    codes: list[str],
    data_dir: Path,
    *,
    period: str = "middle",
    sleep: float = 0.5,
    stop_on_error: bool = False,
    source: str = "selected_codes",
) -> dict[str, Any]:
    normalized_codes: list[str] = []
    for code in codes:
        value = str(code).strip()
        if value and value not in normalized_codes:
            normalized_codes.append(value)
    data_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    for index, code in enumerate(normalized_codes, start=1):
        out_path = data_dir / f"stock_data_{code}.json"
        print(f"[{index}/{len(normalized_codes)}] refresh {code}")
        try:
            payload = build_payload(code, period)
            out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            quote = payload.get("quote") or {}
            meta = payload.get("meta") or {}
            row = {
                "code": code,
                "status": "OK",
                "path": str(out_path),
                "name": quote.get("name"),
                "trade_date": quote.get("trade_date"),
                "generated_at": meta.get("generated_at"),
                "error": None,
            }
            print(
                "  OK "
                f"name={row.get('name') or '-'} "
                f"trade_date={row.get('trade_date') or '-'} "
                f"saved={out_path}"
            )
        except Exception as exc:  # noqa: BLE001 - batch refresh must keep the failed symbol visible.
            row = {
                "code": code,
                "status": "FAILED",
                "path": str(out_path),
                "name": None,
                "trade_date": None,
                "generated_at": None,
                "error": str(exc),
            }
            print(f"  FAILED {exc}")
            if stop_on_error:
                rows.append(row)
                break
        rows.append(row)
        if sleep > 0 and index < len(normalized_codes):
            time.sleep(sleep)

    ok_rows = [row for row in rows if row["status"] == "OK"]
    failed_rows = [row for row in rows if row["status"] != "OK"]
    return {
        "watchlist": source,
        "data_dir": str(data_dir),
        "total": len(normalized_codes),
        "processed": len(rows),
        "ok_count": len(ok_rows),
        "failed_count": len(failed_rows),
        "rows": rows,
        "failed_codes": [row["code"] for row in failed_rows],
    }


def refresh_command(args: argparse.Namespace) -> None:
    result = refresh_watchlist(args)
    print("summary:")
    print(f"  watchlist: {result['watchlist']}")
    print(f"  data_dir: {result['data_dir']}")
    print(f"  total: {result['total']}")
    print(f"  processed: {result['processed']}")
    print(f"  ok: {result['ok_count']}")
    print(f"  failed: {result['failed_count']}")
    if result["failed_codes"]:
        print("failed_codes:")
        print("  " + ",".join(result["failed_codes"]))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Watchlist preparation utilities.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("check", help="Check which watchlist symbols have local stock JSON.")
    check.add_argument("--watchlist", default="data/watchlist.txt")
    check.add_argument("--data-dir", default="data/stock_json")
    check.add_argument("--detail", action="store_true")
    check.set_defaults(func=check_command)

    refresh = subparsers.add_parser("refresh", help="Refresh every watchlist symbol and overwrite local stock JSON.")
    refresh.add_argument("--watchlist", default="data/watchlist.txt")
    refresh.add_argument("--data-dir", default="data/stock_json")
    refresh.add_argument("--period", choices=["short", "middle", "long"], default="middle")
    refresh.add_argument("--sleep", type=float, default=0.5, help="Seconds to wait between symbols. Default: 0.5.")
    refresh.add_argument("--stop-on-error", action="store_true")
    refresh.set_defaults(func=refresh_command)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
