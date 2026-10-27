from __future__ import annotations

from datetime import date, datetime
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest
import requests

from trader_v2.fixtures import make_fixture
from trader_v2.market import MarketDataError, TencentDailyProvider
from trader_v2.models import DailyBar, validate_symbol


def _mock_response(monkeypatch: pytest.MonkeyPatch, payload: object) -> Mock:
    response = Mock()
    response.json.return_value = payload
    get = Mock(return_value=response)
    monkeypatch.setattr("trader_v2.market.requests.get", get)
    monkeypatch.setattr("trader_v2.market._now_shanghai", lambda: datetime(
        2026, 10, 26, 14, tzinfo=ZoneInfo("Asia/Shanghai")
    ))
    return get


def _payload(rows: list[list[str]], key: str = "qfqday") -> dict:
    return {"code": 0, "data": {"sh601138": {
        key: rows, "qt": {"sh601138": ["1", "工业富联", "601138"]}
    }}}


@pytest.mark.parametrize("symbol", ["601138", "600519", "000001", "002563", "605001"])
def test_main_board_codes_keep_leading_zero(symbol: str) -> None:
    assert validate_symbol(symbol) == symbol


@pytest.mark.parametrize("symbol", ["300001", "688001", "510300", "430047", "601138x", " 601138", "０００００１", 1])
def test_non_main_board_and_malformed_codes_are_rejected(symbol: object) -> None:
    with pytest.raises(ValueError):
        validate_symbol(symbol)  # type: ignore[arg-type]


@pytest.mark.parametrize("change", [
    {"close": float("nan")}, {"open": 0}, {"high": 9}, {"low": 12},
    {"volume": -1}, {"amount": float("inf")}, {"close": True},
])
def test_invalid_ohlc_and_units_are_rejected(change: dict) -> None:
    fields = dict(trade_date=date(2026, 10, 23), open=10, high=12, low=9, close=11)
    with pytest.raises(ValueError):
        DailyBar(**(fields | change))


def test_fixture_is_repeatable_and_explicitly_synthetic() -> None:
    first = make_fixture()
    assert first == make_fixture()
    assert first.mode == first.source == "fixture"
    assert "合成" in first.name
    assert len(first.bars) == 90
    assert first.bars[-1].trade_date == date(2026, 10, 23)
    assert all(bar.trade_date.weekday() < 5 for bar in first.bars)


def test_tencent_units_name_and_unclosed_day_are_handled(monkeypatch: pytest.MonkeyPatch) -> None:
    get = _mock_response(monkeypatch, _payload([
        ["2026-10-23", "10", "11", "12", "9", "123.5"],
        ["2026-10-26", "11", "12", "13", "10", "200"],
    ]))
    result = TencentDailyProvider(timeout=8).fetch("601138")
    assert result.mode == "live"
    assert result.source == "tencent"
    assert result.name == "工业富联"
    assert result.adjustment == "qfq"
    assert len(result.bars) == 1
    assert result.bars[0].volume == 12_350
    assert result.bars[0].amount is None
    assert get.call_args.kwargs["timeout"] == 8


def test_historical_end_date_filters_later_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    get = _mock_response(monkeypatch, _payload([
        ["2026-10-22", "10", "11", "12", "9", "100"],
        ["2026-10-23", "11", "12", "13", "10", "200"],
    ]))
    result = TencentDailyProvider().fetch("601138", end_date=date(2026, 10, 22))
    assert [bar.trade_date for bar in result.bars] == [date(2026, 10, 22)]
    assert "2026-10-22" in get.call_args.kwargs["params"]["param"]


def test_closed_current_day_is_retained(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_response(monkeypatch, _payload([
        ["2026-10-26", "10", "11", "12", "9", "100"],
    ]))
    monkeypatch.setattr("trader_v2.market._now_shanghai", lambda: datetime(
        2026, 10, 26, 15, 1, tzinfo=ZoneInfo("Asia/Shanghai")
    ))
    result = TencentDailyProvider().fetch("601138")
    assert result.bars[0].trade_date == date(2026, 10, 26)


def test_unadjusted_response_is_not_mislabeled(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_response(monkeypatch, _payload([
        ["2026-10-23", "10", "11", "12", "9", "100"],
    ], key="day"))
    assert TencentDailyProvider().fetch("601138").adjustment == "none"


@pytest.mark.parametrize("payload", [
    {"code": 1, "data": {}}, {"code": 0, "data": {}},
    {"code": 0, "data": {"sh601138": {"qfqday": []}}}, [],
    _payload([["2026-10-23", "10", "11", "9", "9", "100"]]),
    _payload([["2026-10-23", "10", "11", "12", "9", "100"],
              ["2026-10-23", "10", "11", "12", "9", "100"]]),
])
def test_failed_empty_or_corrupt_source_never_becomes_fixture(monkeypatch: pytest.MonkeyPatch, payload: object) -> None:
    _mock_response(monkeypatch, payload)
    with pytest.raises(MarketDataError):
        TencentDailyProvider().fetch("601138")


def test_network_failure_is_visible(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_response(monkeypatch, {})
    monkeypatch.setattr("trader_v2.market.requests.get", Mock(side_effect=requests.Timeout("timeout")))
    with pytest.raises(MarketDataError, match="请求失败"):
        TencentDailyProvider().fetch("601138")


def test_invalid_request_does_not_call_source(monkeypatch: pytest.MonkeyPatch) -> None:
    get = _mock_response(monkeypatch, {})
    with pytest.raises(ValueError):
        TencentDailyProvider().fetch("601138", end_date=date(2026, 10, 27))
    with pytest.raises(ValueError):
        TencentDailyProvider().fetch("601138", limit=1000)
    get.assert_not_called()
