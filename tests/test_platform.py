from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

from lowfreq.app import app
from lowfreq.application import QuantPlatform
from lowfreq.config import Settings
from lowfreq.domain import OrderIntent, OrderSide, PortfolioSnapshot
from lowfreq.market_data import EastmoneyEtfDataSource, PinkMarketDataSource
from lowfreq.strategy_registry import StrategyRegistry
from lowfreq.trading import RiskEngine


def test_default_strategy_is_discoverable():
    registry = StrategyRegistry(Path("strategy_plugins"))
    loaded = registry.reload()
    assert [strategy.metadata.strategy_id for strategy in loaded] == ["simple_trend"]


def test_backtest_trades_after_signal_date():
    client = TestClient(app)
    response = client.post("/api/backtests", json={"strategy_id": "simple_trend"})
    assert response.status_code == 200
    result = response.json()
    assert result["trades"]
    assert all(trade["trade_date"] > trade["signal_date"] for trade in result["trades"])
    assert result["metrics"]["trade_count"] > 0


def test_backtest_period_limits_equity_curve():
    client = TestClient(app)
    response = client.post("/api/backtests", json={"strategy_id": "simple_trend", "period": "1m"})

    assert response.status_code == 200
    result = response.json()
    assert result["period"] == "1m"
    assert result["start_date"] >= "2026-07-31"
    assert result["end_date"] == "2026-08-31"
    assert len(result["equity_curve"]) <= 24


def test_backtest_rejects_unknown_period():
    client = TestClient(app)
    response = client.post("/api/backtests", json={"strategy_id": "simple_trend", "period": "2y"})

    assert response.status_code == 422


def test_backtest_rejects_unknown_market():
    client = TestClient(app)
    response = client.post(
        "/api/backtests",
        json={"strategy_id": "simple_trend", "market": "unknown"},
    )

    assert response.status_code == 422


def test_backtest_exposes_portfolio_and_etf_curves():
    client = TestClient(app)
    response = client.post("/api/backtests", json={"strategy_id": "simple_trend", "period": "3m"})

    assert response.status_code == 200
    result = response.json()
    assert set(result["series"]) == {"portfolio", "510300", "510500", "518880", "511010"}
    assert result["instrument_names"]["510300"] == "沪深300ETF"
    assert result["series"]["portfolio"] == result["equity_curve"]
    assert all(result["series"][symbol] for symbol in result["series"])


def test_eastmoney_cache_only_returns_requested_symbols(tmp_path):
    cache = tmp_path / "market.csv"
    pd.DataFrame(
        [
            {
                "date": "2026-09-09",
                "symbol": symbol,
                "open": 10,
                "high": 11,
                "low": 9,
                "close": 10,
                "volume": 100,
            }
            for symbol in ("600519", "510300")
        ]
    ).to_csv(cache, index=False)
    source = EastmoneyEtfDataSource(cache, ["600519"], "20240101")

    bars = source.load(["600519"])

    assert bars["symbol"].unique().tolist() == ["600519"]


def test_pink_data_falls_back_to_sina_when_eastmoney_fails(tmp_path):
    class FakeAkshare:
        @staticmethod
        def stock_us_hist(**_kwargs):
            raise ConnectionError("eastmoney unavailable")

        @staticmethod
        def stock_us_daily(**_kwargs):
            return pd.DataFrame(
                [
                    {
                        "date": "2026-09-08",
                        "open": 10,
                        "high": 11,
                        "low": 9,
                        "close": 10,
                        "volume": 100,
                    }
                ]
            )

    source = PinkMarketDataSource(tmp_path / "pink.csv", ["TCEHY"], "20240101")

    bars, provider = source._download_symbol(FakeAkshare(), "TCEHY")

    assert bars["symbol"].unique().tolist() == ["TCEHY"]
    assert provider == "新浪美股日线（备用）"


def test_every_portfolio_point_contains_account_snapshot():
    client = TestClient(app)
    response = client.post("/api/backtests", json={"strategy_id": "simple_trend", "period": "3m"})

    assert response.status_code == 200
    points = response.json()["equity_curve"]
    assert points
    assert all({"cash", "market_value", "positions"} <= point.keys() for point in points)
    assert all(
        abs(point["cash"] + point["market_value"] - point["equity"]) < 0.02
        for point in points
    )
    assert all(
        {"symbol", "quantity", "average_price", "last_price", "market_value", "weight"}
        <= position.keys()
        for point in points
        for position in point["positions"]
    )


def test_every_trade_contains_strategy_reason():
    client = TestClient(app)
    response = client.post("/api/backtests", json={"strategy_id": "simple_trend", "period": "1y"})

    assert response.status_code == 200
    trades = response.json()["trades"]
    assert trades
    assert all(trade["reason"] for trade in trades)
    assert all("portfolio_after" in trade for trade in trades)
    assert all(
        0.999
        <= trade["portfolio_after"]["cash_weight"]
        + sum(position["weight"] for position in trade["portfolio_after"]["positions"])
        <= 1.001
        for trade in trades
    )
    assert response.json()["baseline_value"] == 1_000_000.0


def test_risk_rejects_oversized_order():
    settings = Settings()
    risk = RiskEngine(settings.max_symbol_weight)
    order = OrderIntent(
        client_order_id="test",
        symbol="510300",
        side=OrderSide.BUY,
        quantity=100_000,
        reference_price=10.0,
        target_weight=1.0,
        created_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
    )
    decision = risk.evaluate(order, PortfolioSnapshot(cash=1_000_000))
    assert not decision.approved
    assert "目标单证券仓位超过限制" in decision.reasons


def test_strategy_reload_endpoint():
    client = TestClient(app)
    response = client.post("/api/strategies/reload")
    assert response.status_code == 200
    assert response.json()[0]["strategy_id"] == "simple_trend"


def test_account_positions_include_market_value():
    client = TestClient(app)
    client.post("/api/demo/reset")
    client.post("/api/paper/rebalance/simple_trend")

    response = client.get("/api/account")

    assert response.status_code == 200
    assert response.json()["positions"]
    assert all(position["market_value"] > 0 for position in response.json()["positions"])


def test_paper_rebalance_is_idempotent(tmp_path):
    platform = QuantPlatform(
        Settings(
            database_url=f"sqlite:///{tmp_path / 'paper.db'}",
            plugin_dir=Path("strategy_plugins"),
        )
    )

    first = platform.run_paper_rebalance("simple_trend")
    second = platform.run_paper_rebalance("simple_trend")

    assert first["batch_id"].startswith("simple_trend:1.0.0:")
    assert [order["status"] for order in first["orders"]] == ["FILLED", "FILLED"]
    assert second["orders"] == []
    assert len(platform.store.orders()) == 2
