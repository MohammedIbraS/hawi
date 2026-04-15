"""
PDF parser for text-based PDFs.

Extracts text while preserving document structure (headings, sections, pages).
Tables within PDFs are extracted separately as structured data.
"""
import re
from pathlib import Path
from typing import Optional
import pdfplumber
from loguru import logger

from pipeline.ingestion.processors.chunker import ParsedDocument, Section


# Heading detection heuristics
_HEADING_PATTERNS = [
    re.compile(r"^[١٢٣٤٥٦٧٨٩\d]+[\.\-]\s+\S"),   # Arabic/Latin numbered headings
    re.compile(r"^(الفصل|القسم|المحور|Chapter|Section)\s", re.IGNORECASE),
    re.compile(r"^[A-Z\u0600-\u06FF][^.]{0,60}:?\s*$"),  # Short ALL-CAPS or Arabic
]


def _looks_like_heading(text: str, font_size: Optional[float], avg_font_size: float) -> bool:
    text = text.strip()
    if not text or len(text) > 120:
        return False
    if font_size and font_size > avg_font_size * 1.15:
        return True
    return any(p.match(text) for p in _HEADING_PATTERNS)


_TABLE_TITLE_RE = re.compile(
    r"(?:Table|جدول|شكل|Figure|Chart)\s*[\d\-]+|^\d+-\d+\b",
    re.IGNORECASE,
)

# A broader pattern to also capture "Table X-Y: Title text" full captions
_TABLE_CAPTION_RE = re.compile(
    r"^(?:Table|جدول|شكل|Figure|Chart)\s*[\d\-]+[:\s]",
    re.IGNORECASE,
)


def _looks_like_table_title(text: str) -> bool:
    """Short line that looks like a table number/title (e.g. 'Table 2-27', 'جدول 5')."""
    text = text.strip()
    return bool(_TABLE_TITLE_RE.search(text)) and len(text) < 150


_CHART_NOISE_TOKEN_RE = re.compile(r'^[\d\.\-]+$')

# Detect reversed ASCII words from vertical column headers in bilingual PDFs.
# pdfplumber reads vertical text bottom-to-top, reversing each word character-by-character.
# Pattern: starts with lowercase, ends with uppercase (e.g. "sisylaiD" → "Dialysis").
_REVERSED_ASCII_RE = re.compile(r'^[a-z][a-zA-Z]{3,}[A-Z]$')

# Table-of-contents page detection
# Pattern 1: bilingual chapter index "ةحفص Page | Chapter | لودج Table"
_TOC_BILINGUAL_RE = re.compile(r'ةحفص')
# Pattern 2: dense list of English table-name entries with year+table-number refs
_TOC_ENTRY_RE = re.compile(r'[A-Za-z].{5,}?(?:202\dG|201\dG)\s*\|\s*\d+-\d+')


def _is_chart_noise(text: str) -> bool:
    """
    Detect lines that are bar/pie chart axis labels extracted as individual
    digit characters, e.g. '5 7 .0 8 5 3 .2 8' or '9 9 . 6 9 8'.
    These come from infographic PDFs where pdfplumber picks up each glyph
    of a chart as a separate word.

    Heuristic: if >= 3 whitespace-separated tokens and >= 75 % of them are
    1-2 character strings made only of digits/dots/dashes, it's chart noise.
    """
    tokens = text.split()
    if len(tokens) < 3:
        return False
    noisy = sum(
        1 for t in tokens
        if len(t) <= 2 and _CHART_NOISE_TOKEN_RE.match(t)
    )
    return noisy / len(tokens) >= 0.75


def _is_toc_page(page_text: str) -> bool:
    """
    Return True if this page is a table-of-contents / chapter index page that
    should be skipped entirely (it lists table names + page numbers but has no
    actual data content).

    Two patterns:
    1. Bilingual chapter index: contains Arabic 'ةحفص' (page) alongside 'Page'
       and 'Table' — these are the chapter-level TOC sections in MOH yearbooks.
    2. Dense list of English table names each followed by a year + table ref
       (e.g. "Allied Health Personnel ... 2023G | 14-2") — yearbook master TOC.
    """
    if _TOC_BILINGUAL_RE.search(page_text) and 'Page' in page_text and 'Table' in page_text:
        return True
    if len(_TOC_ENTRY_RE.findall(page_text)) >= 4:
        return True
    return False


