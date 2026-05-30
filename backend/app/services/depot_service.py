"""Depot-Logik: Screenshot-OCR, Quelltext-Import, Abgleich, Uebernahme, Kurs-Refresh, Summen."""
import html as html_lib
import json
import logging
import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.provider import get_llm_provider
from app.models.depot import DepotPosition, DepotSnapshot
from app.schemas.depot import ParsedPosition
from app.services import market_data

logger = logging.getLogger(__name__)

_OCR_SYSTEM = (
    "Du bist ein praeziser Extraktor fuer Wertpapierdepot-Screenshots (z.B. ING). "
    "Lies die Tabelle der Positionen exakt aus. Erfinde nichts. "
    "Zahlen im deutschen Format (1.234,56) gibst du als reine Dezimalzahl mit Punkt zurueck (1234.56)."
)

_OCR_PROMPT = (
    "Extrahiere alle Depot-Positionen aus diesem Screenshot. Gib ausschliesslich JSON in genau dieser Form zurueck:\n"
    '{"positions": [{"name": str, "isin": str|null, "wkn": str|null, '
    '"quantity": number|null, "last_price": number|null, "last_value": number|null, '
    '"day_change_pct": number|null, "total_change_pct": number|null, "currency": str|null}], '
    '"total_value": number|null}\n\n'
    "- name: Wertpapiername\n"
    "- isin: 12-stellige ISIN falls sichtbar, sonst null\n"
    "- wkn: 6-stellige WKN falls sichtbar, sonst null\n"
    "- quantity: Stueck/Anteile/Nominal\n"
    "- last_price: aktueller Kurs pro Stueck\n"
    "- last_value: aktueller Kurswert der Position (Stueck * Kurs)\n"
    "- day_change_pct: heutige Veraenderung in Prozent (Vorzeichen beachten), sonst null\n"
    "- total_change_pct: Gesamt-Performance in Prozent, sonst null\n"
    "- currency: Waehrung (z.B. EUR), sonst null\n"
    "- total_value: Gesamt-Depotwert falls als Summe sichtbar, sonst null\n"
    "Gib NUR das JSON aus, keinen weiteren Text."
)


def _norm_name(name: str | None) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().lower())


def _clean_security_name(name: str | None) -> str:
    """ING-Kurznamen fuer die Marktdaten-Suche bereinigen.

    Entfernt Nominalwert-Suffixe wie 'DL-,01', 'EO 1', 'HD-00001', 'YC 1'
    sowie Aktiengattungs-Kuerzel, die die Yahoo-Suche stoeren.
    """
    if not name:
        return ""
    n = name.strip()
    # Nominalwert-/Waehrungs-Suffixe am Ende (DL=Dollar, EO=Euro, HD, YC, SF, NK, LS, ...)
    n = re.sub(r"\b(?:DL|EO|HD|YC|SF|NK|LS|DM|CHF|GBP)[-.,/ 0-9]*$", "", n, flags=re.IGNORECASE)
    n = re.sub(r"\s+", " ", n).strip(" .,-")
    return n


