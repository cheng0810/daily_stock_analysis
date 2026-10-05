# -*- coding: utf-8 -*-
"""Daily analysis universe selection for portfolio/user required symbols."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any, Dict, Iterable, List, Optional, Sequence

from sqlalchemy import desc, select

from data_provider.base import canonical_stock_code
from src.data.stock_mapping import STOCK_NAME_MAP
from src.repositories.daily_analysis_user_repo import DailyAnalysisUserRepository
from src.repositories.portfolio_repo import PortfolioRepository
from src.storage import AnalysisHistory, DatabaseManager


VALID_DAILY_ANALYSIS_MARKETS = {"cn", "hk", "us", "jp", "kr", "tw"}
VALID_USER_STOCK_RELATION_TYPES = {"holding", "watch"}
DEFAULT_DAILY_ANALYSIS_MIN_STOCKS = 10
DEFAULT_DAILY_ANALYSIS_MAX_STOCKS = 15
DEFAULT_DAILY_ANALYSIS_WATCH_SCORE_THRESHOLD = 60

DEFAULT_TW_TECH_CANDIDATES: Sequence[tuple[str, str, int, str]] = (
    ("2330.TW", "台積電", 95, "半導體權值"),
    ("2308.TW", "台達電", 88, "電源與AI伺服器"),
    ("2454.TW", "聯發科", 86, "IC設計"),
    ("2317.TW", "鴻海", 84, "AI伺服器與組裝"),
    ("2382.TW", "廣達", 82, "AI伺服器"),
    ("2376.TW", "技嘉", 80, "AI PC與伺服器"),
    ("6669.TW", "緯穎", 78, "雲端伺服器"),
    ("3231.TW", "緯創", 76, "AI伺服器與代工"),
    ("2345.TW", "智邦", 74, "網通"),
    ("3017.TW", "奇鋐", 72, "散熱"),
    ("2357.TW", "華碩", 70, "PC與板卡"),
    ("2356.TW", "英業達", 68, "伺服器與代工"),
    ("2383.TW", "台光電", 67, "CCL材料"),
    ("3711.TW", "日月光投控", 66, "封測"),
    ("3034.TW", "聯詠", 65, "IC設計"),
    ("3045.TW", "台灣大", 63, "電信現金流"),
    ("3037.TW", "欣興", 62, "ABF載板"),
    ("3661.TW", "世芯-KY", 61, "ASIC設計"),
    ("5274.TW", "信驊", 60, "伺服器管理晶片"),
    ("6488.TW", "環球晶", 59, "半導體矽晶圓"),
    ("006208.TW", "富邦台50", 58, "台股大型ETF"),
    ("0050.TW", "元大台灣50", 57, "台股大型ETF"),
)


@dataclass(frozen=True)
class DailyAnalysisUniverseItem:
    symbol: str
    stock_name: Optional[str]
    market: str
    required: bool
    source: str
    watch_score: int
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def normalize_daily_analysis_symbol(symbol: str, market_hint: Optional[str] = None) -> str:
    """Normalize user-facing symbols while treating bare Taiwan codes as `.TW`."""

    raw = (symbol or "").strip().upper()
    if not raw:
        return ""
    market = (market_hint or "").strip().lower()
    if market == "tw" and raw.isdigit() and (len(raw) == 4 or (len(raw) == 6 and raw.startswith("00"))):
        return f"{raw}.TW"
    return canonical_stock_code(raw)


def infer_daily_analysis_market(symbol: str, fallback: str = "tw") -> str:
    text = (symbol or "").strip().upper()
    if text.endswith((".TW", ".TWO")):
        return "tw"
    if text.endswith(".HK") or text.startswith("HK"):
        return "hk"
    if text.endswith(".T"):
        return "jp"
    if text.endswith((".KS", ".KQ")):
        return "kr"
    if text.isdigit() and len(text) == 6 and not text.startswith("00"):
        return "cn"
    return fallback if fallback in VALID_DAILY_ANALYSIS_MARKETS else "us"


def _display_stock_name(symbol: str, provided: Optional[str] = None) -> Optional[str]:
    value = (provided or "").strip()
    if value:
        return value
    return STOCK_NAME_MAP.get(symbol) or STOCK_NAME_MAP.get(symbol.upper())


def _coerce_non_negative_float(value: Optional[float], field_name: str) -> Optional[float]:
    if value is None:
        return None
    numeric = float(value)
    if numeric < 0:
        raise ValueError(f"{field_name} must be >= 0")
    return numeric


class DailyAnalysisUniverseService:
    """Build the symbols analyzed by automatic daily runs."""

    def __init__(
        self,
        *,
        user_repo: Optional[DailyAnalysisUserRepository] = None,
        portfolio_repo: Optional[PortfolioRepository] = None,
        db_manager: Optional[DatabaseManager] = None,
    ) -> None:
        self.db = db_manager or DatabaseManager.get_instance()
        self.user_repo = user_repo or DailyAnalysisUserRepository(self.db)
        self.portfolio_repo = portfolio_repo or PortfolioRepository(self.db)

    def upsert_user(
        self,
        *,
        user_key: str,
        display_name: Optional[str] = None,
        email: Optional[str] = None,
        daily_email_enabled: bool = True,
        is_active: bool = True,
    ) -> Dict[str, Any]:
        key = (user_key or "").strip()
        if not key:
            raise ValueError("user_key is required")
        row = self.user_repo.upsert_user(
            user_key=key,
            display_name=(display_name or "").strip() or None,
            email=(email or "").strip() or None,
            daily_email_enabled=daily_email_enabled,
            is_active=is_active,
        )
        return self._user_to_dict(row)

    def list_users(self, *, include_inactive: bool = False) -> List[Dict[str, Any]]:
        return [
            self._user_to_dict(row)
            for row in self.user_repo.list_users(include_inactive=include_inactive)
        ]

    def upsert_user_stock(
        self,
        *,
        user_key: str,
        symbol: str,
        relation_type: str,
        stock_name: Optional[str] = None,
        market: Optional[str] = None,
        shares: Optional[float] = None,
        avg_cost: Optional[float] = None,
        buy_date: Optional[date] = None,
        note: Optional[str] = None,
        display_name: Optional[str] = None,
        email: Optional[str] = None,
        daily_email_enabled: bool = True,
    ) -> Dict[str, Any]:
        key = (user_key or "").strip()
        if not key:
            raise ValueError("user_key is required")
        relation = (relation_type or "").strip().lower()
        if relation not in VALID_USER_STOCK_RELATION_TYPES:
            raise ValueError("relation_type must be holding or watch")
        market_hint = (market or "tw").strip().lower()
        if market_hint not in VALID_DAILY_ANALYSIS_MARKETS:
            raise ValueError("market must be one of: cn, hk, us, jp, kr, tw")
        symbol_norm = normalize_daily_analysis_symbol(symbol, market_hint=market_hint)
        if not symbol_norm:
            raise ValueError("symbol is required")
        market_norm = infer_daily_analysis_market(symbol_norm, fallback=market_hint)

        user = self.user_repo.upsert_user(
            user_key=key,
            display_name=(display_name or "").strip() or None,
            email=(email or "").strip() or None,
            daily_email_enabled=daily_email_enabled,
            is_active=True,
        )
        row = self.user_repo.upsert_user_stock(
            user_id=int(user.id),
            symbol=symbol_norm,
            stock_name=_display_stock_name(symbol_norm, stock_name),
            market=market_norm,
            relation_type=relation,
            shares=_coerce_non_negative_float(shares, "shares"),
            avg_cost=_coerce_non_negative_float(avg_cost, "avg_cost"),
            buy_date=buy_date,
            note=(note or "").strip() or None,
            enabled=True,
        )
        payload = self.user_repo.list_user_stock_payloads(user_key=key, include_disabled=True)
        return next(item for item in payload if int(item["id"]) == int(row.id))

    def list_user_stocks(
        self,
        *,
        user_key: Optional[str] = None,
        include_disabled: bool = False,
    ) -> List[Dict[str, Any]]:
        return self.user_repo.list_user_stock_payloads(
            user_key=(user_key or "").strip() or None,
            include_disabled=include_disabled,
        )

    def delete_user_stock(self, stock_id: int) -> bool:
        return self.user_repo.delete_user_stock(stock_id)

    def set_user_stock_enabled(self, stock_id: int, enabled: bool) -> bool:
        return self.user_repo.set_user_stock_enabled(stock_id, enabled)

    def build_universe(
        self,
        *,
        config_stock_list: Optional[Iterable[str]] = None,
        min_stocks: int = DEFAULT_DAILY_ANALYSIS_MIN_STOCKS,
        max_stocks: int = DEFAULT_DAILY_ANALYSIS_MAX_STOCKS,
        watch_score_threshold: int = DEFAULT_DAILY_ANALYSIS_WATCH_SCORE_THRESHOLD,
        include_portfolio_holdings: bool = True,
    ) -> Dict[str, Any]:
        min_count = max(0, int(min_stocks))
        max_count = max(1, int(max_stocks))
        if max_count < min_count:
            max_count = min_count

        required: "OrderedDict[str, DailyAnalysisUniverseItem]" = OrderedDict()
        self._add_user_required_symbols(required)
        if include_portfolio_holdings:
            self._add_cached_portfolio_holdings(required)
        self._add_legacy_watchlist(required, config_stock_list or [])

        candidates = self._candidate_items(excluded=set(required.keys()))
        selected_candidates = [
            item for item in candidates if item.watch_score >= int(watch_score_threshold)
        ]
        for item in candidates:
            if len(required) + len(selected_candidates) >= min_count:
                break
            if item.symbol not in {selected.symbol for selected in selected_candidates}:
                selected_candidates.append(item)

        available_slots = max_count - len(required)
        if available_slots <= 0:
            final_items = list(required.values())
            truncated_candidates: List[DailyAnalysisUniverseItem] = []
        else:
            final_items = list(required.values()) + selected_candidates[:available_slots]
            truncated_candidates = selected_candidates[available_slots:]

        return {
            "symbols": [item.symbol for item in final_items],
            "items": [item.to_dict() for item in final_items],
            "required_count": len(required),
            "candidate_count": max(0, len(final_items) - len(required)),
            "min_stocks": min_count,
            "max_stocks": max_count,
            "watch_score_threshold": int(watch_score_threshold),
            "truncated_candidate_count": len(truncated_candidates),
        }

    def _add_item(
        self,
        target: "OrderedDict[str, DailyAnalysisUniverseItem]",
        *,
        symbol: str,
        market: str,
        stock_name: Optional[str],
        required: bool,
        source: str,
        watch_score: int,
        reason: str,
    ) -> None:
        symbol_norm = normalize_daily_analysis_symbol(symbol, market_hint=market)
        if not symbol_norm or symbol_norm in target:
            return
        target[symbol_norm] = DailyAnalysisUniverseItem(
            symbol=symbol_norm,
            stock_name=_display_stock_name(symbol_norm, stock_name),
            market=infer_daily_analysis_market(symbol_norm, fallback=market),
            required=required,
            source=source,
            watch_score=max(0, min(100, int(watch_score))),
            reason=reason,
        )

    def _add_user_required_symbols(
        self,
        target: "OrderedDict[str, DailyAnalysisUniverseItem]",
    ) -> None:
        for item in self.user_repo.list_user_stock_payloads(include_disabled=False):
            relation = str(item.get("relation_type") or "watch")
            source = "user_holding" if relation == "holding" else "user_watch"
            self._add_item(
                target,
                symbol=str(item.get("symbol") or ""),
                market=str(item.get("market") or "tw"),
                stock_name=item.get("stock_name"),
                required=True,
                source=source,
                watch_score=100 if relation == "holding" else 95,
                reason="使用者設定每日必跑",
            )

    def _add_cached_portfolio_holdings(
        self,
        target: "OrderedDict[str, DailyAnalysisUniverseItem]",
    ) -> None:
        try:
            identities = self.portfolio_repo.list_cached_position_identities()
        except Exception:
            identities = []
        for market, symbol in identities:
            self._add_item(
                target,
                symbol=symbol,
                market=market or infer_daily_analysis_market(symbol),
                stock_name=None,
                required=True,
                source="portfolio_holding",
                watch_score=100,
                reason="Portfolio 快取持股每日必跑",
            )

    def _add_legacy_watchlist(
        self,
        target: "OrderedDict[str, DailyAnalysisUniverseItem]",
        stock_list: Iterable[str],
    ) -> None:
        for raw in stock_list:
            raw_text = str(raw or "").strip()
            if not raw_text:
                continue
            market = infer_daily_analysis_market(raw_text, fallback="tw")
            self._add_item(
                target,
                symbol=raw_text,
                market=market,
                stock_name=None,
                required=True,
                source="stock_list",
                watch_score=90,
                reason="既有 STOCK_LIST 自選清單",
            )

    def _candidate_items(self, *, excluded: set[str]) -> List[DailyAnalysisUniverseItem]:
        latest_scores = self._latest_history_scores([item[0] for item in DEFAULT_TW_TECH_CANDIDATES])
        items: List[DailyAnalysisUniverseItem] = []
        for symbol, name, base_score, theme in DEFAULT_TW_TECH_CANDIDATES:
            if symbol in excluded:
                continue
            history_score = latest_scores.get(symbol)
            watch_score = base_score
            if history_score is not None:
                watch_score = round((base_score * 0.7) + (int(history_score) * 0.3))
            items.append(
                DailyAnalysisUniverseItem(
                    symbol=symbol,
                    stock_name=name,
                    market="tw",
                    required=False,
                    source="tw_tech_candidate",
                    watch_score=max(0, min(100, int(watch_score))),
                    reason=theme,
                )
            )
        return sorted(items, key=lambda item: (-item.watch_score, item.symbol))

    def _latest_history_scores(self, symbols: Sequence[str]) -> Dict[str, int]:
        if not symbols:
            return {}
        wanted = set(symbols)
        scores: Dict[str, int] = {}
        with self.db.get_session() as session:
            rows = session.execute(
                select(AnalysisHistory.code, AnalysisHistory.sentiment_score)
                .where(AnalysisHistory.code.in_(list(wanted)))
                .order_by(AnalysisHistory.code.asc(), desc(AnalysisHistory.created_at))
            ).all()
        for code, score in rows:
            if code in scores or score is None:
                continue
            try:
                scores[str(code)] = int(score)
            except (TypeError, ValueError):
                continue
        return scores

    @staticmethod
    def _user_to_dict(row: Any) -> Dict[str, Any]:
        return {
            "id": int(row.id),
            "user_key": row.user_key,
            "display_name": row.display_name,
            "email": row.email,
            "daily_email_enabled": bool(row.daily_email_enabled),
            "is_active": bool(row.is_active),
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
