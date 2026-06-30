from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MarketplaceCapabilities:
    key: str
    name: str
    source_markers: tuple[str, ...]
    email_outreach: bool
    browser_outreach: bool
    platform_conversation: bool
    payment: str
    priority: int


CHANNELS = {
    "fl_ru": MarketplaceCapabilities(
        key="fl_ru",
        name="FL.ru",
        source_markers=("www.fl.ru", "fl.ru"),
        email_outreach=False,
        browser_outreach=True,
        platform_conversation=True,
        payment="platform_or_direct",
        priority=1,
    ),
    "freelance_ru": MarketplaceCapabilities(
        key="freelance_ru",
        name="Freelance.ru",
        source_markers=("freelance.ru", "freelance_ru"),
        email_outreach=True,
        browser_outreach=True,
        platform_conversation=True,
        payment="platform_or_direct",
        priority=2,
    ),
    "pchel": MarketplaceCapabilities(
        key="pchel",
        name="Pchel.net",
        source_markers=("pchel.net", "pchel"),
        email_outreach=True,
        browser_outreach=True,
        platform_conversation=False,
        payment="direct",
        priority=3,
    ),
    "weblancer": MarketplaceCapabilities(
        key="weblancer",
        name="Weblancer",
        source_markers=("weblancer.net", "weblancer"),
        email_outreach=True,
        browser_outreach=True,
        platform_conversation=True,
        payment="platform_or_direct",
        priority=4,
    ),
}


def channel_for_source(source: str) -> MarketplaceCapabilities | None:
    lowered = source.lower()
    return next(
        (
            channel
            for channel in CHANNELS.values()
            if any(marker in lowered for marker in channel.source_markers)
        ),
        None,
    )
