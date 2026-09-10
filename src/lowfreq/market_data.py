import json
import time
from abc import ABC, abstractmethod
from datetime import date
from pathlib import Path
from urllib.request import urlopen

import numpy as np
import pandas as pd

REQUIRED_COLUMNS = ["date", "symbol", "open", "high", "low", "close", "volume"]


class MarketDataSource(ABC):
    name = "unknown"

    @abstractmethod
    def load(self, symbols: list[str] | None = None) -> pd.DataFrame:
        """Return validated daily bars ordered by date and symbol."""

    def instrument_names(self, symbols: list[str]) -> dict[str, str]:
        return {symbol: symbol for symbol in symbols}

    def instrument_sources(self, symbols: list[str]) -> dict[str, str]:
        return {symbol: self.name for symbol in symbols}


def validate_bars(bars: pd.DataFrame) -> pd.DataFrame:
    missing = set(REQUIRED_COLUMNS) - set(bars.columns)
    if missing:
        raise ValueError(f"行情缺少列: {sorted(missing)}")
    result = bars[REQUIRED_COLUMNS].copy()
    result["date"] = pd.to_datetime(result["date"]).dt.date
    numeric = ["open", "high", "low", "close", "volume"]
    result[numeric] = result[numeric].apply(pd.to_numeric, errors="raise")
    if result[["open", "high", "low", "close"]].le(0).any().any():
        raise ValueError("价格必须大于0")
    if result["volume"].lt(0).any():
        raise ValueError("成交量不能小于0")
    if result.duplicated(["date", "symbol"]).any():
        raise ValueError("行情存在重复的日期和证券")
    return result.sort_values(["date", "symbol"]).reset_index(drop=True)


class CsvMarketDataSource(MarketDataSource):
    name = "CSV本地行情"

    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self, symbols: list[str] | None = None) -> pd.DataFrame:
        bars = validate_bars(pd.read_csv(self._path))
        return bars if not symbols else bars[bars["symbol"].isin(symbols)].reset_index(drop=True)


class DemoMarketDataSource(MarketDataSource):
    name = "离线演示行情"
    SYMBOLS = ("510300", "510500", "518880", "511010")
    NAMES = {
        "510300": "沪深300ETF",
        "510500": "中证500ETF",
        "518880": "黄金ETF",
        "511010": "国债ETF",
    }

    def load(self, symbols: list[str] | None = None) -> pd.DataFrame:
        dates = pd.bdate_range(end="2026-08-31", periods=320)
        rows: list[dict[str, object]] = []
        for index, symbol in enumerate(self.SYMBOLS):
            t = np.arange(len(dates), dtype=float)
            trend = (0.00015 + index * 0.00004) * t
            cycle = 0.035 * np.sin(t / (14 + index * 5) + index)
            close = (3.2 + index * 0.7) * np.exp(trend + cycle)
            open_price = close * (1 + 0.0015 * np.sin(t / 3 + index))
            for day, open_value, close_value in zip(dates, open_price, close, strict=True):
                high = max(open_value, close_value) * 1.004
                low = min(open_value, close_value) * 0.996
                rows.append(
                    {
                        "date": day.date(),
                        "symbol": symbol,
                        "open": round(float(open_value), 4),
                        "high": round(float(high), 4),
                        "low": round(float(low), 4),
                        "close": round(float(close_value), 4),
                        "volume": 10_000_000 + index * 2_000_000,
                    }
                )
        bars = validate_bars(pd.DataFrame(rows))
        selected = list(symbols) if symbols else list(self.SYMBOLS)
        return bars[bars["symbol"].isin(selected)].reset_index(drop=True)

    def instrument_names(self, symbols: list[str]) -> dict[str, str]:
        return {symbol: self.NAMES.get(symbol, symbol) for symbol in symbols}