def _clean_security_name_aggressive(name: str | None) -> str:
    """Staerkere Bereinigung fuer den Namens-Fallback: entfernt Rechtsform- und
    Gattungs-Kuerzel sowie Satzzeichen, damit die Yahoo-Suche eher trifft."""
    n = _clean_security_name(name)
    n = re.sub(r"\b(?:INC|CORP|PLC|LTD|CO|SP\.?ADS|REGS|CL\.?[A-C]|N\.?V|S\.?A|AG|SE|REIT|ADR)\b",
               " ", n, flags=re.IGNORECASE)
    n = re.sub(r"[.\-/]", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n


def _to_data_url(image: str) -> str:
    image = image.strip()
    if image.startswith("data:"):
        return image
    return f"data:image/png;base64,{image}"


async def parse_screenshot(image: str, model: str | None = None) -> dict:
    """Ruft das Vision-LLM und gibt {positions: [ParsedPosition], total_value, model} zurueck."""
    provider = get_llm_provider()
    used_model = model or provider.default_model
    messages = [
        {"role": "system", "content": _OCR_SYSTEM},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": _OCR_PROMPT},
                {"type": "image_url", "image_url": {"url": _to_data_url(image)}},
            ],
        },
    ]
    result = await provider.chat(
        messages=messages,
        model=used_model,
        temperature=0.0,
        max_tokens=4000,
        response_format={"type": "json_object"},
    )
    content = result.get("content") or "{}"
    # Robust gegen ```json ... ``` Wrapper
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```[a-zA-Z]*", "", content).rstrip("`").strip()
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        logger.warning("Depot-OCR lieferte kein valides JSON")
        data = {"positions": []}

    positions: list[ParsedPosition] = []
    for raw in data.get("positions", []):
        try:
            positions.append(ParsedPosition(**raw))
        except Exception as e:
            logger.debug(f"Position uebersprungen: {e}")
    return {
        "positions": positions,
        "total_value": data.get("total_value"),
        "model": used_model,
    }


def _de_num(s: str | None) -> float | None:
    """Deutsche Zahl '1.234,56' / '+148,30' / '-41,98' -> float."""
    if not s:
        return None
    s = s.strip().replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def parse_ing_depot_html(html_src: str) -> list[ParsedPosition]:
    """Parst den Seitenquelltext der ING-Depotuebersicht.

    Extrahiert je Position deterministisch: Name, ISIN, Stueck, Einstandskurs,
    aktueller Kurs, Kurswert, Gesamt-Performance %. Robust gegen die feste
    ibbr-table-Struktur des Direkt-Depots.
    """
    positions: list[ParsedPosition] = []
    # Auf echte Positions-Zeilen splitten (Kategorie-/Summenzeilen haben andere Klassen)
    blocks = re.split(r'<div role="row" class="ibbr-table-row"\s+data-toggle-state', html_src)
    for blk in blocks[1:]:
        m_isin = re.search(r'isin=([A-Z]{2}[A-Z0-9]{9}[0-9])', blk)
        if not m_isin:
            continue
        isin = m_isin.group(1)

        m_name = re.search(r"<strong>([^<]+)</strong>", blk)
        name = re.sub(r"\s+", " ", html_lib.unescape(m_name.group(1))).strip() if m_name else isin

        m_qty = re.search(r'ibbr-table-cell--quantity[^>]*>\s*<span>([\d.,]+)</span>', blk)
        # Einstandskurs = erste reine valuta-Zelle
        m_avg = re.search(r'ibbr-table-cell valuta-aligned gs-span-20">\s*<span>([\d.,]+)</span>', blk)
        # Aktueller Kurs = bold-sm-Zelle
        m_price = re.search(r'ibbr-table-cell--bold-sm[^>]*>\s*<span>([\d.,]+)</span>', blk)
        # Kurswert = brokerage + market-value
        m_val = re.search(
            r'ibbr-table-cell--brokerage ibbr-table-cell--market-value[^>]*>\s*<span>([\d.,]+)</span>', blk
        )
        # Gesamt-Performance % (seit Kauf)
        m_pct = re.search(
            r'u-text-(?:positive|negative)-value[^>]*>\s*<strong>\s*<span>([+\-]?[\d.,]+)</span>', blk
        )

        positions.append(ParsedPosition(
            name=name,
            isin=isin,
            quantity=_de_num(m_qty.group(1)) if m_qty else None,
            avg_buy_price=_de_num(m_avg.group(1)) if m_avg else None,
            last_price=_de_num(m_price.group(1)) if m_price else None,
            last_value=_de_num(m_val.group(1)) if m_val else None,
            total_change_pct=_de_num(m_pct.group(1)) if m_pct else None,
            currency="EUR",
        ))
    return positions


