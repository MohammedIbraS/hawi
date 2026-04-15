"""
RAG service: assemble context and stream a grounded answer from Claude.
Saves user + assistant messages to DB after streaming when session_id is provided.
"""
import json
from typing import AsyncIterator, Optional
from uuid import UUID

import anthropic
from loguru import logger

from backend.config import get_settings
from backend.services.retrieval import RetrievalService, RetrievedChunk


SYSTEM_PROMPT = """You are a formal research assistant specialising in Saudi Arabian \
public health data. You provide accurate, well-sourced answers drawn exclusively from \
official open data published by Saudi health authorities, including the Ministry of Health \
(MOH), the General Authority for Statistics (GASTAT), SFDA, and others.

RULES:
1. Answer ONLY using the provided context. Never use your own training knowledge for \
health facts, statistics, or policies.
2. If the context does not contain an exact match for the user's query, do the following:
   - Provide the closest relevant information available in the context.
   - Clearly state that you could not find the exact information requested and that the \
information provided is the nearest available match.
   - Do not fabricate or infer data that is not present in the context.
3. Always cite your sources inline using [1], [2], etc. matching the numbered sources provided.
4. Respond in the same language the user asked in. If the user writes in Arabic, respond \
in Arabic. If in English, respond in English.
5. When citing statistics, ALWAYS state the year of the data explicitly. If the context \
contains the same statistic from multiple years, you MUST use and cite ONLY the most \
recent year's figure — not older figures. The publication year is shown as "(published \
YYYY)" next to each source. When answering, lead with the most recent figure and note \
the year (e.g. "As of 2024, ..." or "According to the 2023 yearbook, ..."). \
NEVER present an older statistic as if it is current.
6. Format your response to mirror the structure of the source material:
   - If the source uses bullet points or numbered lists, use the same structure.
   - If the source presents data in a table, reproduce it as a table. Only include rows \
for which data is explicitly present in the context — never fill in rows for regions, \
categories, or years that are not shown in the provided context chunks.
   - If the user explicitly requests a specific format (e.g. "summarise in bullets"), \
follow their instruction.
   - Otherwise, use clear, formal prose.
7. NEVER list, enumerate, or reference page numbers or sections that are not in the \
provided context. Do not say things like "the available pages are..." or imply you know \
the full structure of a document. You only know what is in the context given to you — \
nothing more. If the user claims a table or section exists that you cannot see, simply \
say you do not have that specific content in the current context, without speculating \
about what pages are or are not available.
8. When the context contains the same statistic broken down by multiple scopes — such as \
by sector (MOH, private, other governmental, total), by establishment type (hospitals, \
primary health care centres, clinics), or by nationality (Saudi, non-Saudi, total) — \
always present ALL available breakdowns, not just one. Label each breakdown clearly so \
the user can identify which figure applies to their situation. For example, if asked \
about physician counts and the context has figures for MOH hospitals, PHC centres, and \
the private sector separately, show each figure with its label rather than reporting \
only one. This is especially important for workforce, bed, and facility count queries \
where the scope (all establishments vs. MOH only vs. hospitals only) changes the number \
significantly.

You are a data research assistant, not a medical advisor. Never provide personal medical \
advice or clinical recommendations."""


_REWRITE_SYSTEM = (
    "You are a search query rewriter for a Saudi Arabian public health data platform. "
    "Given a conversation history and a follow-up question, rewrite the follow-up as a "
    "fully self-contained search query in the same language as the follow-up. "
    "Include all context needed to retrieve the relevant document passage. "
    "If the query does not mention a specific year, do NOT add one — the retrieval system "
    "already prefers the most recent data. "
    "Output ONLY the rewritten query — no explanation, no quotes."
)

_EXPAND_SYSTEM = (
    "You are a search query expander for a Saudi Arabian public health data platform. "
    "The platform indexes official statistics from MOH (Ministry of Health), GASTAT (General Authority for Statistics), "
    "CCHI (Council of Health Insurance), SHC (Saudi Health Council cancer registry), NHIC, and SFDA. "
    "Given a short or vague health query, expand it into a specific retrieval query that names "
    "the relevant metric, the data source, Saudi Arabia, and a recent year (prefer 2023 or 2024). "
    "Respond in the SAME LANGUAGE as the input query. "
    "Output ONLY the expanded query — no explanation, no quotes, no more than 25 words."
)