class EastmoneyEtfDataSource(MarketDataSource):
    """AkShare-based Eastmoney stock/ETF history with a daily local snapshot."""

    name = "东方财富优先 · 股票/ETF历史行情"
    DEFAULT_NAMES = {
        "510300": "沪深300ETF",
        "510500": "中证500ETF",
        "518880": "黄金ETF",
        "511010": "国债ETF",
        "600519": "贵州茅台",
        "000333": "美的集团",
        "600887": "伊利股份",
        "600900": "长江电力",
        "601088": "中国神华",
        "600941": "中国移动",
        "601857": "中国石油",
        "601398": "工商银行",
        "600036": "招商银行",
        "601318": "中国平安",
    }

    def __init__(self, cache_path: Path, default_symbols: list[str], start_date: str) -> None:
        self._cache_path = cache_path
        self._names_path = cache_path.with_suffix(".names.json")
        self._default_symbols = default_symbols
        self._start_date = start_date
        self._names = dict(self.DEFAULT_NAMES)
        if self._names_path.exists():
            try:
                self._names.update(json.loads(self._names_path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                pass

    def load(self, symbols: list[str] | None = None) -> pd.DataFrame:
        requested = symbols or self._default_symbols
        cached = self._load_cache(requested)
        if cached is not None:
            return cached
        existing = self._read_cache()
        available = set(existing["symbol"].unique()) if existing is not None else set()
        missing = [symbol for symbol in requested if symbol not in available]
        to_download = missing or requested
        try:
            downloaded = self._download(to_download)
        except Exception as exc:
            stale = self._load_cache(requested, allow_stale=True)
            if stale is not None:
                return stale
            raise RuntimeError(f"东方财富历史行情获取失败，且没有可用缓存: {exc}") from exc
        bars = downloaded if existing is None else validate_bars(
            pd.concat([existing, downloaded], ignore_index=True)
            .drop_duplicates(["date", "symbol"], keep="last")
        )
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        bars.to_csv(self._cache_path, index=False)
        self._names_path.write_text(
            json.dumps(self._names, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return bars[bars["symbol"].isin(requested)].reset_index(drop=True)

    def instrument_names(self, symbols: list[str]) -> dict[str, str]:
        return {symbol: self._names.get(symbol, symbol) for symbol in symbols}

    def _load_cache(self, requested: list[str], allow_stale: bool = False) -> pd.DataFrame | None:
        if not self._cache_path.exists():
            return None
        modified = date.fromtimestamp(self._cache_path.stat().st_mtime)
        if not allow_stale and modified != date.today():
            return None
        bars = self._read_cache()
        if bars is None:
            return None
        available = set(bars["symbol"].unique())
        if not set(requested).issubset(available):
            return None
        return bars[bars["symbol"].isin(requested)].reset_index(drop=True)

    def _read_cache(self) -> pd.DataFrame | None:
        if not self._cache_path.exists():
            return None
        return validate_bars(pd.read_csv(self._cache_path, dtype={"symbol": str}))

    def _download(self, requested: list[str]) -> pd.DataFrame:
        import akshare as ak

        frames: list[pd.DataFrame] = []
        end_date = date.today().strftime("%Y%m%d")
        columns = {
            "日期": "date",
            "开盘": "open",
            "最高": "high",
            "最低": "low",
            "收盘": "close",
            "成交量": "volume",
        }
        for symbol in requested:
            frame = self._download_symbol(ak, symbol, end_date)
            if frame.empty:
                raise ValueError(f"证券 {symbol} 没有可用历史行情")
            frame = frame.rename(columns=columns)
            frame["symbol"] = symbol
            frames.append(frame)
            self._names[symbol] = self._resolve_name(ak, symbol)
        return validate_bars(pd.concat(frames, ignore_index=True))

    def _download_symbol(self, ak, symbol: str, end_date: str) -> pd.DataFrame:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                if self._is_fund(symbol):
                    return ak.fund_etf_hist_em(
                        symbol=symbol,
                        period="daily",
                        start_date=self._start_date,
                        end_date=end_date,
                        adjust="",
                    )
                return ak.stock_zh_a_hist(
                    symbol=symbol,
                    period="daily",
                    start_date=self._start_date,
                    end_date=end_date,
                    adjust="",
                )
            except Exception as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(0.4 * (attempt + 1))
        assert last_error is not None
        prefixed = self._market_prefixed_symbol(symbol)
        try:
            if self._is_fund(symbol):
                fallback = ak.fund_etf_hist_sina(symbol=prefixed)
            else:
                fallback = ak.stock_zh_a_daily(
                    symbol=prefixed,
                    start_date=self._start_date,
                    end_date=end_date,
                    adjust="",
                )
            if "date" in fallback.columns:
                dates = pd.to_datetime(fallback["date"])
                fallback = fallback[
                    (dates >= pd.Timestamp(self._start_date))
                    & (dates <= pd.Timestamp(end_date))
                ]
            return fallback
        except Exception as fallback_error:
            raise RuntimeError(
                f"证券 {symbol} 的东方财富及备用历史行情均获取失败: {fallback_error}"
            ) from last_error

    @staticmethod
    def _is_fund(symbol: str) -> bool:
        return symbol.startswith(("1", "5"))

    def _resolve_name(self, ak, symbol: str) -> str:
        if symbol in self._names:
            return self._names[symbol]
        try:
            if self._is_fund(symbol):
                spot = ak.fund_etf_spot_em()
                match = spot[spot["代码"].astype(str).str.zfill(6) == symbol]
                return str(match.iloc[0]["名称"]) if not match.empty else symbol
            info = ak.stock_individual_info_em(symbol=symbol)
            names = info[info["item"] == "股票简称"]["value"]
            return str(names.iloc[0]) if not names.empty else symbol
        except Exception:
            try:
                quote_url = f"https://qt.gtimg.cn/q={self._market_prefixed_symbol(symbol)}"
                with urlopen(quote_url, timeout=5) as response:  # noqa: S310
                    fields = response.read().decode("gbk").split("~")
                return fields[1] if len(fields) > 1 and fields[1] else symbol
            except Exception:
                return symbol

    @staticmethod
    def _market_prefixed_symbol(symbol: str) -> str:
        return f"{'sh' if symbol.startswith(('5', '6')) else 'sz'}{symbol}"


class PinkMarketDataSource(MarketDataSource):
    """Daily OTC ADR data using Eastmoney first and Sina as a per-symbol fallback."""

    name = "东方财富优先 · 新浪备用 · OTC Pink日线"
    DEFAULT_NAMES = {
        "TCEHY": "腾讯控股ADR",
        "RHHBY": "罗氏控股ADR",
        "NSRGY": "雀巢ADR",
        "VWAGY": "大众汽车ADR",
        "BYDDY": "比亚迪ADR",
        "SFTBY": "软银集团ADR",
        "NTDOY": "任天堂ADR",
        "BASFY": "巴斯夫ADR",
        "DTEGY": "德国电信ADR",
        "BACHY": "中国银行ADR",
    }

    def __init__(self, cache_path: Path, default_symbols: list[str], start_date: str) -> None:
        self._cache_path = cache_path
        self._sources_path = cache_path.with_suffix(".sources.json")
        self._default_symbols = default_symbols
        self._start_date = start_date
        self._sources: dict[str, str] = {}
        if self._sources_path.exists():
            try:
                self._sources = json.loads(self._sources_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass

    def load(self, symbols: list[str] | None = None) -> pd.DataFrame:
        requested = [symbol.strip().upper() for symbol in (symbols or self._default_symbols)]
        if not requested or any(not symbol.replace("-", "").isalnum() for symbol in requested):
            raise ValueError("OTC代码只能包含字母、数字和连字符")
        existing = self._read_cache()
        available = set(existing["symbol"].unique()) if existing is not None else set()
        missing = [symbol for symbol in requested if symbol not in available]
        cache_is_fresh = (
            self._cache_path.exists()
            and date.fromtimestamp(self._cache_path.stat().st_mtime) == date.today()
            and self._sources_path.exists()
        )
        refresh_symbols = missing if cache_is_fresh else requested
        frames = []
        if existing is not None:
            frames.append(existing[~existing["symbol"].isin(refresh_symbols)])
        if refresh_symbols:
            import akshare as ak

            for symbol in refresh_symbols:
                frame, source_name = self._download_symbol(ak, symbol)
                frames.append(frame)
                self._sources[symbol] = source_name
        if not frames:
            raise ValueError("粉红股标的池为空")
        bars = validate_bars(
            pd.concat(frames, ignore_index=True).drop_duplicates(
                ["date", "symbol"], keep="last"
            )
        )
        bars = bars[pd.to_datetime(bars["date"]) <= pd.Timestamp(date.today())]
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        bars.to_csv(self._cache_path, index=False)
        self._sources_path.write_text(
            json.dumps(self._sources, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        selected = bars[bars["symbol"].isin(requested)].copy()
        available = set(selected["symbol"].unique())
        if not set(requested).issubset(available):
            missing_symbols = sorted(set(requested) - available)
            raise ValueError(f"粉红股行情缺少证券: {missing_symbols}")
        common_end = selected.groupby("symbol")["date"].max().min()
        return selected[selected["date"] <= common_end].reset_index(drop=True)

    def instrument_names(self, symbols: list[str]) -> dict[str, str]:
        return {symbol: self.DEFAULT_NAMES.get(symbol, symbol) for symbol in symbols}

    def instrument_sources(self, symbols: list[str]) -> dict[str, str]:
        return {symbol: self._sources.get(symbol, "缓存行情") for symbol in symbols}

    def _download_symbol(self, ak, symbol: str) -> tuple[pd.DataFrame, str]:
        columns = {
            "日期": "date",
            "开盘": "open",
            "最高": "high",
            "最低": "low",
            "收盘": "close",
            "成交量": "volume",
        }
        eastmoney_error: Exception | None = None
        for attempt in range(3):
            try:
                frame = ak.stock_us_hist(
                    symbol=f"153.{symbol}",
                    period="daily",
                    start_date=self._start_date,
                    end_date=date.today().strftime("%Y%m%d"),
                    adjust="",
                ).rename(columns=columns)
                if frame.empty:
                    raise ValueError("返回空行情")
                frame["symbol"] = symbol
                return validate_bars(frame), "东方财富美股历史"
            except Exception as exc:
                eastmoney_error = exc
                if attempt < 2:
                    time.sleep(0.4 * (attempt + 1))

        sina_error: Exception | None = None
        for attempt in range(3):
            try:
                frame = ak.stock_us_daily(symbol=symbol, adjust="")
                if frame.empty:
                    raise ValueError("返回空行情")
                frame = frame.copy()
                frame["symbol"] = symbol
                dates = pd.to_datetime(frame["date"])
                frame = frame[
                    (dates >= pd.Timestamp(self._start_date))
                    & (dates <= pd.Timestamp(date.today()))
                ]
                return validate_bars(frame), "新浪美股日线（备用）"
            except Exception as exc:
                sina_error = exc
                if attempt < 2:
                    time.sleep(0.4 * (attempt + 1))
        raise RuntimeError(
            f"OTC证券 {symbol} 两级行情均失败；"
            f"东方财富: {eastmoney_error}；新浪: {sina_error}"
        )

    def _read_cache(self) -> pd.DataFrame | None:
        if not self._cache_path.exists():
            return None
        return validate_bars(pd.read_csv(self._cache_path, dtype={"symbol": str}))
