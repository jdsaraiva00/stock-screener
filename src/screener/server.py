"""The local web app: a JSON API over the cache, plus the built frontend.

Every endpoint reads from SQLite only. Nothing here calls a data source.
"""

from __future__ import annotations

import json
import logging
import math
import sqlite3
import threading
from pathlib import Path

import pandas as pd
from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from screener import db
from screener.analysis.backtest import BacktestConfig, Backtester, Factors
from screener.analysis.catalog import COMPONENTS, MEASURES, catalog_json
from screener.analysis.compute import load_history, load_members
from screener.analysis.prices import PriceData
from screener.config import Config

WEB_DIR = Path(__file__).parent / "web"
IDENTITY = ["ticker", "name", "sector", "sub_industry", "financial", "price", "price_date",
            "period_end", "available", "market_cap_source", "f_signals_known"]
USER_SCHEMA = """
CREATE TABLE IF NOT EXISTS saved_screens (
    name TEXT PRIMARY KEY, definition TEXT NOT NULL, updated_at TEXT NOT NULL);
"""


def _frame_json(df: pd.DataFrame) -> str:
    """Columnar JSON; NaN becomes null (a missing value stays missing)."""
    return df.to_json(orient="split", index=False, double_precision=8)


def _records(df: pd.DataFrame) -> list[dict]:
    return json.loads(df.to_json(orient="records", double_precision=8))


def _clean(value):
    """NaN and infinity become null all the way down (JSON has neither)."""
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if hasattr(value, "item"):
        return _clean(value.item())
    return value


def freshness(conn: sqlite3.Connection) -> list[dict]:
    rows = []
    for label, step, table, span in [
        ("Prices", "prices", "price_series_meta", "MAX(last_date)"),
        ("Company profiles", "profile", "company_profile", "NULL"),
        ("Filed fundamentals (SEC)", "fundamentals", "fundamentals_meta", "NULL"),
        ("Provider statements", "statements",
         "(SELECT ticker, MAX(fetched_at) fetched_at FROM statement_items GROUP BY ticker)", "NULL"),
        ("Factor returns", "factors", "factor_meta", "MAX(last_date)"),
    ]:
        r = conn.execute(f"SELECT COUNT(*) n, MIN(fetched_at) oldest, MAX(fetched_at) newest, {span} latest "
                         f"FROM {table}").fetchone()
        failing = conn.execute("SELECT COUNT(*) FROM refresh_log WHERE step=? AND status='error'",
                               (step,)).fetchone()[0]
        rows.append({"data": label, "step": step, "series": r["n"], "oldest_fetch": r["oldest"],
                     "newest_fetch": r["newest"], "data_through": r["latest"], "failing": failing})
    return rows


def default_refresh_job(cfg: Config) -> str:
    """Update the cache from the data sources, then recompute scores. Runs in a
    background thread of the app; the pages keep reading the cache meanwhile."""
    from screener.analysis import compute
    from screener.refresh import STEPS, Refresher

    cfg.log_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger("screener")
    if not any(isinstance(h, logging.FileHandler) for h in root.handlers):
        handler = logging.FileHandler(cfg.log_dir / "refresh.log")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S"))
        root.addHandler(handler)
        root.setLevel(logging.INFO)
    conn = db.connect(cfg.db_path)
    try:
        results = Refresher(cfg, conn).run(STEPS)
        compute.run(conn, cfg.universe)
    finally:
        conn.close()
    failed = sum(r.failed for r in results.values())
    updated = sum(r.ok for r in results.values())
    return f"{updated} series updated, {failed} failed"


