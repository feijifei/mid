from lowfreq.domain import StrategyContext, StrategyMetadata, StrategyResult


class SimpleTrendStrategy:
    """Equal-weight securities whose short moving average is above the long moving average."""

    metadata = StrategyMetadata(
        strategy_id="simple_trend",
        name="基础双均线趋势策略",
        version="1.0.0",
        description="20日均线高于60日均线时等权持有，最多持有3只股票或ETF。",
        warmup_bars=60,
        rebalance_interval=5,
    )

    def generate(self, context: StrategyContext) -> StrategyResult:
        short_window = int(context.parameters.get("short_window", 20))
        long_window = int(context.parameters.get("long_window", 60))
        max_positions = int(context.parameters.get("max_positions", 3))
        scores: dict[str, float] = {}
        trend_values: dict[str, float] = {}
        averages: dict[str, tuple[float, float]] = {}
        for symbol, frame in context.bars.groupby("symbol"):
            closes = frame.sort_values("date")["close"].tail(long_window)
            if len(closes) < long_window:
                continue
            short_average = float(closes.tail(short_window).mean())
            long_average = float(closes.mean())
            symbol = str(symbol)
            trend_values[symbol] = short_average / long_average - 1
            averages[symbol] = (short_average, long_average)
            if short_average > long_average:
                scores[symbol] = trend_values[symbol]

        selected = sorted(scores, key=scores.get, reverse=True)[:max_positions]
        weight = min(0.95 / len(selected), 0.40) if selected else 0.0
        targets = {symbol: weight for symbol in selected}
        reasons: dict[str, str] = {}
        for symbol, trend in trend_values.items():
            short_average, long_average = averages[symbol]
            if symbol in selected:
                rank = selected.index(symbol) + 1
                reasons[symbol] = (
                    f"20日均线{short_average:.4f}高于60日均线{long_average:.4f}，"
                    f"趋势强度{trend * 100:.2f}%，排名第{rank}，目标权重{weight * 100:.1f}%"
                )
            elif trend <= 0:
                reasons[symbol] = (
                    f"20日均线{short_average:.4f}不高于60日均线{long_average:.4f}，"
                    f"趋势强度{trend * 100:.2f}%，触发清仓"
                )
            else:
                reasons[symbol] = (
                    f"趋势强度{trend * 100:.2f}%仍为正，但未进入前{max_positions}名，触发调出"
                )
        return StrategyResult(
            target_weights=targets,
            diagnostics={
                "as_of": context.as_of.isoformat(),
                "selected": selected,
                "trend_scores": {symbol: round(scores[symbol], 6) for symbol in selected},
                "cash_weight": round(1 - sum(targets.values()), 6),
                "reasons": reasons,
            },
        )


def create_strategy() -> SimpleTrendStrategy:
    return SimpleTrendStrategy()
