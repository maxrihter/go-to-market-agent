"""Source-URL sanity helpers, shared by model validators and assembly.

LLMs sometimes fabricate citations as placeholder hosts (example.com, localhost).
These helpers reject such URLs at two layers: Pydantic validators on the citation
models (so a model refuses a fake URL), and a post-hoc filter in assembly that strips
any that slip through. Kept deliberately in both places: the validator surfaces the
problem during structured output, the filter quietly drops it so one bad citation does
not abort a report.
"""

from __future__ import annotations

# Hosts that are almost certainly not real citations: RFC 2606 placeholders plus
# loopback / internal hosts a public report should never cite.
_FAKE_URL_HOSTS: frozenset[str] = frozenset(
    {
        "example.com",
        "example.org",
        "example.net",
        "localhost",
        "127.0.0.1",
        "0.0.0.0",
        "test.com",
        "test.org",
        "domain.com",
        "url.com",
        "website.com",
        "site.com",
        "placeholder.com",
    }
)


def is_fake_source_url(url: str) -> bool:
    """True if `url` uses a placeholder / hallucinated host.

    Matches the exact host, host with port, and subdomains, with or without a trailing
    slash. Empty / whitespace-only input also counts as fake.
    """
    if not url or not url.strip():
        return True
    url_lower = url.lower().strip()
    for fake in _FAKE_URL_HOSTS:
        if (
            f"//{fake}/" in url_lower
            or f"//{fake}:" in url_lower
            or url_lower.rstrip("/").endswith(f"//{fake}")
        ):
            return True
        if f".{fake}/" in url_lower or f".{fake}:" in url_lower or url_lower.endswith(f".{fake}"):
            return True
    return False


def fake_url_hosts() -> frozenset[str]:
    """Expose the blocklist for tests and diagnostics (immutable)."""
    return _FAKE_URL_HOSTS
