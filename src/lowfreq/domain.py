from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class Position:
    symbol: str
    quantity: int
    average_price: float
    last_price: float

    @property
    def market_value(self) -> float:
        return self.quantity * self.last_price


@dataclass(frozen=True)
class PortfolioSnapshot:
    cash: float
    positions: dict[str, Position] = field(default_factory=dict)

    @property
    def market_value(self) -> float:
        return sum(position.market_value for position in self.positions.values())

    @property
    def equity(self) -> float:
        return self.cash + self.market_value


@dataclass(frozen=True)
class StrategyContext:
    as_of: date
    bars: pd.DataFrame
    portfolio: PortfolioSnapshot
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StrategyResult:
    target_weights: dict[str, float]
    diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StrategyMetadata:
    strategy_id: str
    name: str
    version: str
    description: str
    warmup_bars: int = 60
    rebalance_interval: int = 5


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(StrEnum):
    CREATED = "CREATED"
    RISK_REJECTED = "RISK_REJECTED"
    APPROVED = "APPROVED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class OrderIntent:
    client_order_id: str
    symbol: str
    side: OrderSide
    quantity: int
    reference_price: float
    target_weight: float
    created_at: datetime


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class BacktestConfig:
    initial_cash: float = 1_000_000.0
    commission_rate: float = 0.0003
    min_commission: float = 5.0
    slippage_bps: float = 2.0
    lot_size: int = 100


@dataclass(frozen=True)
class BacktestResult:
    strategy_id: str
    equity_curve: list[dict[str, Any]]
    series: dict[str, list[dict[str, Any]]]
    trades: list[dict[str, Any]]
    metrics: dict[str, float]
