"""Parse simple relative intervals like '30d', '2w' into a cutoff datetime."""
import re
from datetime import datetime, timedelta, timezone

_UNITS = {"d": 1, "w": 7}


def parse_since(text: str | None, now: datetime | None = None) -> datetime | None:
    if not text:
        return None
    now = now or datetime.now(timezone.utc)
    m = re.fullmatch(r"(\d+)\s*([dw])", text.strip().lower())
    if not m:
        raise ValueError(f"Bad interval: {text!r}. Use e.g. '30d' or '2w'.")
    return now - timedelta(days=int(m.group(1)) * _UNITS[m.group(2)])
