# -*- coding: utf-8 -*-
"""Repository for daily analysis user profiles and required symbols."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, select

from src.storage import (
    DailyAnalysisUser,
    DailyAnalysisUserStock,
    DatabaseManager,
)


class DailyAnalysisUserRepository:
    """DB access for user-scoped daily analysis inputs."""

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        self.db = db_manager or DatabaseManager.get_instance()

    def upsert_user(
        self,
        *,
        user_key: str,
        display_name: Optional[str] = None,
        email: Optional[str] = None,
        daily_email_enabled: bool = True,
        is_active: bool = True,
    ) -> DailyAnalysisUser:
        with self.db.get_session() as session:
            row = session.execute(
                select(DailyAnalysisUser).where(DailyAnalysisUser.user_key == user_key).limit(1)
            ).scalar_one_or_none()
            if row is None:
                row = DailyAnalysisUser(user_key=user_key)
                session.add(row)

            row.display_name = display_name
            row.email = email
            row.daily_email_enabled = bool(daily_email_enabled)
            row.is_active = bool(is_active)
            row.updated_at = datetime.now()
            session.commit()
            session.refresh(row)
            return row

    def list_users(self, include_inactive: bool = False) -> List[DailyAnalysisUser]:
        with self.db.get_session() as session:
            query = select(DailyAnalysisUser)
            if not include_inactive:
                query = query.where(DailyAnalysisUser.is_active.is_(True))
            return list(session.execute(query.order_by(DailyAnalysisUser.id.asc())).scalars().all())

    def get_user_by_key(self, user_key: str) -> Optional[DailyAnalysisUser]:
        with self.db.get_session() as session:
            return session.execute(
                select(DailyAnalysisUser).where(DailyAnalysisUser.user_key == user_key).limit(1)
            ).scalar_one_or_none()

    def upsert_user_stock(
        self,
        *,
        user_id: int,
        symbol: str,
        stock_name: Optional[str],
        market: str,
        relation_type: str,
        shares: Optional[float] = None,
        avg_cost: Optional[float] = None,
        buy_date: Optional[Any] = None,
        note: Optional[str] = None,
        enabled: bool = True,
    ) -> DailyAnalysisUserStock:
        with self.db.get_session() as session:
            row = session.execute(
                select(DailyAnalysisUserStock)
                .where(
                    and_(
                        DailyAnalysisUserStock.user_id == user_id,
                        DailyAnalysisUserStock.symbol == symbol,
                    )
                )
                .limit(1)
            ).scalar_one_or_none()
            if row is None:
                row = DailyAnalysisUserStock(user_id=user_id, symbol=symbol)
                session.add(row)

            row.stock_name = stock_name
            row.market = market
            row.relation_type = relation_type
            row.shares = shares
            row.avg_cost = avg_cost
            row.buy_date = buy_date
            row.note = note
            row.enabled = bool(enabled)
            row.updated_at = datetime.now()
            session.commit()
            session.refresh(row)
            return row

    def list_user_stocks(
        self,
        *,
        user_key: Optional[str] = None,
        include_disabled: bool = False,
    ) -> List[DailyAnalysisUserStock]:
        with self.db.get_session() as session:
            query = (
                select(DailyAnalysisUserStock)
                .join(DailyAnalysisUser, DailyAnalysisUserStock.user_id == DailyAnalysisUser.id)
                .where(DailyAnalysisUser.is_active.is_(True))
            )
            if user_key:
                query = query.where(DailyAnalysisUser.user_key == user_key)
            if not include_disabled:
                query = query.where(DailyAnalysisUserStock.enabled.is_(True))
            return list(
                session.execute(
                    query.order_by(
                        DailyAnalysisUser.user_key.asc(),
                        DailyAnalysisUserStock.relation_type.asc(),
                        DailyAnalysisUserStock.symbol.asc(),
                    )
                ).scalars().all()
            )

    def list_user_stock_payloads(
        self,
        *,
        user_key: Optional[str] = None,
        include_disabled: bool = False,
    ) -> List[Dict[str, Any]]:
        with self.db.get_session() as session:
            query = (
                select(DailyAnalysisUser, DailyAnalysisUserStock)
                .join(DailyAnalysisUserStock, DailyAnalysisUserStock.user_id == DailyAnalysisUser.id)
                .where(DailyAnalysisUser.is_active.is_(True))
            )
            if user_key:
                query = query.where(DailyAnalysisUser.user_key == user_key)
            if not include_disabled:
                query = query.where(DailyAnalysisUserStock.enabled.is_(True))
            rows = session.execute(
                query.order_by(
                    DailyAnalysisUser.user_key.asc(),
                    DailyAnalysisUserStock.relation_type.asc(),
                    DailyAnalysisUserStock.symbol.asc(),
                )
            ).all()
            return [
                {
                    "id": int(stock.id),
                    "user_id": int(user.id),
                    "user_key": user.user_key,
                    "display_name": user.display_name,
                    "email": user.email,
                    "daily_email_enabled": bool(user.daily_email_enabled),
                    "symbol": stock.symbol,
                    "stock_name": stock.stock_name,
                    "market": stock.market,
                    "relation_type": stock.relation_type,
                    "shares": stock.shares,
                    "avg_cost": stock.avg_cost,
                    "buy_date": stock.buy_date.isoformat() if stock.buy_date else None,
                    "note": stock.note,
                    "enabled": bool(stock.enabled),
                    "created_at": stock.created_at.isoformat() if stock.created_at else None,
                    "updated_at": stock.updated_at.isoformat() if stock.updated_at else None,
                }
                for user, stock in rows
            ]

    def set_user_stock_enabled(self, stock_id: int, enabled: bool) -> bool:
        with self.db.get_session() as session:
            row = session.execute(
                select(DailyAnalysisUserStock).where(DailyAnalysisUserStock.id == stock_id).limit(1)
            ).scalar_one_or_none()
            if row is None:
                return False
            row.enabled = bool(enabled)
            row.updated_at = datetime.now()
            session.commit()
            return True

    def delete_user_stock(self, stock_id: int) -> bool:
        with self.db.get_session() as session:
            row = session.execute(
                select(DailyAnalysisUserStock).where(DailyAnalysisUserStock.id == stock_id).limit(1)
            ).scalar_one_or_none()
            if row is None:
                return False
            session.delete(row)
            session.commit()
            return True