def _match(parsed: ParsedPosition, existing: list[DepotPosition]) -> DepotPosition | None:
    if parsed.isin:
        for p in existing:
            if p.isin and p.isin.upper() == parsed.isin.upper():
                return p
    if parsed.wkn:
        for p in existing:
            if p.wkn and p.wkn.upper() == parsed.wkn.upper():
                return p
    pname = _norm_name(parsed.name)
    if pname:
        for p in existing:
            if _norm_name(p.name) == pname:
                return p
    return None


async def build_preview(db: AsyncSession, positions: list[ParsedPosition]) -> list[dict]:
    existing = (await db.execute(
        select(DepotPosition).where(DepotPosition.is_active == True)  # noqa: E712
    )).scalars().all()
    items = []
    for parsed in positions:
        m = _match(parsed, existing)
        if m is None:
            status = "new"
        elif (
            m.quantity is not None and parsed.quantity is not None
            and float(m.quantity) == float(parsed.quantity)
            and parsed.last_price is not None and m.last_price is not None
            and float(m.last_price) == float(parsed.last_price)
        ):
            status = "unchanged"
        else:
            status = "update"
        items.append({
            "parsed": parsed,
            "match_id": m.id if m else None,
            "match_name": m.name if m else None,
            "status": status,
        })
    return items


async def apply_positions(
    db: AsyncSession, positions: list[ParsedPosition], replace_missing: bool = False
) -> dict:
    existing = (await db.execute(select(DepotPosition))).scalars().all()
    active = [p for p in existing if p.is_active]
    seen_ids: set = set()
    created = updated = 0

    for parsed in positions:
        if not parsed.name and not parsed.isin:
            continue
        m = _match(parsed, active)
        value = parsed.last_value
        if value is None and parsed.quantity is not None and parsed.last_price is not None:
            value = float(parsed.quantity) * float(parsed.last_price)
        if m is None:
            m = DepotPosition(name=parsed.name or parsed.isin or "Unbenannt", source="screenshot")
            db.add(m)
            created += 1
        else:
            updated += 1
        m.name = parsed.name or m.name
        m.isin = parsed.isin or m.isin
        m.wkn = parsed.wkn or m.wkn
        if parsed.quantity is not None:
            m.quantity = parsed.quantity
        if parsed.avg_buy_price is not None:
            m.avg_buy_price = parsed.avg_buy_price
        if parsed.currency:
            m.currency = parsed.currency
        if parsed.last_price is not None:
            m.last_price = parsed.last_price
        if value is not None:
            m.last_value = value
        if parsed.day_change_pct is not None:
            m.day_change_pct = parsed.day_change_pct
        if parsed.total_change_pct is not None:
            m.total_change_pct = parsed.total_change_pct
        m.last_price_at = datetime.now(timezone.utc)
        m.price_stale = False
        m.is_active = True
        m.source = "screenshot"
        await db.flush()
        seen_ids.add(m.id)

    if replace_missing:
        for p in active:
            if p.id not in seen_ids:
                p.is_active = False

    await db.flush()
    await _create_snapshot(db, source="screenshot")
    return {"created": created, "updated": updated}


