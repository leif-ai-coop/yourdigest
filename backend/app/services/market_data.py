"""Marktdaten via Yahoo Finance (kostenlos, kein API-Key).

ISIN -> Symbol ueber den Search-Endpoint, Kurs ueber den v8-Chart-Endpoint
(funktioniert ohne crumb/cookie, im Gegensatz zum v7-quote-Endpoint).
"""
import logging

import httpx

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://query1.finance.yahoo.com/v1/finance/search"
_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


async def resolve_symbol(client: httpx.AsyncClient, isin: str) -> str | None:
    """ISIN (oder Suchbegriff) -> Yahoo-Symbol. None wenn kein Treffer."""
    if not isin:
        return None
    try:
        resp = await client.get(
            _SEARCH_URL, params={"q": isin, "quotesCount": 5, "newsCount": 0}
        )
        resp.raise_for_status()
        quotes = resp.json().get("quotes", [])
        if not quotes:
            return None
        # Bevorzuge eine Notierung in EUR/Deutschland, sonst erstes Ergebnis.
        for q in quotes:
            sym = q.get("symbol", "")
            if sym.endswith((".DE", ".F", ".SG", ".MU", ".BE", ".DU", ".HM", ".HA")):
                return sym
        return quotes[0].get("symbol")
    except Exception as e:
        logger.warning(f"Yahoo symbol-resolve fehlgeschlagen fuer {isin}: {e}")
        return None


async def fetch_quote(client: httpx.AsyncClient, symbol: str) -> dict | None:
    """Aktueller Kurs + Tagesveraenderung fuer ein Symbol."""
    if not symbol:
        return None
    try:
        resp = await client.get(_CHART_URL.format(symbol=symbol), params={"interval": "1d", "range": "5d"})
        resp.raise_for_status()
        result = resp.json().get("chart", {}).get("result")
        if not result:
            return None
        r0 = result[0]
        meta = r0.get("meta", {})
        price = meta.get("regularMarketPrice")
        if price is None:
            return None
        # Vortagsschluss aus der Tages-Schlusskursreihe (zweitletzter Schluss).
        # Yahoos meta.chartPreviousClose ist unzuverlaessig (oft nicht der letzte
        # Handelstag) -> falsche Tagesveraenderung. Die Reihe ist verlaesslich.
        closes = [c for c in ((r0.get("indicators", {}).get("quote") or [{}])[0].get("close") or []) if c is not None]
        prev = closes[-2] if len(closes) >= 2 else (meta.get("chartPreviousClose") or meta.get("previousClose"))
        day_change_pct = None
        if prev:
            try:
                day_change_pct = round((price - prev) / prev * 100, 4)
            except ZeroDivisionError:
                day_change_pct = None
        return {
            "price": float(price),
            "currency": meta.get("currency"),
            "day_change_pct": day_change_pct,
            "symbol": meta.get("symbol", symbol),
        }
    except Exception as e:
        logger.warning(f"Yahoo quote fehlgeschlagen fuer {symbol}: {e}")
        return None


async def get_price_by_isin(client: httpx.AsyncClient, isin: str, cached_symbol: str | None = None) -> dict | None:
    """Komplettpfad: (gecachtes) Symbol -> Kurs. Gibt None bei Misserfolg."""
    symbol = cached_symbol or await resolve_symbol(client, isin)
    if not symbol:
        return None
    quote = await fetch_quote(client, symbol)
    if quote:
        quote["symbol"] = quote.get("symbol") or symbol
    return quote


async def fetch_history(client: httpx.AsyncClient, symbol: str, range_: str = "3mo") -> dict | None:
    """Taegliche Schlusskurse fuer ein Symbol. Liefert {'currency', 'closes': {date_iso: close}}."""
    if not symbol:
        return None
    try:
        resp = await client.get(_CHART_URL.format(symbol=symbol), params={"interval": "1d", "range": range_})
        resp.raise_for_status()
        result = resp.json().get("chart", {}).get("result")
        if not result:
            return None
        r0 = result[0]
        ts = r0.get("timestamp") or []
        quote = (r0.get("indicators", {}).get("quote") or [{}])[0]
        closes = quote.get("close") or []
        out: dict[str, float] = {}
        from datetime import datetime as _dt, timezone as _tz
        for t, c in zip(ts, closes):
            if c is None:
                continue
            d = _dt.fromtimestamp(t, tz=_tz.utc).date().isoformat()
            out[d] = float(c)
        return {"currency": r0.get("meta", {}).get("currency"), "closes": out}
    except Exception as e:
        logger.warning(f"Yahoo history fehlgeschlagen fuer {symbol}: {e}")
        return None


async def fetch_fx_rate(client: httpx.AsyncClient, currency: str) -> float | None:
    """Wechselkurs: wie viele EUR ist 1 Einheit von `currency` wert.

    Behandelt GBp/GBX (Pence) als GBP/100. EUR -> 1.0.
    """
    cur = (currency or "").upper()
    if cur in ("EUR", ""):
        return 1.0
    pence = cur in ("GBP", "GBX", "GBPENCE") or currency == "GBp"
    base = "GBP" if pence else cur
    quote = await fetch_quote(client, f"{base}EUR=X")
    if not quote or not quote.get("price"):
        return None
    rate = quote["price"]
    return rate / 100 if pence else rate


def new_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=15, headers=_HEADERS, follow_redirects=True)
