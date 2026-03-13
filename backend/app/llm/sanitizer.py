import re


# Patterns that look like secrets/tokens
SECRET_PATTERNS = [
    re.compile(r'\b[A-Za-z0-9+/]{40,}={0,2}\b'),  # Base64-like
    re.compile(r'\b[0-9a-fA-F]{32,}\b'),  # Hex strings
    re.compile(r'(?:password|passwd|token|secret|api[_-]?key)\s*[:=]\s*\S+', re.IGNORECASE),
    re.compile(r'Bearer\s+\S+', re.IGNORECASE),
]


def sanitize_for_llm(text: str) -> str:
    """Remove potential secrets from text before sending to LLM."""
    if not text:
        return text

    result = text
    for pattern in SECRET_PATTERNS:
        result = pattern.sub("[REDACTED]", result)

    return result


def sanitize_email_for_llm(subject: str | None, body: str | None, from_addr: str | None) -> dict:
    """Sanitize email fields for LLM consumption."""
    return {
        "subject": subject or "",
        "body": sanitize_for_llm(body or "")[:4000],  # Limit body size
        "from": from_addr or "",
    }