def create_app(cfg: Config, refresh_job=default_refresh_job) -> FastAPI:
    app = FastAPI(title="Stock screener", docs_url="/api/docs", openapi_url="/api/openapi.json")
    refresh_state = {"running": False, "started_at": None, "finished_at": None, "result": None, "error": None}
    refresh_lock = threading.Lock()

    def run_refresh() -> None:
        try:
            refresh_state["result"] = refresh_job(cfg)
        except Exception as exc:  # shown to the user in the freshness panel
            refresh_state["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            refresh_state["finished_at"] = db.now_utc()
            refresh_state["running"] = False

    @app.post("/api/refresh")
    def start_refresh():
        with refresh_lock:
            if refresh_state["running"]:
                raise HTTPException(409, "A refresh is already running")
            refresh_state.update(running=True, started_at=db.now_utc(), finished_at=None, result=None, error=None)
        threading.Thread(target=run_refresh, daemon=True).start()
        return dict(refresh_state)

    @app.get("/api/refresh")
    def refresh_status():
        log_file = cfg.log_dir / "refresh.log"
        tail = []
        if log_file.exists():
            with open(log_file, "rb") as fh:
                fh.seek(0, 2)
                fh.seek(max(0, fh.tell() - 4000))
                tail = fh.read().decode("utf-8", "replace").splitlines()[-8:]
        return {**refresh_state, "log": tail}

    def cache() -> sqlite3.Connection:
        if not cfg.db_path.exists():
            raise HTTPException(503, "The cache is empty. Run `screener refresh` first.")
        return db.connect(cfg.db_path, read_only=True)

    def user() -> sqlite3.Connection:
        cfg.user_db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(cfg.user_db_path)
        conn.row_factory = sqlite3.Row
        conn.executescript(USER_SCHEMA)
        return conn

    def has_table(conn: sqlite3.Connection, name: str) -> bool:
        return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None

    def snapshot(conn: sqlite3.Connection) -> pd.DataFrame:
        if not has_table(conn, "snapshot"):
            raise HTTPException(503, "Scores have not been computed. Run `screener compute`.")
        return pd.read_sql_query("SELECT * FROM snapshot", conn)

    @app.get("/api/meta")
    def meta():
        conn = cache()
        info = dict(conn.execute("SELECT key, value FROM analysis_meta").fetchall()) if has_table(conn, "analysis_meta") else {}
        failures = [dict(r) for r in conn.execute(
            "SELECT step, key, last_attempt, last_success, error FROM refresh_log WHERE status='error' "
            "ORDER BY step, key LIMIT 200")]
        return {"universe": cfg.universe, "as_of": info.get("as_of"), "computed_at": info.get("computed_at"),
                "freshness": freshness(conn), "failures": failures, "catalog": catalog_json()}

    @app.get("/api/screen")
    def screen():
        snap = snapshot(cache())
        keys = [m.key for m in MEASURES]
        cols = [c for c in IDENTITY if c in snap]
        cols += [c for k in keys for c in (k, f"{k}__pct", f"{k}__spct") if c in snap]
        return Response(_frame_json(snap[cols]), media_type="application/json")

    @app.get("/api/stock/{ticker}")
    def stock(ticker: str):
        conn = cache()
        snap = snapshot(conn)
        ticker = ticker.upper().replace(".", "-")
        row = snap[snap["ticker"] == ticker]
        if row.empty:
            raise HTTPException(404, f"{ticker} is not in the {cfg.universe} universe")
        record = _records(row)[0]
        cik = record.get("cik")
        history = pd.read_sql_query("SELECT * FROM fundamental_history WHERE cik=? ORDER BY period_end",
                                    conn, params=(cik,))
        prices = pd.read_sql_query("SELECT date, close, adj_close, volume FROM prices_daily WHERE ticker=? "
                                   "ORDER BY date", conn, params=(ticker,))
        insight = conn.execute("SELECT items FROM insights WHERE ticker=?", (ticker,)).fetchone()
        source = conn.execute("SELECT detail FROM statement_sources WHERE cik=?", (cik,)).fetchone()
        profile = conn.execute("SELECT * FROM company_profile WHERE ticker=?", (ticker,)).fetchone()
        filer = conn.execute("SELECT * FROM filer_info WHERE cik=?", (cik,)).fetchone()
        price_meta = conn.execute("SELECT * FROM price_series_meta WHERE ticker=?", (ticker,)).fetchone()
        fund_meta = conn.execute("SELECT * FROM fundamentals_meta WHERE cik=?", (cik,)).fetchone()
        peers = snap[snap["sector"] == record.get("sector")]
        peer_cols = ["ticker", "name"] + [m.key for m in MEASURES if m.key in peers]
        return {
            "row": record,
            "profile": dict(profile) if profile else None,
            "filer": dict(filer) if filer else None,
            "fetched": {"prices": price_meta["fetched_at"] if price_meta else None,
                        "fundamentals": fund_meta["fetched_at"] if fund_meta else None,
                        "profile": profile["fetched_at"] if profile else None},
            "history": _records(history),
            "prices": json.loads(prices.to_json(orient="split", index=False)),
            "insights": json.loads(insight["items"]) if insight else [],
            "sources": json.loads(source["detail"]) if source else None,
            "peers": json.loads(_frame_json(peers[peer_cols])),
            "component_labels": {k: v[0] for k, v in COMPONENTS.items()},
        }

    engines: dict[str, Backtester] = {}

    def backtester() -> Backtester:
        """Built once per computed data set; it remembers each date's cross-section."""
        conn = cache()
        if not has_table(conn, "fundamental_history"):
            raise HTTPException(503, "Scores have not been computed. Run `screener compute`.")
        stamp = conn.execute("SELECT value FROM analysis_meta WHERE key='computed_at'").fetchone()
        key = stamp[0] if stamp else ""
        if key not in engines:
            engines.clear()
            engines[key] = Backtester(load_members(conn, cfg.universe), load_history(conn),
                                      PriceData.load(conn), Factors.load(conn))
        return engines[key]

    @app.post("/api/backtest")
    def backtest(config: dict = Body(...)):
        allowed = BacktestConfig.__dataclass_fields__
        try:
            settings = BacktestConfig(**{k: v for k, v in config.items() if k in allowed})
            result = backtester().run(settings)
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, str(exc)) from exc
        return Response(json.dumps(_clean(result)), media_type="application/json")

    @app.get("/api/screens")
    def list_screens():
        return [{"name": r["name"], "definition": json.loads(r["definition"]), "updated_at": r["updated_at"]}
                for r in user().execute("SELECT * FROM saved_screens ORDER BY name")]

    @app.put("/api/screens/{name}")
    def save_screen(name: str, definition: dict = Body(...)):
        name = name.strip()
        if not name or len(name) > 80:
            raise HTTPException(422, "A screen name must be 1 to 80 characters")
        conn = user()
        conn.execute("INSERT OR REPLACE INTO saved_screens VALUES(?,?,?)",
                     (name, json.dumps(definition), db.now_utc()))
        conn.commit()
        return {"name": name}

    @app.delete("/api/screens/{name}")
    def delete_screen(name: str):
        conn = user()
        gone = conn.execute("DELETE FROM saved_screens WHERE name=?", (name,)).rowcount
        conn.commit()
        if not gone:
            raise HTTPException(404, "No such saved screen")
        return {"deleted": name}

    if (WEB_DIR / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=WEB_DIR / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                raise HTTPException(404)
            target = WEB_DIR / path
            if path and target.is_file() and WEB_DIR in target.resolve().parents:
                return FileResponse(target)
            return FileResponse(WEB_DIR / "index.html")
    else:
        @app.get("/", include_in_schema=False)
        def not_built():
            return Response("The frontend has not been built. Run: npm --prefix frontend install && "
                            "npm --prefix frontend run build", media_type="text/plain")

    return app
