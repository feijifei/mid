import math
import uuid
from datetime import UTC, datetime

from lowfreq.domain import (
    OrderIntent,
    OrderSide,
    PortfolioSnapshot,
    RiskDecision,
)


class PortfolioPlanner:
    def __init__(self, lot_size: int = 100, minimum_trade_value: float = 1000.0) -> None:
        self._lot_size = lot_size
        self._minimum_trade_value = minimum_trade_value

    def plan(
        self,
        targets: dict[str, float],
        portfolio: PortfolioSnapshot,
        prices: dict[str, float],
        batch_id: str,
    ) -> list[OrderIntent]:
        equity = portfolio.cash + sum(
            position.quantity * prices.get(symbol, position.last_price)
            for symbol, position in portfolio.positions.items()
        )
        symbols = set(targets) | set(portfolio.positions)
        intents: list[OrderIntent] = []
        for symbol in sorted(symbols):
            price = prices.get(symbol)
            if price is None or price <= 0:
                continue
            target_quantity = (
                math.floor(equity * targets.get(symbol, 0.0) / price / self._lot_size)
                * self._lot_size
            )
            current_quantity = (
                portfolio.positions.get(symbol).quantity if symbol in portfolio.positions else 0
            )
            delta = target_quantity - current_quantity
            if delta == 0 or abs(delta) * price < self._minimum_trade_value:
                continue
            side = OrderSide.BUY if delta > 0 else OrderSide.SELL
            intents.append(
                OrderIntent(
                    client_order_id=str(
                        uuid.uuid5(uuid.NAMESPACE_URL, f"{batch_id}:{symbol}:{side}")
                    ),
                    symbol=symbol,
                    side=side,
                    quantity=abs(delta),
                    reference_price=price,
                    target_weight=targets.get(symbol, 0.0),
                    created_at=datetime.now(UTC),
                )
            )
        return sorted(intents, key=lambda item: item.side != OrderSide.SELL)


class RiskEngine:
    def __init__(self, max_symbol_weight: float, max_order_notional_ratio: float = 0.45) -> None:
        self._max_symbol_weight = max_symbol_weight
        self._max_order_notional_ratio = max_order_notional_ratio

    def evaluate(self, order: OrderIntent, portfolio: PortfolioSnapshot) -> RiskDecision:
        reasons: list[str] = []
        notional = order.quantity * order.reference_price
        if order.quantity <= 0 or order.reference_price <= 0:
            reasons.append("订单数量和价格必须为正数")
        if order.target_weight > self._max_symbol_weight:
            reasons.append("目标单证券仓位超过限制")
        if notional > portfolio.equity * self._max_order_notional_ratio:
            reasons.append("单笔订单金额超过账户限制")
        if order.side == OrderSide.BUY and notional > portfolio.cash:
            reasons.append("可用资金不足")
        if order.side == OrderSide.SELL:
            held = portfolio.positions.get(order.symbol)
            if held is None or order.quantity > held.quantity:
                reasons.append("可卖持仓不足")
        return RiskDecision(approved=not reasons, reasons=tuple(reasons))