async def refresh_prices(db: AsyncSession) -> dict:
    positions = (await db.execute(
        select(DepotPosition).where(DepotPosition.is_active == True)  # noqa: E712
    )).scalars().all()
    refreshed = stale = 0
    fx_cache: dict[str, float | None] = {}
    async with market_data.new_client() as client:
        for p in positions:
            quote = None
            # 1. Primaer ueber ISIN (gecachtes Symbol bevorzugt)
            if p.isin:
                quote = await market_data.get_price_by_isin(client, p.isin, p.market_symbol)
            # 2. Fallback ueber bereinigten Namen, wenn ISIN keinen Kurs liefert
            if (not quote or not quote.get("price")) and not p.market_symbol:
                for nm in (_clean_security_name(p.name), _clean_security_name_aggressive(p.name)):
                    if not nm:
                        continue
                    sym = await market_data.resolve_symbol(client, nm)
                    if sym:
                        quote = await market_data.fetch_quote(client, sym)
                        if quote and quote.get("price"):
                            break
            if not quote or not quote.get("price"):
                p.price_stale = True
                stale += 1
                continue

            price = quote["price"]
            cur = (quote.get("currency") or p.currency or "EUR").upper()
            target = (p.currency or "EUR").upper()
            # Fremdwaehrung -> EUR umrechnen (statt zu verwerfen)
            if cur != target:
                if cur not in fx_cache:
                    fx_cache[cur] = await market_data.fetch_fx_rate(client, quote.get("currency") or cur)
                rate = fx_cache[cur]
                if not rate:
                    logger.info(f"Kein FX-Kurs {cur}->EUR fuer {p.isin}, Position bleibt veraltet")
                    p.price_stale = True
                    stale += 1
                    continue
                price = price * rate

            p.last_price = price
            p.market_symbol = quote.get("symbol") or p.market_symbol
            if p.quantity is not None:
                p.last_value = float(p.quantity) * price
            if quote.get("day_change_pct") is not None:
                p.day_change_pct = quote["day_change_pct"]
            p.last_price_at = datetime.now(timezone.utc)
            p.price_stale = False
            refreshed += 1
    await db.flush()
    if refreshed:
        await _create_snapshot(db, source="market")
    return {"refreshed": refreshed, "stale": stale}


def _range_for_days(days: int) -> str:
    for limit, label in [(7, "1mo"), (30, "1mo"), (90, "3mo"), (180, "6mo"), (365, "1y"), (730, "2y")]:
        if days <= limit:
            return label
    return "5y"


async def backfill_history(db: AsyncSession, days: int = 90) -> dict:
    """Rekonstruiert den Depotwert-Verlauf aus historischen Yahoo-Kursen.

    Naeherung: nutzt die AKTUELLEN Stueckzahlen (vergangene Kaeufe/Verkaeufe
    sind nicht erfasst). FX-Umrechnung mit historischem Tageskurs. Legt nur
    Snapshots fuer Tage an, die noch keinen Snapshot haben (heute ausgenommen).
    """
    import bisect

    positions = (await db.execute(
        select(DepotPosition).where(DepotPosition.is_active == True)  # noqa: E712
    )).scalars().all()
    range_ = _range_for_days(days)

    existing_days = set()
    for snap in (await db.execute(select(DepotSnapshot))).scalars().all():
        if snap.captured_at:
            existing_days.add(snap.captured_at.date().isoformat())

    series: dict = {}   # pid -> (sorted_dates, {date: eur_price}, quantity)
    all_dates: set[str] = set()
    fx_hist: dict[str, dict] = {}

    async with market_data.new_client() as client:
        for p in positions:
            if p.quantity is None:
                continue
            sym = p.market_symbol
            if not sym and p.isin:
                sym = await market_data.resolve_symbol(client, p.isin)
            if not sym:
                for nm in (_clean_security_name(p.name), _clean_security_name_aggressive(p.name)):
                    if nm:
                        sym = await market_data.resolve_symbol(client, nm)
                        if sym:
                            break
            if not sym:
                continue
            hist = await market_data.fetch_history(client, sym, range_)
            if not hist or not hist["closes"]:
                continue
            cur = (hist.get("currency") or p.currency or "EUR").upper()
            target = (p.currency or "EUR").upper()
            fxh = None
            if cur != target:
                if cur not in fx_hist:
                    base = "GBP" if (cur in ("GBP", "GBX") or hist.get("currency") == "GBp") else cur
                    fxd = await market_data.fetch_history(client, f"{base}EUR=X", range_)
                    fx_hist[cur] = fxd or {"closes": {}}
                fxh = fx_hist[cur]["closes"]
                pence = cur in ("GBP", "GBX") or hist.get("currency") == "GBp"

            eur_prices: dict[str, float] = {}
            fx_dates = sorted(fxh.keys()) if fxh is not None else []
            for d, close in hist["closes"].items():
                if fxh is None:
                    eur_prices[d] = close
                else:
                    rate = fxh.get(d)
                    if rate is None and fx_dates:
                        idx = bisect.bisect_right(fx_dates, d) - 1
                        rate = fxh[fx_dates[idx]] if idx >= 0 else None
                    if rate is None:
                        continue
                    eur_prices[d] = close * (rate / 100 if pence else rate)
            if eur_prices:
                sd = sorted(eur_prices.keys())
                series[p.id] = (sd, eur_prices, float(p.quantity))
                all_dates.update(sd)

    # Pro Tag aufsummieren (forward-fill je Position; Tag nur wenn alle Positionen Daten haben)
    inserted = 0
    today_iso = datetime.now(timezone.utc).date().isoformat()
    for d in sorted(all_dates):
        if d == today_iso or d in existing_days:
            continue
        total = 0.0
        complete = True
        for sd, pmap, qty in series.values():
            idx = bisect.bisect_right(sd, d) - 1
            if idx < 0:
                complete = False
                break
            total += pmap[sd[idx]] * qty
        if not complete:
            continue
        db.add(DepotSnapshot(
            captured_at=datetime.fromisoformat(f"{d}T18:00:00+00:00"),
            total_value=round(total, 2),
            currency="EUR",
            source="history",
        ))
        existing_days.add(d)
        inserted += 1

    await db.flush()
    return {"inserted": inserted, "positions": len(series)}


