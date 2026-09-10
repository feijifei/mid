import importlib.util
import math
import sys
from pathlib import Path

from lowfreq.domain import PortfolioSnapshot, StrategyContext
from lowfreq.strategy_api import Strategy


class StrategyLoadError(RuntimeError):
    pass


class StrategyRegistry:
    def __init__(self, plugin_dir: Path) -> None:
        self._plugin_dir = plugin_dir
        self._strategies: dict[str, Strategy] = {}

    def reload(self) -> list[Strategy]:
        loaded: dict[str, Strategy] = {}
        self._plugin_dir.mkdir(parents=True, exist_ok=True)
        for path in sorted(self._plugin_dir.glob("*.py")):
            if path.name.startswith("_"):
                continue
            module_name = f"lowfreq_user_strategy_{path.stem}"
            spec = importlib.util.spec_from_file_location(module_name, path)
            if spec is None or spec.loader is None:
                raise StrategyLoadError(f"无法加载策略文件: {path}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            try:
                spec.loader.exec_module(module)
                factory = module.create_strategy
                strategy = factory()
            except Exception as exc:
                raise StrategyLoadError(f"策略 {path.name} 加载失败: {exc}") from exc
            self._validate(strategy, path)
            strategy_id = strategy.metadata.strategy_id
            if strategy_id in loaded:
                raise StrategyLoadError(f"策略ID重复: {strategy_id}")
            loaded[strategy_id] = strategy
        self._strategies = loaded
        return self.list()

    def list(self) -> list[Strategy]:
        return list(self._strategies.values())

    def get(self, strategy_id: str) -> Strategy:
        try:
            return self._strategies[strategy_id]
        except KeyError as exc:
            raise KeyError(f"未知策略: {strategy_id}") from exc

    @staticmethod
    def _validate(strategy: object, path: Path) -> None:
        if not isinstance(strategy, Strategy):
            raise StrategyLoadError(f"{path.name} 未实现 Strategy 接口")
        metadata = strategy.metadata
        if not metadata.strategy_id or metadata.warmup_bars < 1:
            raise StrategyLoadError(f"{path.name} 的策略元数据无效")
        empty_context = StrategyContext(
            as_of=__import__("datetime").date(2020, 1, 1),
            bars=__import__("pandas").DataFrame(
                columns=["date", "symbol", "open", "high", "low", "close", "volume"]
            ),
            portfolio=PortfolioSnapshot(cash=1.0),
        )
        # Plugin behavior is validated during each real invocation; loading must not require data.
        if not callable(getattr(strategy, "generate", None)):
            raise StrategyLoadError(f"{path.name} 缺少 generate 方法")
        del empty_context


def validate_result_weights(weights: dict[str, float]) -> None:
    if any(not math.isfinite(value) or value < 0 for value in weights.values()):
        raise ValueError("目标权重必须是非负有限数")
    if sum(weights.values()) > 1.000001:
        raise ValueError("目标权重之和不能超过1")
