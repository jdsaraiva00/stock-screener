"""Provider registry. To add a source: write a DataProvider subclass, register it
here, and name it under [sources] in config.toml."""

from __future__ import annotations

from screener.providers.base import DataProvider, ProviderError


def _registry() -> dict[str, type[DataProvider]]:
    from screener.providers.edgar import EdgarProvider
    from screener.providers.french import FrenchProvider
    from screener.providers.wikipedia import WikipediaProvider
    from screener.providers.yahoo import YahooProvider

    return {p.name: p for p in (WikipediaProvider, YahooProvider, EdgarProvider, FrenchProvider)}


def get_provider(cfg, role: str) -> DataProvider:
    """The provider configured for a role (universe, prices, profile, statements,
    fundamentals, factors)."""
    name = cfg.sources.get(role)
    registry = _registry()
    if name not in registry:
        raise ProviderError(f"[sources] {role} = {name!r} is not a known provider ({sorted(registry)})")
    return registry[name](cfg)
