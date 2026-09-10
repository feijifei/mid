from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LOWFREQ_", env_file=".env")

    app_name: str = "低频量化研究与模拟交易平台"
    database_url: str = "sqlite:///data/platform.db"
    plugin_dir: Path = Path("strategy_plugins")
    data_source: str = "eastmoney"
    csv_data_path: Path = Path("data/market.csv")
    market_cache_path: Path = Path("data/cache/eastmoney_etf.csv")
    pink_cache_path: Path = Path("data/cache/pink_us_daily.csv")
    market_symbols: str = "600519,000333,600887,600900,601088,600941,601857,601398,600036,601318"
    market_start_date: str = "20240101"
    pink_symbols: str = "TCEHY,RHHBY,NSRGY,VWAGY,BYDDY,SFTBY,NTDOY,BASFY,DTEGY,BACHY"
    initial_cash: float = 1_000_000.0
    commission_rate: float = 0.0003
    min_commission: float = 5.0
    slippage_bps: float = 2.0
    max_symbol_weight: float = 0.40
    lot_size: int = 100


settings = Settings()
