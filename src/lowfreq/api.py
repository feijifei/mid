from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from lowfreq.application import QuantPlatform
from lowfreq.strategy_registry import StrategyLoadError


class BacktestRequest(BaseModel):
    strategy_id: str = "simple_trend"
    symbols: list[str] | None = None
    period: Literal["1m", "3m", "6m", "1y", "all"] = "1y"
    market: Literal["cn", "pink"] = "cn"


def create_router(platform: QuantPlatform) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/health")
    def health():
        return {"status": "ok", "data_source": platform.data_source.name}

    @router.get("/strategies")
    def strategies():
        return [asdict(strategy.metadata) for strategy in platform.registry.list()]

    @router.post("/strategies/reload")
    def reload_strategies():
        try:
            return [asdict(strategy.metadata) for strategy in platform.registry.reload()]
        except StrategyLoadError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/backtests")
    def backtest(request: BacktestRequest):
        try:
            result = asdict(
                platform.run_backtest(
                    request.strategy_id, request.symbols, request.period, request.market
                )
            )
            source = platform.backtest_data_source(request.market)
            result.update(
                {
                    "period": request.period,
                    "start_date": result["equity_curve"][0]["date"],
                    "end_date": result["equity_curve"][-1]["date"],
                    "data_source": source.name,
                    "market": request.market,
                    "currency": "USD" if request.market == "pink" else "CNY",
                    "baseline_value": platform.settings.initial_cash,
                    "instrument_names": source.instrument_names(
                        [symbol for symbol in result["series"] if symbol != "portfolio"]
                    ),
                    "instrument_sources": source.instrument_sources(
                        [symbol for symbol in result["series"] if symbol != "portfolio"]
                    ),
                }
            )
            return result
        except (KeyError, ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/paper/rebalance/{strategy_id}")
    def paper_rebalance(strategy_id: str):
        try:
            return platform.run_paper_rebalance(strategy_id)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/account")
    def account():
        bars = platform.data_source.load()
        latest_date = max(bars["date"])
        latest = bars[bars["date"] == latest_date]
        prices = dict(zip(latest["symbol"], latest["close"], strict=True))
        snapshot = platform.store.snapshot(prices)
        return {
            "cash": snapshot.cash,
            "market_value": snapshot.market_value,
            "equity": snapshot.equity,
            "positions": [
                {**asdict(position), "market_value": position.market_value}
                for position in snapshot.positions.values()
            ],
        }

    @router.get("/orders")
    def orders():
        return platform.store.orders()

    @router.post("/demo/reset")
    def reset_demo():
        platform.store.reset(platform.settings.initial_cash)
        return {"status": "reset"}

    return router