def _is_boilerplate(text: str) -> bool:
    """Filter out page numbers, headers/footers, and chart axis noise."""
    text = text.strip()
    if not text:
        return True
    if re.match(r"^\d+$", text):         # standalone page number
        return True
    if len(text) < 3:
        return True
    if _is_chart_noise(text):            # infographic axis label garbage
        return True
    if re.search(r"P\.O\.\s*Box\s+\d+", text):  # mailing address footer (e.g. GASTAT)
        return True
    return False


_DECIMAL_DOT_RE = re.compile(r"\d\.$")   # trailing dot after a digit → decimal, not sentence end


def _is_sentence_end(text: str) -> bool:
    """Return True if text ends with real sentence-ending punctuation.

    A trailing '.' after a digit is treated as a decimal point (e.g. '99.')
    not a sentence ending, so the next line fragment will be merged in.
    """
    if not text:
        return False
    if text.endswith(("!", "?", "؟")):
        return True
    if text.endswith("."):
        return not bool(_DECIMAL_DOT_RE.search(text))
    return False


def parse_pdf(file_path: Path) -> ParsedDocument:
    """
    Extract text from a text-based PDF, returning a ParsedDocument
    with sections and paragraphs for chunking.

    Tables are detected via pdfplumber's bounding-box table finder and
    converted to a readable text representation so their content is
    indexed properly (instead of being extracted as jumbled word fragments).
    """
    doc = ParsedDocument()
    current_section = Section(heading=None, paragraphs=[], page_number=1)

    try:
        with pdfplumber.open(file_path) as pdf:
            avg_font_size = _estimate_avg_font_size(pdf)

            for page_num, page in enumerate(pdf.pages, start=1):
                # Skip table-of-contents / chapter index pages entirely
                raw_page_text = page.extract_text() or ""
                if _is_toc_page(raw_page_text):
                    logger.debug(f"Skipping TOC page {page_num}")
                    continue

                # --- Extract tables first, collect their bounding boxes ---
                found_tables = page.find_tables()
                table_bboxes = [t.bbox for t in found_tables] if found_tables else []
                raw_tables = page.extract_tables() if found_tables else []
                table_paragraphs = []
                for table in raw_tables:
                    text = _table_to_text(table)
                    if text:
                        table_paragraphs.append(text)

                # --- Extract words outside table bounding boxes ---
                words = page.extract_words(
                    x_tolerance=3,
                    y_tolerance=3,
                    keep_blank_chars=False,
                    use_text_flow=True,
                    extra_attrs=["size"],
                )
                if table_bboxes:
                    words = [
                        w for w in words
                        if not any(
                            _word_in_bbox(w, bbox) for bbox in table_bboxes
                        )
                    ]
                lines = _group_words_into_lines(words)

                pending_table_title: Optional[str] = None

                for line_text, line_font_size in lines:
                    if _is_boilerplate(line_text):
                        continue
                    if _looks_like_heading(line_text, line_font_size, avg_font_size):
                        if pending_table_title:
                            # A chapter-label/footer heading (e.g. "Chapter 02") appearing
                            # between the table title and the table — it's a running footer
                            # on yearbook pages, not a real section break. Skip it so the
                            # table inherits pending_table_title as its section_heading.
                            pass
                        else:
                            if current_section.paragraphs:
                                doc.sections.append(current_section)
                            current_section = Section(
                                heading=line_text.strip(),
                                paragraphs=[],
                                page_number=page_num,
                                paragraph_pages=[],
                            )
                    elif _looks_like_table_title(line_text):
                        # Start a pending table title; keep current_section intact
                        # so caption/description lines that follow are still stored
                        # as content paragraphs (they're searchable text, not just a label).
                        pending_table_title = line_text.strip()
                    else:
                        line = line_text.strip()
                        # Line-continuation merging: if the previous paragraph didn't end
                        # with a sentence-ending punctuation, the current line is a
                        # visual wrap of the same sentence — merge it in rather than
                        # creating a new paragraph. This prevents pdfplumber line-breaks
                        # from producing orphaned sentence fragments as separate chunks.
                        # Guard: only merge if the existing paragraph is short enough
                        # that the result will still fit within chunk_size.
                        if (
                            current_section.paragraphs
                            and not _is_sentence_end(current_section.paragraphs[-1])
                            and len(current_section.paragraphs[-1]) < 450
                        ):
                            current_section.paragraphs[-1] += " " + line
                            # Don't append to paragraph_pages — page is already recorded
                        else:
                            current_section.paragraphs.append(line)
                            current_section.paragraph_pages.append(page_num)
                        # Only clear pending_table_title if the line is clearly substantial
                        # prose (> 200 chars) — short/medium caption lines between a table
                        # reference and the table itself should not reset it.
                        if pending_table_title and len(line_text.strip()) > 200:
                            pending_table_title = None

                # Append table text as paragraphs.
                # When a table title was detected immediately before the table,
                # start a new section using that title as the heading so that
                # chunks get section_heading="Table 2-27: Hospital Beds by Region"
                # instead of the generic chapter heading (e.g. "Chapter 02").
                for tp in table_paragraphs:
                    if pending_table_title:
                        if current_section.paragraphs:
                            doc.sections.append(current_section)
                        current_section = Section(
                            heading=pending_table_title,
                            paragraphs=[],
                            page_number=page_num,
                            paragraph_pages=[],
                        )
                        pending_table_title = None
                    current_section.paragraphs.append(tp)
                    current_section.paragraph_pages.append(page_num)

            if current_section.paragraphs or current_section.heading:
                doc.sections.append(current_section)

    except Exception as e:
        logger.error(f"Failed to parse PDF {file_path}: {e}")
        raise

    return doc


