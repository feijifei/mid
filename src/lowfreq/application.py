from datetime import date

import pandas as pd

from lowfreq.backtest import BacktestEngine
from lowfreq.config import Settings
from lowfreq.domain import BacktestConfig, StrategyContext
from lowfreq.market_data import (
    CsvMarketDataSource,
    DemoMarketDataSource,
    EastmoneyEtfDataSource,
    MarketDataSource,
    PinkMarketDataSource,
)
from lowfreq.persistence import TradingStore
from lowfreq.strategy_registry import StrategyRegistry, validate_result_weights
from lowfreq.trading import PortfolioPlanner, RiskEngine


class QuantPlatform:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.registry = StrategyRegistry(settings.plugin_dir)
        self.registry.reload()
        self.data_source = self._create_data_source(settings)
        self.pink_data_source = PinkMarketDataSource(
            settings.pink_cache_path,
            [symbol.strip() for symbol in settings.pink_symbols.split(",")],
            settings.market_start_date,
        )
        self.store = TradingStore(settings.database_url, settings.initial_cash)
        self.backtester = BacktestEngine()
        self.planner = PortfolioPlanner(settings.lot_size)
        self.risk = RiskEngine(settings.max_symbol_weight)

    @staticmethod
    def _create_data_source(settings: Settings) -> MarketDataSource:
        if settings.data_source == "csv":
            return CsvMarketDataSource(settings.csv_data_path)
        if settings.data_source == "eastmoney":
            return EastmoneyEtfDataSource(
                settings.market_cache_path,
                [symbol.strip() for symbol in settings.market_symbols.split(",")],
                settings.market_start_date,
            )
        return DemoMarketDataSource()

    def backtest_data_source(self, market: str) -> MarketDataSource:
        if market == "pink":
            return self.pink_data_source
        if market == "cn":
            return self.data_source
        raise ValueError(f"不支持的市场组: {market}")

    def run_backtest(
        self,
        strategy_id: str,
        symbols: list[str] | None = None,
        period: str = "1y",
        market: str = "cn",
    ):
        strategy = self.registry.get(strategy_id)
        bars = self.backtest_data_source(market).load(symbols)
        end_date = pd.Timestamp(max(bars["date"]))
        offsets = {
            "1m": pd.DateOffset(months=1),
            "3m": pd.DateOffset(months=3),
            "6m": pd.DateOffset(months=6),
            "1y": pd.DateOffset(years=1),
        }
        start_date = (end_date - offsets[period]).date() if period in offsets else None
        return self.backtester.run(
            strategy,
            bars,
            BacktestConfig(
                initial_cash=self.settings.initial_cash,
                commission_rate=self.settings.commission_rate,
                min_commission=1.0 if market == "pink" else self.settings.min_commission,
                slippage_bps=50.0 if market == "pink" else self.settings.slippage_bps,
                lot_size=1 if market == "pink" else self.settings.lot_size,
            ),
            start_date=start_date,
        )

    def run_paper_rebalance(self, strategy_id: str) -> dict[str, object]:
        strategy = self.registry.get(strategy_id)
        bars = self.data_source.load()
        as_of = max(bars["date"])
        latest = bars[bars["date"] == as_of]
        prices = dict(zip(latest["symbol"], latest["close"], strict=True))
        snapshot = self.store.snapshot(prices)
        context = StrategyContext(as_of=as_of, bars=bars, portfolio=snapshot)
        result = strategy.generate(context)
        validate_result_weights(result.target_weights)
        batch_id = (
            f"{strategy_id}:{strategy.metadata.version}:"
            f"{date.fromisoformat(str(as_of)).isoformat()}"
        )
        orders = self.planner.plan(result.target_weights, snapshot, prices, batch_id)
        outcomes: list[dict[str, object]] = []
        for order in orders:
            current = self.store.snapshot(prices)
            decision = self.risk.evaluate(order, current)
            if not decision.approved:
                reason = "; ".join(decision.reasons)
                self.store.record_rejection(batch_id, order, reason)
                outcomes.append(
                    {"order_id": order.client_order_id, "status": "RISK_REJECTED", "reason": reason}
                )
                continue
            filled = self.store.fill(
                batch_id,
                order,
                self.settings.commission_rate,
                self.settings.min_commission,
            )
            outcomes.append(
                {
                    "order_id": order.client_order_id,
                    "status": "FILLED" if filled else "DUPLICATE_OR_REJECTED",
                }
            )
        return {
            "batch_id": batch_id,
            "as_of": as_of.isoformat(),
            "targets": result.target_weights,
            "diagnostics": result.diagnostics,
            "orders": outcomes,
        }
