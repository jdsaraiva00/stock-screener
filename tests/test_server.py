"""The API over a small synthetic cache: it must serve what is stored, keep
missing values as null, and never need the network."""

import json
import warnings

import pytest

from screener import db
from screener.analysis import compute, engine

from test_engine import _universe

warnings.filterwarnings("ignore", category=DeprecationWarning)
from fastapi.testclient import TestClient  # noqa: E402

from screener.server import create_app  # noqa: E402


@pytest.fixture
def client(cfg, conn):
    members, history, px = _universe()
    snap = engine.cross_section(members, history, px, px.adj.index[-1])
    compute.store(conn, history, snap, {1: {"period_end": "2023-06-30", "available": "2023-08-15",
                                            "derived": {}, "tags": {"revenue": "Revenues"}}})
    conn.execute("INSERT INTO analysis_meta VALUES('as_of', ?)", (px.adj.index[-1],))
    conn.execute("INSERT INTO refresh_log VALUES('prices','BAD','2026-01-01T00:00:00Z',NULL,'error','no data',NULL)")
    conn.commit()
    return TestClient(create_app(cfg))


def test_meta_reports_freshness_failures_and_the_catalog(client):
    meta = client.get("/api/meta").json()
    assert meta["universe"] == "sp500" and meta["as_of"]
    assert {f["step"] for f in meta["freshness"]} >= {"prices", "fundamentals", "factors"}
    assert meta["failures"] == [{"step": "prices", "key": "BAD", "last_attempt": "2026-01-01T00:00:00Z",
                                 "last_success": None, "error": "no data"}]
    keys = {m["key"] for m in meta["catalog"]["measures"]}
    assert {"f_score", "altman_z", "beneish_m", "mom_12_1", "quality", "composite"} <= keys
    cited = [m for m in meta["catalog"]["measures"] if m["key"] == "f_score"][0]
    assert "Piotroski" in cited["citation"] and cited["about"]


def test_screen_is_columnar_and_missing_values_are_null(client):
    body = client.get("/api/screen").json()
    cols = body["columns"]
    assert len(body["data"]) == 12 and {"ticker", "sector", "f_score", "f_score__pct", "f_score__spct"} <= set(cols)
    row = dict(zip(cols, body["data"][0]))                       # T0, a financial
    assert row["ticker"] == "T0" and row["financial"] in (1, True)
    assert row["altman_z"] is None and row["beneish_m"] is None  # not applicable: null, not zero
    assert "NaN" not in json.dumps(body)


def test_stock_detail_and_unknown_ticker(client):
    detail = client.get("/api/stock/t2").json()
    assert detail["row"]["ticker"] == "T2" and len(detail["history"]) == 1
    assert detail["peers"]["columns"][:2] == ["ticker", "name"] and len(detail["peers"]["data"]) == 5
    assert detail["profile"] is None and detail["insights"] is not None
    assert client.get("/api/stock/NOPE").status_code == 404


def test_saved_screens_round_trip(client):
    assert client.get("/api/screens").json() == []
    definition = {"filters": [{"key": "f_score", "op": ">=", "a": "8"}], "weights": {"quality": 2}}
    assert client.put("/api/screens/Strong%20balance%20sheets", json=definition).status_code == 200
    saved = client.get("/api/screens").json()
    assert saved[0]["name"] == "Strong balance sheets" and saved[0]["definition"] == definition
    assert client.put("/api/screens/%20", json={}).status_code == 422
    assert client.delete("/api/screens/Strong%20balance%20sheets").status_code == 200
    assert client.delete("/api/screens/Strong%20balance%20sheets").status_code == 404


def test_empty_cache_gives_a_clear_error(cfg):
    response = TestClient(create_app(cfg)).get("/api/screen")
    assert response.status_code == 503 and "refresh" in response.json()["detail"]
