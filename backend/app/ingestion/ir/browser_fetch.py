"""Browser-TLS-impersonating fetch — the primary fetcher for WAF-protected IR sites.

Several IR platforms (ISRG/UBER/FIG sit behind Cloudflare/Akamai-class bot mitigation) reset the
connection based on the *TLS/HTTP2 handshake fingerprint* (JA3), BEFORE any HTTP body or JS runs.
A plain httpx GET gets a RemoteProtocolError/ReadTimeout, and even a headless Chromium gets
ERR_HTTP2_PROTOCOL_ERROR — the block is below the browser layer, so rendering can't beat it.

curl_cffi speaks the exact TLS+HTTP2 fingerprint of a real Chrome, so the WAF lets it through. It's
also cheap (no browser spawn), so it's the *primary* fetch — `render.py` (headless Chromium) stays as
the fallback only for sites whose links are injected by JS after load.
"""

import logging

logger = logging.getLogger(__name__)

# Pin a recent Chrome fingerprint. curl_cffi ships the impersonation profiles; bump as Chrome ages.
_IMPERSONATE = "chrome124"


async def fetch_impersonated(
    url: str, timeout: float = 25.0
) -> tuple[bytes, str] | None:
    """Return (content_bytes, content_type) for `url` using Chrome-TLS impersonation, or None.

    Lazy-imports curl_cffi so a missing/incompatible build degrades gracefully (caller falls back to
    the headless render, then to "no transcript") rather than crashing the ingest.
    """
    try:
        from curl_cffi.requests import AsyncSession
    except Exception:
        logger.warning("[ir.browser] curl_cffi not installed — cannot impersonate-fetch %s", url)
        return None

    try:
        async with AsyncSession() as session:
            resp = await session.get(
                url, impersonate=_IMPERSONATE, timeout=timeout, allow_redirects=True
            )
            resp.raise_for_status()
            return resp.content, resp.headers.get("content-type", "")
    except Exception as e:
        logger.info("[ir.browser] impersonated fetch failed for %s: %s", url, str(e)[:120])
        return None
