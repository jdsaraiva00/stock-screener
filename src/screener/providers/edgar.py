"""SEC EDGAR: filed fundamentals (XBRL company facts) and filer details.

API reference: https://www.sec.gov/search-filings/edgar-application-programming-interfaces
Each figure carries the date its filing reached the SEC, which is what makes
point-in-time analysis possible. XBRL coverage starts around 2009-2011.

The full JSON for each company is kept gzipped under data/raw/edgar so that the
tag mapping can change without downloading anything again.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Iterable

from screener.providers.base import DataProvider, Fact, FilerInfo, ProviderError
from screener.providers.http import ThrottledClient

FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
# Filings that carry financial statements.
REPORT_FORMS = {"10-K", "10-K/A", "10-Q", "10-Q/A", "10-KT", "10-QT", "20-F", "20-F/A", "40-F", "40-F/A"}


def parse_company_facts(doc: dict) -> Iterable[Fact]:
    for taxonomy, tags in doc.get("facts", {}).items():
        for tag, body in tags.items():
            for unit, entries in body.get("units", {}).items():
                for e in entries:
                    # A figure with no value, period end, filing date or accession
                    # cannot be placed in time, so it is skipped rather than guessed.
                    if e.get("val") is None or not e.get("end") or not e.get("filed") or not e.get("accn"):
                        continue
                    yield Fact(
                        taxonomy=taxonomy, tag=tag, unit=unit,
                        period_start=e.get("start") or "", period_end=e["end"],
                        value=float(e["val"]), fy=e.get("fy"), fp=e.get("fp"),
                        form=e.get("form"), filed=e["filed"], accession=e["accn"],
                        frame=e.get("frame"),
                    )


def parse_submissions(doc: dict) -> FilerInfo:
    recent = doc.get("filings", {}).get("recent", {})
    latest_date = latest_accn = None
    for form, date, accn in zip(recent.get("form", []), recent.get("filingDate", []),
                                recent.get("accessionNumber", [])):
        if form in REPORT_FORMS and (latest_date is None or date > latest_date):
            latest_date, latest_accn = date, accn
    return FilerInfo(
        cik=int(doc["cik"]), name=doc.get("name") or None,
        sic=doc.get("sic") or None, sic_description=doc.get("sicDescription") or None,
        fiscal_year_end=doc.get("fiscalYearEnd") or None,
        latest_report_filed=latest_date, latest_report_accession=latest_accn,
    )


class EdgarProvider(DataProvider):
    name = "edgar"

    def __init__(self, cfg):
        self.http = ThrottledClient(cfg.edgar_rps, cfg.require_edgar_user_agent())
        self.raw_dir: Path = cfg.raw_dir / "edgar"

    def raw_path(self, cik: int) -> Path:
        return self.raw_dir / f"CIK{cik:010d}.json.gz"

    def filer_info(self, cik: int) -> FilerInfo:
        return parse_submissions(self.http.get(SUBMISSIONS_URL.format(cik=cik)).json())

    def fundamentals(self, cik: int, offline: bool = False) -> Iterable[Fact]:
        path = self.raw_path(cik)
        if offline:
            if not path.exists():
                raise ProviderError(f"no raw EDGAR file cached for CIK {cik}")
            doc = json.loads(gzip.decompress(path.read_bytes()))
        else:
            content = self.http.get(FACTS_URL.format(cik=cik)).content
            doc = json.loads(content)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(gzip.compress(content, compresslevel=6))
            tmp.replace(path)
        return parse_company_facts(doc)


class EdgarOfflineProvider(EdgarProvider):
    """Reads only the raw files already on disk; needs no User-Agent."""

    def __init__(self, cfg):
        self.http = None
        self.raw_dir = cfg.raw_dir / "edgar"
