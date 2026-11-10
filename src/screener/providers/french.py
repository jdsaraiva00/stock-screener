"""Fama-French factors, momentum and the risk-free rate from the Ken French Data Library.

https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html
Values are stored in percent, as published. The library is updated with a lag
of one to two months.
"""

from __future__ import annotations

import calendar
import io
import re
import zipfile

from screener.providers.base import DataProvider, FactorSeries, ProviderError
from screener.providers.http import ThrottledClient

BASE = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
USER_AGENT = "personal-stock-screener/0.1 (local research tool)"
DATASETS = {
    ("ff3", "monthly"): "F-F_Research_Data_Factors_CSV.zip",
    ("ff3", "daily"): "F-F_Research_Data_Factors_daily_CSV.zip",
    ("ff5", "monthly"): "F-F_Research_Data_5_Factors_2x3_CSV.zip",
    ("ff5", "daily"): "F-F_Research_Data_5_Factors_2x3_daily_CSV.zip",
    ("mom", "monthly"): "F-F_Momentum_Factor_CSV.zip",
    ("mom", "daily"): "F-F_Momentum_Factor_daily_CSV.zip",
}
_DATA_LINE = re.compile(r"^\s*(\d{8}|\d{6})\s*,")


def parse_french_csv(text: str) -> list[tuple[str, str, float]]:
    """Rows (date, factor, percent) from the first data block of a library CSV.

    Files hold explanatory text, a header line starting with a comma, the
    monthly or daily block, then (monthly files) an annual block that is ignored.
    Monthly dates become the last calendar day of the month. The library marks
    missing values as -99.99 or -999; those are dropped, not stored.
    """
    rows: list[tuple[str, str, float]] = []
    header: list[str] | None = None
    previous = ""
    for line in text.splitlines():
        if _DATA_LINE.match(line):
            if header is None:
                if not previous.startswith(","):
                    raise ProviderError("French file: no header line above the data block")
                header = [h.strip() for h in previous.split(",")[1:]]
            cells = [c.strip() for c in line.split(",")]
            stamp = cells[0]
            if len(stamp) == 6:
                year, month = int(stamp[:4]), int(stamp[4:])
                date = f"{year:04d}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}"
            else:
                date = f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}"
            for factor, cell in zip(header, cells[1:], strict=True):
                value = float(cell)
                if value > -99:
                    rows.append((date, factor, value))
        elif header is not None:
            break
        previous = line.strip()
    if not rows:
        raise ProviderError("French file: no data rows found")
    return rows


class FrenchProvider(DataProvider):
    name = "french"

    def __init__(self, cfg):
        self.http = ThrottledClient(1, USER_AGENT)

    def factor_datasets(self) -> list[tuple[str, str]]:
        return list(DATASETS)

    def factor_returns(self, dataset: str, freq: str) -> FactorSeries:
        archive = zipfile.ZipFile(io.BytesIO(self.http.get(BASE + DATASETS[dataset, freq]).content))
        text = archive.read(archive.namelist()[0]).decode("latin-1")
        return FactorSeries(dataset, freq, parse_french_csv(text))
