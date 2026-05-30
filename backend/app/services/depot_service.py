"""Depot-Logik: Screenshot-OCR, Abgleich, Uebernahme, Kurs-Refresh, Summen."""
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
    async with market_data.new_client() as client:
        for p in positions:
            # Primaer ueber ISIN, sonst Fallback ueber bereinigten Namen.
            query = p.isin or _clean_security_name(p.name)
            if not query:
                p.price_stale = True
                stale += 1
                continue
            quote = await market_data.get_price_by_isin(client, query, p.market_symbol)
            # Waehrungs-Guard: Kurs nur uebernehmen, wenn die Waehrung zur Position passt.
            # Verhindert, dass z.B. ein USD-Listing als EUR-Wert verbucht wird.
            if quote and quote.get("currency") and p.currency and quote["currency"].upper() != p.currency.upper():
                logger.info(
                    f"Kurs verworfen fuer {p.isin}: {quote['currency']} != {p.currency} (Symbol {quote.get('symbol')})"
                )
                # Gecachtes Symbol verwerfen, damit beim naechsten Lauf neu aufgeloest wird
                p.market_symbol = None
                p.price_stale = True
                stale += 1
                continue
            if quote and quote.get("price"):
                p.last_price = quote["price"]
                p.market_symbol = quote.get("symbol") or p.market_symbol
                if p.quantity is not None:
                    p.last_value = float(p.quantity) * quote["price"]
                if quote.get("day_change_pct") is not None:
                    p.day_change_pct = quote["day_change_pct"]
                p.last_price_at = datetime.now(timezone.utc)
                p.price_stale = False
                refreshed += 1
            else:
                p.price_stale = True
                stale += 1
    await db.flush()
    if refreshed:
        await _create_snapshot(db, source="market")
    return {"refreshed": refreshed, "stale": stale}


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