async def _create_snapshot(db: AsyncSession, source: str) -> None:
    totals = await compute_totals(db)
    positions = (await db.execute(
        select(DepotPosition).where(DepotPosition.is_active == True)  # noqa: E712
    )).scalars().all()
    snap = DepotSnapshot(
        captured_at=datetime.now(timezone.utc),
        total_value=totals["total_value"],
        total_cost=totals["total_cost"],
        currency=totals["currency"],
        source=source,
        positions_json=[
            {
                "name": p.name, "isin": p.isin, "quantity": float(p.quantity) if p.quantity is not None else None,
                "last_price": float(p.last_price) if p.last_price is not None else None,
                "last_value": float(p.last_value) if p.last_value is not None else None,
            }
            for p in positions
        ],
    )
    db.add(snap)
    await db.flush()


async def compute_totals(db: AsyncSession) -> dict:
    positions = (await db.execute(
        select(DepotPosition).where(DepotPosition.is_active == True)  # noqa: E712
    )).scalars().all()
    total_value = 0.0
    total_cost = 0.0
    day_change_value = 0.0
    has_cost = False
    has_stale = False
    last_update = None
    currency = "EUR"
    for p in positions:
        if p.last_value is not None:
            total_value += float(p.last_value)
        if p.avg_buy_price is not None and p.quantity is not None:
            total_cost += float(p.avg_buy_price) * float(p.quantity)
            has_cost = True
        if p.last_value is not None and p.day_change_pct is not None:
            # Wert von heute -> gestriger Wert -> absolute Tagesveraenderung
            prev = float(p.last_value) / (1 + float(p.day_change_pct) / 100) if float(p.day_change_pct) != -100 else 0
            day_change_value += float(p.last_value) - prev
        if p.price_stale:
            has_stale = True
        if p.last_price_at and (last_update is None or p.last_price_at > last_update):
            last_update = p.last_price_at
        if p.currency:
            currency = p.currency
    total_gain = (total_value - total_cost) if has_cost else None
    total_gain_pct = (total_gain / total_cost * 100) if (has_cost and total_cost) else None
    return {
        "total_value": round(total_value, 2),
        "total_cost": round(total_cost, 2) if has_cost else None,
        "total_gain": round(total_gain, 2) if total_gain is not None else None,
        "total_gain_pct": round(total_gain_pct, 2) if total_gain_pct is not None else None,
        "day_change_value": round(day_change_value, 2),
        "position_count": len(positions),
        "currency": currency,
        "last_update": last_update,
        "has_stale_prices": has_stale,
    }
