import math
from datetime import date

import numpy as np
import pandas as pd

from lowfreq.domain import (
    BacktestConfig,
    BacktestResult,
    PortfolioSnapshot,
    Position,
    StrategyContext,
)
from lowfreq.strategy_api import Strategy
from lowfreq.strategy_registry import validate_result_weights


class BacktestEngine:
    def run(
        self,
        strategy: Strategy,
        bars: pd.DataFrame,
        config: BacktestConfig,
        start_date: date | None = None,
    ) -> BacktestResult:
        dates = sorted(bars["date"].unique())
        if len(dates) <= strategy.metadata.warmup_bars + 1:
            raise ValueError("可用行情不足以满足策略预热期")

        evaluation_start = strategy.metadata.warmup_bars
        if start_date is not None:
            candidates = [index for index, value in enumerate(dates) if value >= start_date]
            if not candidates:
                raise ValueError("选择的回测区间没有行情")
            evaluation_start = max(evaluation_start, candidates[0])
        if evaluation_start >= len(dates) - 1:
            raise ValueError("回测区间过短，无法执行策略")

        cash = config.initial_cash
        quantities: dict[str, int] = {}
        average_prices: dict[str, float] = {}
        pending_targets: dict[str, float] | None = None
        pending_signal_date = None
        pending_reasons: dict[str, str] = {}
        trades: list[dict[str, object]] = []
        curve: list[dict[str, object]] = []

        # The day before the requested interval is used only to generate the first signal.
        for index in range(evaluation_start - 1, len(dates)):
            trading_date = dates[index]
            day = bars[bars["date"] == trading_date].set_index("symbol")
            if pending_targets is not None:
                cash = self._rebalance(
                    pending_targets,
                    day,
                    cash,
                    quantities,
                    average_prices,
                    config,
                    trades,
                    pending_signal_date,
                    trading_date,
                    pending_reasons,
                )
                pending_targets = None
                pending_reasons = {}

            close_prices = day["close"].to_dict()
            equity = cash + sum(
                quantity * close_prices.get(symbol, average_prices[symbol])
                for symbol, quantity in quantities.items()
            )
            if index >= evaluation_start:
                positions = [
                    {
                        "symbol": symbol,
                        "quantity": quantity,
                        "average_price": round(average_prices[symbol], 4),
                        "last_price": round(float(close_prices[symbol]), 4),
                        "market_value": round(quantity * float(close_prices[symbol]), 2),
                        "weight": round(quantity * float(close_prices[symbol]) / equity, 6),
                    }
                    for symbol, quantity in sorted(quantities.items())
                    if quantity > 0 and symbol in close_prices
                ]
                market_value = sum(float(position["market_value"]) for position in positions)
                curve.append(
                    {
                        "date": trading_date.isoformat(),
                        "equity": round(equity, 2),
                        "cash": round(cash, 2),
                        "market_value": round(market_value, 2),
                        "positions": positions,
                    }
                )

            first_signal = index == evaluation_start - 1
            scheduled = (
                index >= evaluation_start
                and (index - evaluation_start + 1) % strategy.metadata.rebalance_interval == 0
            )
            if (first_signal or scheduled) and index < len(dates) - 1:
                history = bars[bars["date"] <= trading_date].copy()
                positions = {
                    symbol: Position(symbol, quantity, average_prices[symbol], close_prices[symbol])
                    for symbol, quantity in quantities.items()
                    if quantity > 0 and symbol in close_prices
                }
                result = strategy.generate(
                    StrategyContext(
                        as_of=trading_date,
                        bars=history,
                        portfolio=PortfolioSnapshot(cash=cash, positions=positions),
                    )
                )
                validate_result_weights(result.target_weights)
                pending_targets = result.target_weights
                pending_signal_date = trading_date
                pending_reasons = dict(result.diagnostics.get("reasons", {}))

        metrics = self._metrics(curve, trades)
        series = self._build_series(bars, curve, config.initial_cash)
        series = {"portfolio": curve, **series}
        return BacktestResult(strategy.metadata.strategy_id, curve, series, trades, metrics)

    @staticmethod
    def _rebalance(
        targets: dict[str, float],
        day: pd.DataFrame,
        cash: float,
        quantities: dict[str, int],
        average_prices: dict[str, float],
        config: BacktestConfig,
        trades: list[dict[str, object]],
        signal_date: object,
        trade_date: object,
        reasons: dict[str, str],
    ) -> float:
        first_trade_index = len(trades)
        prices = day["open"].to_dict()
        equity = cash + sum(
            quantity * prices.get(symbol, average_prices[symbol])
            for symbol, quantity in quantities.items()
        )
        desired = {
            symbol: math.floor(equity * weight / prices[symbol] / config.lot_size) * config.lot_size
            for symbol, weight in targets.items()
            if symbol in prices
        }
        for symbol in list(quantities):
            desired.setdefault(symbol, quantities[symbol] if symbol not in prices else 0)

        deltas = {
            symbol: desired_qty - quantities.get(symbol, 0)
            for symbol, desired_qty in desired.items()
        }
        for symbol, delta in sorted(deltas.items(), key=lambda item: item[1]):
            if delta >= 0:
                continue
            fill_price = prices[symbol] * (1 - config.slippage_bps / 10_000)
            fee = max(config.min_commission, abs(delta) * fill_price * config.commission_rate)
            cash += abs(delta) * fill_price - fee
            quantities[symbol] = desired[symbol]
            BacktestEngine._record_trade(
                trades,
                signal_date,
                trade_date,
                symbol,
                "SELL",
                abs(delta),
                fill_price,
                fee,
                reasons.get(symbol, "目标权重降至零或低于当前持仓，触发卖出"),
            )

        for symbol, delta in sorted(deltas.items(), key=lambda item: item[1], reverse=True):
            if delta <= 0:
                continue
            fill_price = prices[symbol] * (1 + config.slippage_bps / 10_000)
            affordable = (
                math.floor(
                    max(0.0, cash - config.min_commission)
                    / (fill_price * (1 + config.commission_rate))
                    / config.lot_size
                )
                * config.lot_size
            )
            quantity = min(delta, affordable)
            if quantity <= 0:
                continue
            fee = max(config.min_commission, quantity * fill_price * config.commission_rate)
            cash -= quantity * fill_price + fee
            old_qty = quantities.get(symbol, 0)
            old_cost = old_qty * average_prices.get(symbol, fill_price)
            quantities[symbol] = old_qty + quantity
            average_prices[symbol] = (old_cost + quantity * fill_price) / quantities[symbol]
            BacktestEngine._record_trade(
                trades,
                signal_date,
                trade_date,
                symbol,
                "BUY",
                quantity,
                fill_price,
                fee,
                reasons.get(symbol, "目标权重高于当前持仓，触发买入"),
            )
        equity_after = cash + sum(
            quantity * prices.get(symbol, average_prices[symbol])
            for symbol, quantity in quantities.items()
        )
        positions_after = [
            {
                "symbol": symbol,
                "quantity": quantity,
                "weight": round(quantity * prices[symbol] / equity_after, 6),
            }
            for symbol, quantity in sorted(quantities.items())
            if quantity > 0 and symbol in prices
        ]
        portfolio_after = {
            "cash": round(cash, 2),
            "cash_weight": round(cash / equity_after, 6),
            "positions": positions_after,
        }
        for trade in trades[first_trade_index:]:
            trade["portfolio_after"] = portfolio_after
        return cash

    @staticmethod
    def _record_trade(
        trades, signal_date, trade_date, symbol, side, quantity, price, fee, reason
    ) -> None:
        trades.append(
            {
                "signal_date": signal_date.isoformat(),
                "trade_date": trade_date.isoformat(),
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "price": round(price, 4),
                "fee": round(fee, 2),
                "reason": reason,
            }
        )

    @staticmethod
    def _build_series(
        bars: pd.DataFrame, curve: list[dict[str, object]], initial_cash: float
    ) -> dict[str, list[dict[str, object]]]:
        first_date = date.fromisoformat(str(curve[0]["date"]))
        result: dict[str, list[dict[str, object]]] = {}
        for symbol, frame in bars[bars["date"] >= first_date].groupby("symbol"):
            ordered = frame.sort_values("date")
            base_price = float(ordered.iloc[0]["close"])
            result[str(symbol)] = [
                {
                    "date": row.date.isoformat(),
                    "equity": round(initial_cash * float(row.close) / base_price, 2),
                }
                for row in ordered.itertuples()
            ]
        return result

    @staticmethod
    def _metrics(
        curve: list[dict[str, object]], trades: list[dict[str, object]]
    ) -> dict[str, float]:
        equity = pd.Series([float(point["equity"]) for point in curve])
        returns = equity.pct_change().dropna()
        total_return = equity.iloc[-1] / equity.iloc[0] - 1
        annualized = (1 + total_return) ** (252 / max(1, len(returns))) - 1
        daily_volatility = float(returns.std(ddof=1)) if len(returns) > 1 else 0.0
        volatility = daily_volatility * np.sqrt(252)
        sharpe = (
            float(returns.mean() / daily_volatility * np.sqrt(252)) if daily_volatility else 0.0
        )
        drawdown = equity / equity.cummax() - 1
        max_drawdown = float(drawdown.min())
        return {
            "total_return": round(float(total_return), 6),
            "annualized_return": round(float(annualized), 6),
            "annualized_volatility": round(volatility, 6),
            "sharpe": round(float(sharpe), 4),
            "max_drawdown": round(max_drawdown, 6),
            "trade_count": float(len(trades)),
        }
