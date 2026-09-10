import json
import shutil
from dataclasses import asdict
from pathlib import Path

from lowfreq.application import QuantPlatform
from lowfreq.config import Settings

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "github-pages"
PERIODS = ("1m", "3m", "6m", "1y", "all")
MARKETS = ("cn", "pink")


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def build() -> None:
    settings = Settings()
    platform = QuantPlatform(settings)
    data_dir = OUTPUT / "demo-data"
    data_dir.mkdir(parents=True, exist_ok=True)

    for market in MARKETS:
        source = platform.backtest_data_source(market)
        symbols = (
            [item.strip() for item in settings.pink_symbols.split(",")]
            if market == "pink"
            else [item.strip() for item in settings.market_symbols.split(",")]
        )
        for period in PERIODS:
            result = asdict(platform.run_backtest("simple_trend", symbols, period, market))
            result.update(
                {
                    "period": period,
                    "market": market,
                    "currency": "USD" if market == "pink" else "CNY",
                    "start_date": result["equity_curve"][0]["date"],
                    "end_date": result["equity_curve"][-1]["date"],
                    "data_source": source.name,
                    "baseline_value": settings.initial_cash,
                    "instrument_names": source.instrument_names(
                        [symbol for symbol in result["series"] if symbol != "portfolio"]
                    ),
                    "instrument_sources": source.instrument_sources(
                        [symbol for symbol in result["series"] if symbol != "portfolio"]
                    ),
                }
            )
            write_json(data_dir / f"{market}-{period}.json", result)

    write_json(
        data_dir / "strategies.json",
        [asdict(strategy.metadata) for strategy in platform.registry.list()],
    )
    shutil.copy2(ROOT / "static" / "app.js", OUTPUT / "app.js")
    shutil.copy2(ROOT / "static" / "styles.css", OUTPUT / "styles.css")
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    html = html.replace('/static/styles.css?v=20260909-1', './styles.css?v=20260909-2')
    html = html.replace(
        '<script src="/static/app.js?v=20260909-1"></script>',
        '<script>window.LOWFREQ_STATIC_DEMO = true;</script>\n'
        '  <script src="./app.js?v=20260909-2"></script>',
    )
    (OUTPUT / "index.html").write_text(html, encoding="utf-8")
    (OUTPUT / ".nojekyll").write_text("", encoding="ascii")


if __name__ == "__main__":
    build()
