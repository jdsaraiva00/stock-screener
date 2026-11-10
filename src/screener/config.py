"""Settings, read from a local config.toml. Nothing here is hard-coded to a machine."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_NAME = "config.toml"
DEFAULT_MAX_AGE_HOURS = {
    "universe": 24, "prices": 12, "profile": 24,
    "statements": 168, "fundamentals": 24, "factors": 168,
}
DEFAULT_SOURCES = {
    "universe": "wikipedia", "prices": "yfinance", "profile": "yfinance",
    "statements": "yfinance", "fundamentals": "edgar", "factors": "french",
}


class ConfigError(Exception):
    pass


@dataclass
class Config:
    root: Path
    edgar_user_agent: str = ""
    edgar_rps: float = 5.0
    universe: str = "sp500"
    price_start: str = "2000-01-01"
    benchmarks: list[str] = field(default_factory=lambda: ["SPY", "^SP500TR", "^GSPC"])
    data_dir_name: str = "data"
    sources: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_SOURCES))
    yahoo_rps: float = 2.0
    yahoo_price_batch: int = 50
    max_age_hours: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_MAX_AGE_HOURS))
    server_port: int = 0          # 0 = pick any free port

    @property
    def data_dir(self) -> Path:
        return self.root / self.data_dir_name

    @property
    def db_path(self) -> Path:
        return self.data_dir / "cache.sqlite"

    @property
    def user_db_path(self) -> Path:
        """Things you create in the app (saved screens). Kept apart from the cache,
        which can be deleted and rebuilt."""
        return self.data_dir / "user.sqlite"

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def log_dir(self) -> Path:
        return self.data_dir / "logs"

    def require_edgar_user_agent(self) -> str:
        ua = self.edgar_user_agent.strip()
        if not ua or "example.com" in ua.lower():
            raise ConfigError(
                "EDGAR needs a User-Agent with your contact details. "
                "Set [edgar] user_agent in config.toml, e.g. \"Jane Doe jane.doe@example.com\"."
            )
        return ua


def find_config(start: Path | None = None) -> Path:
    """SCREENER_CONFIG if set, otherwise config.toml in the working directory or a parent."""
    env = os.environ.get("SCREENER_CONFIG")
    if env:
        path = Path(env).expanduser()
        if not path.is_file():
            raise ConfigError(f"SCREENER_CONFIG points to a missing file: {path}")
        return path.resolve()
    here = (start or Path.cwd()).resolve()
    for folder in (here, *here.parents):
        candidate = folder / CONFIG_NAME
        if candidate.is_file():
            return candidate
    raise ConfigError(
        f"No {CONFIG_NAME} found in {here} or its parents. "
        "Copy config.example.toml to config.toml and fill it in."
    )


def load_config(path: Path | None = None) -> Config:
    path = path or find_config()
    with open(path, "rb") as fh:
        raw = tomllib.load(fh)
    cfg = Config(root=path.parent)
    edgar = raw.get("edgar", {})
    cfg.edgar_user_agent = str(edgar.get("user_agent", ""))
    cfg.edgar_rps = float(edgar.get("requests_per_second", cfg.edgar_rps))
    if not 0 < cfg.edgar_rps <= 10:
        raise ConfigError("[edgar] requests_per_second must be between 0 and 10 (the SEC limit).")
    cfg.universe = raw.get("universe", {}).get("name", cfg.universe)
    cfg.price_start = raw.get("history", {}).get("price_start", cfg.price_start)
    cfg.benchmarks = list(raw.get("benchmarks", {}).get("tickers", cfg.benchmarks))
    cfg.data_dir_name = raw.get("storage", {}).get("data_dir", cfg.data_dir_name)
    cfg.sources.update(raw.get("sources", {}))
    yahoo = raw.get("yahoo", {})
    cfg.yahoo_rps = float(yahoo.get("requests_per_second", cfg.yahoo_rps))
    cfg.yahoo_price_batch = int(yahoo.get("price_batch_size", cfg.yahoo_price_batch))
    cfg.server_port = int(raw.get("server", {}).get("port", 0))
    cfg.max_age_hours.update(raw.get("refresh", {}).get("max_age_hours", {}))
    return cfg