def _word_in_bbox(word: dict, bbox: tuple) -> bool:
    """Return True if a word's centre falls inside the bounding box."""
    x0, top, x1, bottom = bbox
    wx = (word["x0"] + word["x1"]) / 2
    wy = (word["top"] + word["bottom"]) / 2
    return x0 <= wx <= x1 and top <= wy <= bottom


def _un_reverse_word(word: str) -> str:
    """
    Un-reverse a single ASCII token extracted from a vertical column header.

    pdfplumber reads vertical text bottom-to-top, producing reversed words like
    'sisylaiD' (Dialysis), 'sretneC' (Centers), 'setebaiD' (Diabetes).
    A reversed English word starts with lowercase and ends with uppercase
    (because the original word started with a capital letter).

    Handles slash-separated compound tokens like '/lartneC' → '/Central'.
    """
    if "/" in word:
        return "/".join(_un_reverse_word(part) for part in word.split("/"))
    if _REVERSED_ASCII_RE.match(word):
        return word[::-1]
    return word


def _clean_cell(cell_text: str) -> str:
    """
    Clean a single table cell by removing chart axis label noise lines and
    fixing reversed ASCII words from vertical column headers.

    Unlike body-text filtering, table cells may contain standalone numbers
    (e.g., "40", "222") that are valid data values — so we only strip chart
    axis noise here, NOT the full _is_boilerplate() check (which would
    incorrectly remove numeric data).

    Bilingual yearbook tables have vertical (rotated) column headers where
    pdfplumber reads English text bottom-to-top, reversing each word.
    """
    lines = cell_text.split("\n")
    clean_lines = [
        ln for ln in lines
        if ln.strip() and not _is_chart_noise(ln.strip())
    ]
    result = " ".join(clean_lines).strip()
    # Un-reverse any vertical-header ASCII words (e.g. 'sisylaiD' → 'Dialysis')
    result = " ".join(_un_reverse_word(w) for w in result.split())
    return result


