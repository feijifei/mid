from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import Float, Integer, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from lowfreq.domain import OrderIntent, OrderStatus, PortfolioSnapshot, Position


class Base(DeclarativeBase):
    pass


class AccountRow(Base):
    __tablename__ = "accounts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cash: Mapped[float] = mapped_column(Float)


class PositionRow(Base):
    __tablename__ = "positions"
    symbol: Mapped[str] = mapped_column(String(20), primary_key=True)
    quantity: Mapped[int] = mapped_column(Integer)
    average_price: Mapped[float] = mapped_column(Float)
    last_price: Mapped[float] = mapped_column(Float)


class OrderRow(Base):
    __tablename__ = "orders"
    client_order_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    batch_id: Mapped[str] = mapped_column(String(64), index=True)
    symbol: Mapped[str] = mapped_column(String(20))
    side: Mapped[str] = mapped_column(String(8))
    quantity: Mapped[int] = mapped_column(Integer)
    price: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(24))
    reason: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[str] = mapped_column(String(40))


class AuditRow(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(50))
    detail: Mapped[str] = mapped_column(String(1000))
    created_at: Mapped[str] = mapped_column(String(40))


class TradingStore:
    def __init__(self, database_url: str, initial_cash: float) -> None:
        if database_url.startswith("sqlite:///"):
            path = Path(database_url.removeprefix("sqlite:///"))
            path.parent.mkdir(parents=True, exist_ok=True)
        connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
        self.engine = create_engine(database_url, connect_args=connect_args)
        Base.metadata.create_all(self.engine)
        with Session(self.engine) as session:
            if session.get(AccountRow, 1) is None:
                session.add(AccountRow(id=1, cash=initial_cash))
                session.commit()

    def snapshot(self, prices: dict[str, float] | None = None) -> PortfolioSnapshot:
        prices = prices or {}
        with Session(self.engine) as session:
            account = session.get(AccountRow, 1)
            rows = session.scalars(select(PositionRow)).all()
            positions = {
                row.symbol: Position(
                    row.symbol,
                    row.quantity,
                    row.average_price,
                    prices.get(row.symbol, row.last_price),
                )
                for row in rows
                if row.quantity > 0
            }
            return PortfolioSnapshot(cash=account.cash, positions=positions)

    def record_rejection(self, batch_id: str, order: OrderIntent, reason: str) -> None:
        self._record_order(batch_id, order, OrderStatus.RISK_REJECTED, reason)

    def fill(
        self, batch_id: str, order: OrderIntent, commission_rate: float, min_commission: float
    ) -> bool:
        with Session(self.engine) as session:
            if session.get(OrderRow, order.client_order_id) is not None:
                return False
            account = session.get(AccountRow, 1)
            position = session.get(PositionRow, order.symbol)
            fee = max(min_commission, order.quantity * order.reference_price * commission_rate)
            notional = order.quantity * order.reference_price
            if order.side.value == "BUY":
                if account.cash < notional + fee:
                    self._add_order(
                        session, batch_id, order, OrderStatus.REJECTED, "撮合时资金不足"
                    )
                    session.commit()
                    return False
                old_quantity = position.quantity if position else 0
                old_cost = old_quantity * position.average_price if position else 0.0
                if position is None:
                    position = PositionRow(
                        symbol=order.symbol,
                        quantity=0,
                        average_price=order.reference_price,
                        last_price=order.reference_price,
                    )
                    session.add(position)
                position.quantity += order.quantity
                position.average_price = (old_cost + notional) / position.quantity
                position.last_price = order.reference_price
                account.cash -= notional + fee
            else:
                if position is None or position.quantity < order.quantity:
                    self._add_order(
                        session, batch_id, order, OrderStatus.REJECTED, "撮合时持仓不足"
                    )
                    session.commit()
                    return False
                position.quantity -= order.quantity
                position.last_price = order.reference_price
                account.cash += notional - fee
            self._add_order(session, batch_id, order, OrderStatus.FILLED, "")
            session.add(
                AuditRow(
                    event_type="ORDER_FILLED",
                    detail=(
                        f"{order.side.value} {order.symbol} "
                        f"{order.quantity}@{order.reference_price}"
                    ),
                    created_at=datetime.now(UTC).isoformat(),
                )
            )
            session.commit()
            return True

    def _record_order(self, batch_id, order, status, reason) -> None:
        with Session(self.engine) as session:
            if session.get(OrderRow, order.client_order_id) is None:
                self._add_order(session, batch_id, order, status, reason)
                session.commit()

    @staticmethod
    def _add_order(session, batch_id, order, status, reason) -> None:
        session.add(
            OrderRow(
                client_order_id=order.client_order_id,
                batch_id=batch_id,
                symbol=order.symbol,
                side=order.side.value,
                quantity=order.quantity,
                price=order.reference_price,
                status=status.value,
                reason=reason,
                created_at=order.created_at.isoformat(),
            )
        )

    def orders(self, limit: int = 100) -> list[dict[str, object]]:
        with Session(self.engine) as session:
            rows = session.scalars(
                select(OrderRow).order_by(OrderRow.created_at.desc()).limit(limit)
            ).all()
            return [
                {
                    "client_order_id": row.client_order_id,
                    "batch_id": row.batch_id,
                    "symbol": row.symbol,
                    "side": row.side,
                    "quantity": row.quantity,
                    "price": row.price,
                    "status": row.status,
                    "reason": row.reason,
                    "created_at": row.created_at,
                }
                for row in rows
            ]

    def reset(self, initial_cash: float) -> None:
        with Session(self.engine) as session:
            session.query(OrderRow).delete()
            session.query(PositionRow).delete()
            session.query(AuditRow).delete()
            account = session.get(AccountRow, 1)
            account.cash = initial_cash
            session.commit()