def _is_short_query(query: str) -> bool:
    """True for queries too short/vague to retrieve well without expansion (≤5 words or <45 chars)."""
    return len(query.split()) <= 5 and len(query.strip()) < 45


class RAGService:
    def __init__(self):
        settings = get_settings()
        self.client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        self.retrieval = RetrievalService()
        self.model = settings.llm_model

    async def _expand_query(self, query: str) -> str:
        """Expand a short / vague standalone query with Saudi health context."""
        if not _is_short_query(query):
            return query
        try:
            resp = await self.client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=80,
                system=_EXPAND_SYSTEM,
                messages=[{"role": "user", "content": query}],
            )
            expanded = resp.content[0].text.strip()
            # Only use the expansion if it's meaningfully longer (i.e. added context)
            if expanded and len(expanded) > len(query) + 5:
                logger.debug(f"Query expanded: '{query}' → '{expanded}'")
                return expanded
        except Exception as e:
            logger.warning(f"Query expansion failed, using original: {e}")
        return query

    async def _rewrite_query(self, query: str, chat_history: list[dict]) -> str:
        """Rewrite a follow-up question into a standalone retrieval query."""
        if not chat_history:
            return query
        # Only the last 3 turns (6 messages) for context — enough without being noisy
        recent = chat_history[-6:]
        history_text = "\n".join(
            f"{t['role'].upper()}: {t['content'][:200]}" for t in recent
        )
        prompt = f"Conversation so far:\n{history_text}\n\nFollow-up question: {query}"
        try:
            resp = await self.client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=120,
                system=_REWRITE_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )
            rewritten = resp.content[0].text.strip()
            if rewritten:
                logger.debug(f"Query rewritten: '{query}' → '{rewritten}'")
                return rewritten
        except Exception as e:
            logger.warning(f"Query rewrite failed, using original: {e}")
        return query

    async def get_answer(
        self,
        query: str,
        entity_filter: Optional[str] = None,
        doc_type_filter: Optional[str] = None,
        chat_history: Optional[list[dict]] = None,
    ) -> tuple[str, list[str], list[dict]]:
        """
        Non-streaming version for evaluation.
        Returns (answer_text, [raw_chunk_texts], [sources]).
        """
        retrieval_query = await self._rewrite_query(query, chat_history or [])
        # For standalone short queries that weren't rewritten (no history), expand with context
        if retrieval_query == query:
            retrieval_query = await self._expand_query(query)
        chunks = await self.retrieval.retrieve(
            query=retrieval_query,
            entity_filter=entity_filter,
            doc_type_filter=doc_type_filter,
        )
        if not chunks:
            return ("No relevant information found.", [], [])

        context_block = _build_context_block(chunks)
        messages = _build_messages(query, context_block, chat_history or [])
        sources = _build_sources(chunks)
        raw_contexts = []
        for c in chunks:
            parts = []
            title = c.document_title_en or c.document_title_ar
            if title:
                parts.append(f"[Source: {title}]")
            if c.section_heading:
                parts.append(f"[Section: {c.section_heading}]")
            parts.append(c.content)
            raw_contexts.append("\n".join(parts))

        response = await self.client.messages.create(
            model=self.model,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=messages,
        )
        answer = response.content[0].text
        return answer, raw_contexts, sources

    async def stream_answer(
        self,
        query: str,
        entity_filter: Optional[str] = None,
        doc_type_filter: Optional[str] = None,
        chat_history: Optional[list[dict]] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> AsyncIterator[str]:
        # Step 1: Rewrite follow-up queries, then retrieve
        retrieval_query = await self._rewrite_query(query, chat_history or [])
        # For standalone short queries that weren't rewritten (no history), expand with context
        if retrieval_query == query:
            retrieval_query = await self._expand_query(query)
        try:
            chunks = await self.retrieval.retrieve(
                query=retrieval_query,
                entity_filter=entity_filter,
                doc_type_filter=doc_type_filter,
            )
        except Exception as e:
            logger.error(f"Retrieval error: {e}")
            yield 'data: {"type": "error", "content": "Failed to search the knowledge base. Please try again."}\n\n'
            return

        if not chunks:
            yield 'data: {"type": "text", "content": "لم أجد معلومات ذات صلة في قاعدة البيانات. / No relevant information found in the database."}\n\n'
            return

        # Step 2: Build prompt
        context_block = _build_context_block(chunks)
        messages = _build_messages(query, context_block, chat_history or [])
        sources = _build_sources(chunks)

        # Step 3: Stream from Claude (async), buffer full response for DB save
        full_response = ""
        try:
            async with self.client.messages.stream(
                model=self.model,
                max_tokens=2048,
                system=SYSTEM_PROMPT,
                messages=messages,
            ) as stream:
                async for text in stream.text_stream:
                    full_response += text
                    payload = json.dumps({"type": "text", "content": text})
                    yield f"data: {payload}\n\n"

            sources_payload = json.dumps({"type": "sources", "sources": sources})
            yield f"data: {sources_payload}\n\n"
            yield "data: [DONE]\n\n"

            # Step 4: Persist to DB if authenticated
            if session_id and user_id and full_response:
                await _save_messages(session_id, user_id, query, full_response, sources)

        except anthropic.APIError as e:
            logger.error(f"Anthropic API error: {e}")
            error_payload = json.dumps({"type": "error", "content": "Failed to generate response."})
            yield f"data: {error_payload}\n\n"


async def _save_messages(
    session_id: str,
    user_id: str,
    query: str,
    response: str,
    sources: list[dict],
) -> None:
    """Save the user question and assistant answer to the chat session."""
    try:
        import asyncio
        await asyncio.to_thread(_save_messages_sync, session_id, user_id, query, response, sources)
    except Exception as e:
        logger.error(f"Failed to save chat messages: {e}")


def _save_messages_sync(
    session_id: str,
    user_id: str,
    query: str,
    response: str,
    sources: list[dict],
) -> None:
    from backend.database import get_session as db_session
    from backend.models.chat import ChatSession, ChatMessage
    from datetime import datetime, timezone

    with db_session() as db:
        session = db.query(ChatSession).filter_by(
            id=UUID(session_id), user_id=UUID(user_id)
        ).first()
        if not session:
            return

        # Auto-title from first message
        if not session.title:
            session.title = query[:80].strip()

        db.add(ChatMessage(session_id=UUID(session_id), role="user", content=query))
        db.add(ChatMessage(
            session_id=UUID(session_id),
            role="assistant",
            content=response,
            sources=sources,
        ))
        session.updated_at = datetime.now(timezone.utc)


def _build_context_block(chunks: list[RetrievedChunk]) -> str:
    lines = ["The following sources are available to answer the question:\n"]
    for i, chunk in enumerate(chunks, start=1):
        title = chunk.document_title_en or chunk.document_title_ar or "Untitled"
        entity = chunk.entity or "Unknown"
        year = chunk.publication_date[:4] if chunk.publication_date else "year unknown"
        source_line = f"[{i}] Source: {entity} — {title}"
        if chunk.page_number:
            source_line += f", page {chunk.page_number}"
        lines.append(source_line)
        # Year on its own line so the LLM cannot miss it when comparing sources
        lines.append(f"    DATA YEAR: {year}")
        if chunk.section_heading:
            lines.append(f"    Section: {chunk.section_heading}")
        lines.append(f"    {chunk.content}")
        lines.append("")
    return "\n".join(lines)


def _build_messages(
    query: str,
    context_block: str,
    chat_history: list[dict],
) -> list[dict]:
    messages = []
    for turn in chat_history[-6:]:
        messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": f"{context_block}\n\nQuestion: {query}"})
    return messages


def _build_sources(chunks: list[RetrievedChunk]) -> list[dict]:
    seen: set = set()
    sources = []
    for i, chunk in enumerate(chunks, start=1):
        key = (chunk.document_id, chunk.page_number)
        if key in seen:
            continue
        seen.add(key)
        sources.append({
            "index": i,
            "entity": chunk.entity,
            "title_ar": chunk.document_title_ar,
            "title_en": chunk.document_title_en,
            "url": chunk.original_url,
            "page_number": chunk.page_number,
            "section_heading": chunk.section_heading,
            "content": chunk.content[:300],
            "publication_date": chunk.publication_date,
        })
    return sources