def _table_to_text(table: list[list]) -> str:
    """
    Convert a pdfplumber table (list of rows, each a list of cell strings)
    to a readable plain-text representation suitable for embedding.

    Example output:
        المنطقة | عدد المراكز | ...
        الرياض  | 45          | ...
    """
    if not table:
        return ""

    cleaned_rows = []
    for row in table:
        cells = [
            _clean_cell(str(cell)) if cell is not None else ""
            for cell in row
        ]
        # Skip rows that are completely empty after cleaning
        if any(c for c in cells):
            cleaned_rows.append(cells)

    if not cleaned_rows:
        return ""

    # Format as pipe-separated rows (markdown-style, readable and embeddable)
    lines = [" | ".join(row) for row in cleaned_rows]
    return "\n".join(lines)


def _estimate_avg_font_size(pdf) -> float:
    sizes = []
    for page in list(pdf.pages)[:5]:
        for word in page.extract_words(extra_attrs=["size"]):
            size = word.get("size")
            if size:
                sizes.append(size)
    return sum(sizes) / len(sizes) if sizes else 12.0


def is_scanned_pdf(file_path: Path) -> bool:
    """
    Return True if the PDF has no extractable text (i.e. it is a scanned image PDF).
    Checks the first 5 pages; if none yield text, it's likely scanned.
    """
    try:
        with pdfplumber.open(file_path) as pdf:
            for page in list(pdf.pages)[:5]:
                text = page.extract_text() or ""
                if len(text.strip()) > 50:
                    return False
        return True
    except Exception:
        return False


def parse_pdf_ocr(file_path: Path) -> ParsedDocument:
    """
    OCR fallback for scanned (image-only) PDFs.

    Uses pdf2image to render each page as a PIL image, then pytesseract
    to extract text with Arabic + English language support.
    The result is assembled into a ParsedDocument with one section per page.
    """
    try:
        from pdf2image import convert_from_path
        import pytesseract
    except ImportError as e:
        raise ImportError(
            "OCR dependencies not installed. "
            "Run: pip install pytesseract pdf2image"
        ) from e

    doc = ParsedDocument()
    logger.info(f"OCR: starting OCR for {file_path.name}")

    try:
        pages = convert_from_path(str(file_path), dpi=200)
    except Exception as e:
        logger.error(f"OCR: pdf2image failed for {file_path}: {e}")
        raise

    for page_num, img in enumerate(pages, start=1):
        # Run OCR with Arabic + English; tessdata must have both lang packs
        try:
            text = pytesseract.image_to_string(img, lang="ara+eng")
        except Exception as e:
            logger.warning(f"OCR: tesseract failed on page {page_num} of {file_path.name}: {e}")
            continue

        paragraphs = [
            line.strip()
            for line in text.splitlines()
            if len(line.strip()) > 30
        ]
        if paragraphs:
            doc.sections.append(Section(
                heading=f"Page {page_num}",
                paragraphs=paragraphs,
                page_number=page_num,
                paragraph_pages=[page_num] * len(paragraphs),
            ))

    logger.info(f"OCR: extracted {sum(len(s.paragraphs) for s in doc.sections)} paragraphs from {len(pages)} pages")
    return doc


def _group_words_into_lines(words: list[dict]) -> list[tuple[str, Optional[float]]]:
    """Group words into lines based on Y position proximity."""
    if not words:
        return []

    lines: list[tuple[str, Optional[float]]] = []
    current_line_words = [words[0]]

    for word in words[1:]:
        prev_y = current_line_words[-1]["top"]
        curr_y = word["top"]
        if abs(curr_y - prev_y) < 5:    # same line
            current_line_words.append(word)
        else:
            text = " ".join(w["text"] for w in current_line_words)
            size = current_line_words[0].get("size")
            lines.append((text, size))
            current_line_words = [word]

    if current_line_words:
        text = " ".join(w["text"] for w in current_line_words)
        size = current_line_words[0].get("size")
        lines.append((text, size))

    return lines
