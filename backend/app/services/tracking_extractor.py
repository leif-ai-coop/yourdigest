"""Tracking URL builder for carrier codes detected by LLM."""


def _build_tracking_url(carrier: str, code: str) -> str:
    """Build tracking URL based on carrier name."""
    c = carrier.lower()
    if "dhl" in c or "deutsche post" in c:
        return f"https://www.dhl.de/de/privatkunden/pakete-empfangen/verfolgen.html?piececode={code}"
    elif "ups" in c:
        return f"https://www.ups.com/track?tracknum={code}"
    elif "hermes" in c:
        return f"https://www.myhermes.de/empfangen/sendungsverfolgung/?s={code}"
    elif "dpd" in c:
        return f"https://tracking.dpd.de/status/de_DE/parcel/{code}"
    elif "gls" in c:
        return f"https://gls-group.com/DE/de/paketverfolgung?match={code}"
    elif "fedex" in c:
        return f"https://www.fedex.com/fedextrack/?trknbr={code}"
    elif "amazon" in c:
        return "https://www.amazon.de/gp/your-account/order-history"
    else:
        return f"https://t.17track.net/en#nums={code}"
