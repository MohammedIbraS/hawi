"""
Hierarchical document chunker.

Strategy:
  - Respect document structure (headings → sections → paragraphs)
  - Store parent (section) and child (paragraph) chunks
  - Child chunks are what get embedded; parent is fetched for LLM context
  - Tag chunks with metadata (has_statistics, language, section heading)
"""
import re
from dataclasses import dataclass, field
from typing import Optional
from .arabic_normalizer import normalize_for_embedding, detect_language


_STAT_PATTERNS = re.compile(
    r"\d[\d,،.٪%]*\s*(?:%|٪|percent|مليون|billion|trillion|ألف|thousand|مليار)"
    r"|\b\d{4}\b"   # years
    r"|\bQ[1-4]\b"  # quarters
    r"|نسبة|معدل|إجمالي|عدد|rate|ratio|total|count",
    re.IGNORECASE,
)


@dataclass
class Chunk:
    content: str
    content_normalized: str
    chunk_index: int
    language: str
    section_heading: Optional[str] = None
    page_number: Optional[int] = None
    has_statistics: bool = False
    is_table_description: bool = False
    parent_index: Optional[int] = None   # index of parent section chunk


@dataclass
class ParsedDocument:
    """Intermediate structure from parsers, before chunking."""
    sections: list["Section"] = field(default_factory=list)


@dataclass
class Section:
    heading: Optional[str]
    paragraphs: list[str]
    page_number: Optional[int] = None
    # Per-paragraph page numbers — lets tables on page N+1 get page_number=N+1
    # even when the section heading is on page N.
    paragraph_pages: list[Optional[int]] = field(default_factory=list)


def _is_table_content(text: str) -> bool:
    """Return True if text looks like a pipe-delimited table — must not be split."""
    lines = text.strip().splitlines()
    if len(lines) < 2:
        return False
    pipe_lines = sum(1 for line in lines if "|" in line)
    return pipe_lines / len(lines) >= 0.5


class HierarchicalChunker:
    def __init__(self, chunk_size: int = 512, overlap: int = 64):
        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunk_document(self, doc: ParsedDocument) -> list[Chunk]:
        chunks: list[Chunk] = []
        chunk_index = 0

        for section in doc.sections:
            # Build per-paragraph pages list, falling back to section page
            para_pages: list[Optional[int]] = (
                section.paragraph_pages
                if len(section.paragraph_pages) == len(section.paragraphs)
                else [section.page_number] * len(section.paragraphs)
            )

            # Create a parent chunk for the full section (for context retrieval)
            section_text = "\n\n".join(section.paragraphs)
            if not section_text.strip():
                continue

            # Skip creating a parent when the section has only one paragraph —
            # the child IS the content; a duplicate parent just bloats the index.
            paragraphs = [p.strip() for p in section.paragraphs if p.strip() and len(p.strip()) >= 80]
            if not paragraphs:
                continue

            if len(paragraphs) > 1:
                parent_index = chunk_index
                parent_chunk = self._make_chunk(
                    content=section_text,
                    index=chunk_index,
                    heading=section.heading,
                    page=section.page_number,
                    parent_index=None,
                )
                chunks.append(parent_chunk)
                chunk_index += 1
            else:
                # Single-paragraph section: no separate parent chunk.
                # Use -1 as a sentinel so the retrieval filter (gte=-1) still includes
                # these child chunks. parent_index=None is reserved for parent chunks only.
                parent_index = -1

            # Create child chunks from paragraphs
            for para, para_page in zip(section.paragraphs, para_pages):
                para = para.strip()
                if not para or len(para) < 80:
                    continue

                # If paragraph fits in chunk_size, keep as one chunk
                if len(para) <= self.chunk_size:
                    child = self._make_chunk(
                        content=para,
                        index=chunk_index,
                        heading=section.heading,
                        page=para_page,
                        parent_index=parent_index,
                    )
                    chunks.append(child)
                    chunk_index += 1
                elif _is_table_content(para):
                    # Tables must not be split mid-row — keep whole even if large
                    child = self._make_chunk(
                        content=para,
                        index=chunk_index,
                        heading=section.heading,
                        page=para_page,
                        parent_index=parent_index,
                        is_table=True,
                    )
                    chunks.append(child)
                    chunk_index += 1
                else:
                    # Split long prose paragraphs at sentence boundaries
                    for sub_chunk in self._split_long_text(para):
                        child = self._make_chunk(
                            content=sub_chunk,
                            index=chunk_index,
                            heading=section.heading,
                            page=para_page,
                            parent_index=parent_index,
                        )
                        chunks.append(child)
                        chunk_index += 1

        return chunks

    def _make_chunk(
        self,
        content: str,
        index: int,
        heading: Optional[str],
        page: Optional[int],
        parent_index: Optional[int],
        is_table: bool = False,
    ) -> Chunk:
        normalized = normalize_for_embedding(content)
        lang = detect_language(content)
        has_stats = bool(_STAT_PATTERNS.search(content))
        return Chunk(
            content=content,
            content_normalized=normalized,
            chunk_index=index,
            language=lang,
            section_heading=heading,
            page_number=page,
            has_statistics=has_stats,
            parent_index=parent_index,
            is_table_description=is_table,
        )

    def _split_long_text(self, text: str) -> list[str]:
        """Split long text at sentence boundaries with overlap."""
        # Split on Arabic and Latin sentence endings
        sentences = re.split(r"(?<=[.!?؟।])\s+", text)
        chunks = []
        current = ""

        for sentence in sentences:
            if len(current) + len(sentence) <= self.chunk_size:
                current = (current + " " + sentence).strip()
            else:
                if current:
                    chunks.append(current)
                # Start new chunk with overlap from end of previous.
                # Advance to the nearest word boundary so the overlap never starts mid-word.
                if len(current) > self.overlap:
                    overlap_start = len(current) - self.overlap
                    while overlap_start < len(current) and current[overlap_start] not in (" ", "\n"):
                        overlap_start += 1
                    overlap_text = current[overlap_start:].lstrip()
                else:
                    overlap_text = current
                current = (overlap_text + " " + sentence).strip()

        if current:
            chunks.append(current)

        return chunks
