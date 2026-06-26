"""SSRF guard for server-side fetches of user-supplied URLs.

Feed URLs, podcast audio URLs and connector test URLs are created by the
(single, authenticated) admin, but they are fetched server-side on a host that
also runs internal-only services (databases, the cloud-metadata range, other
containers). A feed pointing at http://169.254.169.254/ or an internal host —
directly or via an HTTP redirect — would let the fetcher reach those services.

`validate_public_url` resolves the host and rejects any address in a
private/loopback/link-local/reserved range. `safe_get` / `safe_stream` follow
redirects manually, re-validating every hop (httpx's own follow_redirects would
silently chase a 302 into the internal network).

Residual: DNS rebinding (TOCTOU between our resolve and httpx's) is not closed —
acceptable here because only the authenticated admin can register URLs.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from contextlib import asynccontextmanager
from urllib.parse import urljoin, urlparse

import httpx


class SsrfError(ValueError):
    """Raised when a URL resolves to a non-public address or is otherwise unsafe."""


def _ip_is_blocked(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


def validate_public_url(url: str) -> None:
    """Raise SsrfError unless `url` is http(s) and every resolved IP is public."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise SsrfError(f"Blocked URL scheme: {parsed.scheme or '(none)'!r}")
    host = parsed.hostname
    if not host:
        raise SsrfError("URL has no host")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise SsrfError(f"Cannot resolve host {host!r}: {exc}") from exc
    for info in infos:
        ip = info[4][0]
        if _ip_is_blocked(ip):
            raise SsrfError(f"Blocked internal address {ip} for host {host!r}")


async def _avalidate(url: str) -> None:
    # getaddrinfo blocks (DNS) — keep it off the event loop.
    await asyncio.to_thread(validate_public_url, url)


async def safe_get(
    client: httpx.AsyncClient, url: str, *, max_redirects: int = 20, **kwargs
) -> httpx.Response:
    """GET that validates the target and every redirect hop is a public host.

    max_redirects defaults to 20 (httpx's own default): podcast audio URLs chain
    through several tracking prefixes (Podtrac, Chartable, Megaphone, Podder, ...)
    and legitimately need 6+ hops — a lower cap breaks those downloads. The SSRF
    guarantee is per-hop validation, not the count, so a generous cap is safe.
    """
    current = url
    for _ in range(max_redirects + 1):
        await _avalidate(current)
        resp = await client.get(current, follow_redirects=False, **kwargs)
        if resp.is_redirect:
            location = resp.headers.get("location")
            if not location:
                return resp
            current = urljoin(current, location)
            continue
        return resp
    raise SsrfError(f"Too many redirects starting from {url!r}")


@asynccontextmanager
async def safe_stream(
    client: httpx.AsyncClient, method: str, url: str, *, max_redirects: int = 20, **kwargs
):
    """Streaming request that re-validates the target across redirects.

    Yields a streaming httpx.Response for the final (validated) public URL.
    """
    current = url
    for _ in range(max_redirects + 1):
        await _avalidate(current)
        request = client.build_request(method, current, **kwargs)
        resp = await client.send(request, stream=True, follow_redirects=False)
        if resp.is_redirect:
            location = resp.headers.get("location")
            await resp.aclose()
            if not location:
                raise SsrfError(f"Redirect without Location from {current!r}")
            current = urljoin(current, location)
            continue
        try:
            yield resp
        finally:
            await resp.aclose()
        return
    raise SsrfError(f"Too many redirects starting from {url!r}")
