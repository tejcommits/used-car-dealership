"""Small parsing helpers shared by the source modules."""
import re

# makes whose name is two words, so we can split "Maruti Suzuki Swift VXi" correctly
TWO_WORD_MAKES = [
    "Maruti Suzuki", "Land Rover", "Aston Martin", "Rolls Royce",
    "Mercedes Benz", "Mercedes-Benz",
]


def to_int(text):
    """Pull a rupee amount or count out of messy text.

    Handles '24 Lakh', '36.99L', '1.2 Crore', '45,000', '45k km'.
    """
    if text is None:
        return None
    t = str(text).lower().replace(",", "").strip()
    m = re.search(r"([\d.]+)\s*(crore|cr)\b", t)
    if m:
        return int(float(m.group(1)) * 10000000)
    m = re.search(r"([\d.]+)\s*(lakh|lac|l)\b", t)
    if m:
        return int(float(m.group(1)) * 100000)
    m = re.search(r"([\d.]+)\s*k\b", t)
    if m:
        return int(float(m.group(1)) * 1000)
    digits = re.sub(r"[^\d]", "", t)
    return int(digits) if digits else None


def year_from(text):
    if not text:
        return None
    m = re.search(r"(19|20)\d{2}", str(text))
    return int(m.group(0)) if m else None


def split_name(title):
    """Split '2018 Maruti Suzuki Swift VXi' into (make, model, variant)."""
    t = re.sub(r"^\s*(19|20)\d{2}\s+", "", str(title)).strip()
    for tw in TWO_WORD_MAKES:
        if t.lower().startswith(tw.lower()):
            rest = t[len(tw):].strip().split(" ", 1)
            return tw, (rest[0] if rest and rest[0] else None), (rest[1] if len(rest) > 1 else None)
    parts = t.split(" ")
    make = parts[0] if parts else None
    model = parts[1] if len(parts) > 1 else None
    variant = " ".join(parts[2:]) if len(parts) > 2 else None
    return make, model, variant
