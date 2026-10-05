# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import main
from src.config import Config
from src.services.daily_analysis_universe import (
    DailyAnalysisUniverseService,
    normalize_daily_analysis_symbol,
)
from src.storage import DatabaseManager


def _setup_isolated_db(tmp_path: Path, monkeypatch) -> DailyAnalysisUniverseService:
    env_path = tmp_path / ".env"
    db_path = tmp_path / "daily_analysis_universe.db"
    env_path.write_text(
        "\n".join(
            [
                "STOCK_LIST=0050.TW",
                "GEMINI_API_KEY=test",
                "ADMIN_AUTH_ENABLED=false",
                f"DATABASE_PATH={db_path}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ENV_FILE", str(env_path))
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    Config.reset_instance()
    DatabaseManager.reset_instance()
    return DailyAnalysisUniverseService()


def teardown_function() -> None:
    DatabaseManager.reset_instance()
    Config.reset_instance()


def test_normalize_daily_analysis_symbol_treats_bare_tw_codes_as_tw() -> None:
    assert normalize_daily_analysis_symbol("2376", market_hint="tw") == "2376.TW"
    assert normalize_daily_analysis_symbol("00878", market_hint="tw") == "00878.TW"
    assert normalize_daily_analysis_symbol("006208", market_hint="tw") == "006208.TW"
    assert normalize_daily_analysis_symbol("600519", market_hint="cn") == "600519"


def test_user_required_symbols_and_stock_list_are_always_in_daily_universe(tmp_path: Path, monkeypatch) -> None:
    service = _setup_isolated_db(tmp_path, monkeypatch)
    service.upsert_user_stock(
        user_key="andy",
        display_name="Andy",
        email="andy@example.com",
        symbol="2376",
        relation_type="holding",
        market="tw",
        shares=10,
        avg_cost=250,
    )

    universe = service.build_universe(config_stock_list=["0050.TW"], min_stocks=10, max_stocks=15)

    assert "2376.TW" in universe["symbols"]
    assert "0050.TW" in universe["symbols"]
    assert 10 <= len(universe["symbols"]) <= 15
    item_by_symbol = {item["symbol"]: item for item in universe["items"]}
    assert item_by_symbol["2376.TW"]["required"] is True
    assert item_by_symbol["2376.TW"]["source"] == "user_holding"
    assert item_by_symbol["0050.TW"]["required"] is True
    assert item_by_symbol["0050.TW"]["source"] == "stock_list"


def test_required_symbols_are_not_dropped_when_they_exceed_candidate_cap(tmp_path: Path, monkeypatch) -> None:
    service = _setup_isolated_db(tmp_path, monkeypatch)
    required_symbols = [
        "1101",
        "1102",
        "1216",
        "1301",
        "1303",
        "1326",
        "1402",
        "2002",
        "2207",
        "2301",
        "2327",
        "2409",
        "2881",
        "2882",
        "2891",
        "5871",
    ]
    for symbol in required_symbols:
        service.upsert_user_stock(
            user_key="long_portfolio",
            symbol=symbol,
            relation_type="watch",
            market="tw",
        )

    universe = service.build_universe(config_stock_list=[], min_stocks=10, max_stocks=15)

    expected = {f"{symbol}.TW" for symbol in required_symbols}
    assert expected.issubset(set(universe["symbols"]))
    assert len(universe["symbols"]) == len(required_symbols)
    assert universe["candidate_count"] == 0


def test_cached_portfolio_holdings_are_required_without_snapshot_replay(tmp_path: Path, monkeypatch) -> None:
    service = _setup_isolated_db(tmp_path, monkeypatch)

    class FakePortfolioRepo:
        def list_cached_position_identities(self):
            return [("tw", "2330.TW")]

    service.portfolio_repo = FakePortfolioRepo()
    universe = service.build_universe(config_stock_list=[], min_stocks=10, max_stocks=15)

    item_by_symbol = {item["symbol"]: item for item in universe["items"]}
    assert item_by_symbol["2330.TW"]["required"] is True
    assert item_by_symbol["2330.TW"]["source"] == "portfolio_holding"


def test_preserve_shared_slots_keeps_user_symbols_from_consuming_candidate_cap(
    tmp_path: Path,
    monkeypatch,
) -> None:
    service = _setup_isolated_db(tmp_path, monkeypatch)
    service.upsert_user_stock(
        user_key="cheng",
        email="andy@example.com",
        symbol="00878",
        relation_type="holding",
        market="tw",
    )

    universe = service.build_universe(
        config_stock_list=["2330.TW"],
        min_stocks=10,
        max_stocks=10,
        preserve_shared_slots=True,
    )

    assert "00878.TW" in universe["symbols"]
    assert len(universe["symbols"]) == 11
    assert universe["candidate_count"] == 9


def test_email_routing_sends_user_specific_symbols_and_default_shared_report(
    tmp_path: Path,
    monkeypatch,
) -> None:
    service = _setup_isolated_db(tmp_path, monkeypatch)
    service.upsert_user_stock(
        user_key="cheng",
        email="andy@example.com",
        symbol="00878",
        relation_type="holding",
        market="tw",
    )

    routing = service.build_email_routing(
        config_stock_list=["2330.TW"],
        default_receivers=["andy@example.com", "rita@example.com"],
        min_stocks=10,
        max_stocks=10,
    )

    groups = {group["label"]: group for group in routing["groups"]}
    assert groups["daily-user:cheng"]["receivers"] == ["andy@example.com"]
    assert "2330.TW" in groups["daily-user:cheng"]["symbols"]
    assert "00878.TW" in groups["daily-user:cheng"]["symbols"]
    assert groups["daily-default"]["receivers"] == ["rita@example.com"]
    assert "2330.TW" in groups["daily-default"]["symbols"]
    assert "00878.TW" not in groups["daily-default"]["symbols"]


def test_scheduled_analysis_snapshot_freezes_daily_universe_with_user_symbols(
    tmp_path: Path,
    monkeypatch,
) -> None:
    service = _setup_isolated_db(tmp_path, monkeypatch)
    service.upsert_user_stock(
        user_key="cheng",
        email="andy@example.com",
        symbol="00878",
        relation_type="holding",
        market="tw",
    )
    config = Config.get_instance()
    args = SimpleNamespace(
        portfolio=None,
        no_notify=False,
        no_market_review=False,
        dry_run=False,
        force_run=False,
        single_notify=False,
        _scheduled_for=datetime(2026, 10, 5, 18, 0, tzinfo=timezone.utc),
    )

    with patch.object(main, "run_full_analysis", return_value=True) as run_full:
        assert main.run_scheduled_analysis(config, args) is True

    captured = run_full.call_args.args[0]
    assert run_full.call_args.kwargs["refresh_watchlist"] is False
    assert "0050.TW" in captured.stock_list
    assert "00878.TW" in captured.stock_list
