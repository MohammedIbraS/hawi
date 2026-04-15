"""
Arabic text normalization.

Without this, the same word written with/without diacritics,
different alef forms, or teh marbuta variations will NOT match
in retrieval — silently destroying recall quality.
"""
import re
import unicodedata


# Arabic Unicode ranges
_ARABIC_DIACRITICS = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670]")
_TATWEEL = re.compile(r"\u0640")  # kashida / tatweel

# Alef normalization: all alef variants → plain alef ا
_ALEF_VARIANTS = re.compile(r"[آأإٱ]")

# Teh marbuta ة → heh ه (common variant in names)
_TEH_MARBUTA = re.compile(r"ة")

# Waw with hamza above ؤ → waw و
_WAW_HAMZA = re.compile(r"ؤ")

# Yeh with hamza above ئ → yeh ي
_YEH_HAMZA = re.compile(r"ئ")

# Alef maqsura ى → yeh ي
_ALEF_MAQSURA = re.compile(r"ى")

# Hamza on its own
_HAMZA = re.compile(r"[ءأإآ]")

# Extra whitespace
_WHITESPACE = re.compile(r"\s+")


def normalize_arabic(text: str, *, aggressive: bool = False) -> str:
    """
    Normalize Arabic text for consistent retrieval.

    Args:
        text: Raw Arabic (or mixed Arabic/English) text.
        aggressive: If True, apply additional normalizations (teh marbuta,
                    alef maqsura) that improve recall but may lose distinctions.
                    Use aggressive=True for embedding/retrieval.
                    Use aggressive=False for display text.

    Returns:
        Normalized text.
    """
    if not text:
        return text

    # Unicode NFC normalization first
    text = unicodedata.normalize("NFC", text)

    # Remove diacritics (tashkeel)
    text = _ARABIC_DIACRITICS.sub("", text)

    # Remove tatweel (kashida stretching)
    text = _TATWEEL.sub("", text)

    # Normalize alef variants to plain alef
    text = _ALEF_VARIANTS.sub("ا", text)

    if aggressive:
        # Normalize teh marbuta to heh
        text = _TEH_MARBUTA.sub("ه", text)
        # Normalize alef maqsura to yeh
        text = _ALEF_MAQSURA.sub("ي", text)
        # Normalize waw with hamza
        text = _WAW_HAMZA.sub("و", text)
        # Normalize yeh with hamza
        text = _YEH_HAMZA.sub("ي", text)

    # Collapse multiple spaces
    text = _WHITESPACE.sub(" ", text).strip()

    return text


def normalize_for_embedding(text: str) -> str:
    """Normalize text before embedding. Uses aggressive normalization."""
    return normalize_arabic(text, aggressive=True)


def normalize_for_display(text: str) -> str:
    """Normalize text for storage/display. Preserves teh marbuta etc."""
    return normalize_arabic(text, aggressive=False)


def is_arabic(text: str, threshold: float = 0.3) -> bool:
    """Return True if at least `threshold` fraction of chars are Arabic."""
    if not text:
        return False
    arabic_chars = sum(1 for c in text if "\u0600" <= c <= "\u06FF")
    return arabic_chars / len(text) >= threshold


def detect_language(text: str) -> str:
    """Detect primary language of text. Returns 'ar', 'en', or 'mixed'."""
    if not text:
        return "unknown"
    arabic_chars = sum(1 for c in text if "\u0600" <= c <= "\u06FF")
    latin_chars = sum(1 for c in text if c.isalpha() and ord(c) < 128)
    total = arabic_chars + latin_chars
    if total == 0:
        return "unknown"
    ar_ratio = arabic_chars / total
    if ar_ratio >= 0.8:
        return "ar"
    if ar_ratio <= 0.2:
        return "en"
    return "mixed"
