import json
from pathlib import Path

import pytest

from screener import db
from screener.config import Config
from screener.providers.edgar import parse_company_facts
from screener.refresh import Refresher

FIXTURES = Path(__file__).parent / "fixtures"
APPLE_CIK = 320193


@pytest.fixture
def cfg(tmp_path):
    return Config(root=tmp_path)


@pytest.fixture
def conn(cfg):
    connection = db.connect(cfg.db_path)
    yield connection
    connection.close()


@pytest.fixture
def apple_doc():
    """Real SEC company-facts response for Apple, trimmed to a few tags and to
    filings from October 2024 on (plus 10-K revenue rows filed 2016-2019)."""
    return json.loads((FIXTURES / "aapl_companyfacts_trimmed.json").read_text())


@pytest.fixture
def apple(cfg, conn, apple_doc):
    Refresher(cfg, conn).store_facts(APPLE_CIK, parse_company_facts(apple_doc), "edgar")
    conn.commit()
    return conn
