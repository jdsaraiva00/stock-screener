"""HTTP GET with a rate limit and retries, shared by the web-based providers."""

from __future__ import annotations

import time

import httpx

from screener.providers.base import ProviderError

RETRY_STATUS = {429, 500, 502, 503, 504}


class Throttle:
    def __init__(self, per_second: float):
        self.interval = 1.0 / per_second
        self._last = 0.0

    def wait(self) -> None:
        delay = self._last + self.interval - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        self._last = time.monotonic()


class ThrottledClient:
    def __init__(self, per_second: float, user_agent: str, retries: int = 4,
                 backoff: float = 1.0, transport: httpx.BaseTransport | None = None):
        self.throttle = Throttle(per_second)
        self.retries = retries
        self.backoff = backoff
        self.client = httpx.Client(
            headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"},
            timeout=60, follow_redirects=True, transport=transport,
        )

    def get(self, url: str) -> httpx.Response:
        problem = ""
        for attempt in range(self.retries + 1):
            self.throttle.wait()
            try:
                resp = self.client.get(url)
            except httpx.TransportError as exc:
                problem = f"{type(exc).__name__}: {exc}"
            else:
                if resp.status_code == 200:
                    return resp
                problem = f"HTTP {resp.status_code}"
                if resp.status_code not in RETRY_STATUS:
                    break
                retry_after = resp.headers.get("Retry-After", "")
                if retry_after.isdigit():
                    time.sleep(min(int(retry_after), 120))
            if attempt < self.retries:
                time.sleep(self.backoff * 2 ** attempt)
        raise ProviderError(f"{problem} for {url}")
