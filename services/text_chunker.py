"""Split extracted document text into overlapping chunks.

Two jobs, both of which the platform previously did without:

1. Feed knowledge-base generation in batches that fit the tier's budget. Before
   this, the *entire* corpus went into one prompt with a 4000-token output cap on
   Terra - which truncated the JSON mid-object and looked, to the user, like a bug
   in their documents.
2. Give the vector index something to embed. Retrieval over 800-token chunks is
   what makes a fact on page 30 of a handbook findable at all.
"""
import math
import re

# Deliberately pessimistic: English prose is closer to 1 token per 4.2 chars, and
# over-estimating means a batch lands under the model's real limit rather than
# over it. Being wrong in the cheap direction costs one extra API call; being
# wrong in the other direction costs a failed run.
CHARS_PER_TOKEN = 4

_PARAGRAPH_RE = re.compile(r'\n\s*\n')
_SENTENCE_RE = re.compile(r'(?<=[.!?])\s+')
_WHITESPACE_RE = re.compile(r'[ \t]+')


def estimate_tokens(text):
    """Rough token count. Cheap, dependency-free, and biased high on purpose."""
    if not text:
        return 0
    return int(math.ceil(len(text) / float(CHARS_PER_TOKEN)))


def _tidy(text):
    """Collapse runs of spaces/tabs but keep paragraph breaks, which carry structure."""
    text = (text or '').replace('\r\n', '\n').replace('\r', '\n')
    text = _WHITESPACE_RE.sub(' ', text)
    return re.sub(r'\n{3,}', '\n\n', text).strip()


def _split_units(text, max_chars):
    """Paragraphs -> sentences -> hard split. Returns pieces no longer than max_chars."""
    units = []
    for paragraph in _PARAGRAPH_RE.split(text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if len(paragraph) <= max_chars:
            units.append(paragraph)
            continue
        for sentence in _SENTENCE_RE.split(paragraph):
            sentence = sentence.strip()
            if not sentence:
                continue
            if len(sentence) <= max_chars:
                units.append(sentence)
                continue
            # One sentence longer than a whole chunk: a table, a minified blob, a
            # PDF that lost its punctuation. Cut it rather than drop it.
            for start in range(0, len(sentence), max_chars):
                piece = sentence[start:start + max_chars].strip()
                if piece:
                    units.append(piece)
    return units


def chunk_text(text, *, source=None, target_tokens=800, overlap_tokens=100, start_ord=0):
    """Chunk one document's text.

    Returns [{'id','source','ord','text','tokens'}, ...]. Chunks overlap by
    roughly overlap_tokens so a fact spanning a boundary stays retrievable from
    at least one side of it.

    Chunk per document rather than over a concatenated blob, so `source` is a
    real filename the chat context can attribute a passage to.
    """
    text = _tidy(text)
    if not text:
        return []

    target_chars = max(1, target_tokens * CHARS_PER_TOKEN)
    overlap_chars = max(0, min(overlap_tokens, target_tokens // 2) * CHARS_PER_TOKEN)

    units = _split_units(text, target_chars)
    chunks = []
    buffer = []
    buffer_len = 0

    def flush():
        nonlocal buffer, buffer_len
        if not buffer:
            return
        body = ' '.join(buffer).strip()
        if body:
            ordinal = start_ord + len(chunks)
            chunks.append({
                'id': 'c%05d' % ordinal,
                'source': source,
                'ord': ordinal,
                'text': body,
                'tokens': estimate_tokens(body),
            })
        # Carry the tail into the next chunk as overlap.
        if overlap_chars:
            tail, tail_len = [], 0
            for unit in reversed(buffer):
                if tail_len + len(unit) > overlap_chars:
                    break
                tail.insert(0, unit)
                tail_len += len(unit) + 1
            buffer, buffer_len = tail, tail_len
        else:
            buffer, buffer_len = [], 0

    for unit in units:
        if buffer and buffer_len + len(unit) + 1 > target_chars:
            flush()
        buffer.append(unit)
        buffer_len += len(unit) + 1

    # Final flush without carrying overlap forward.
    if buffer:
        body = ' '.join(buffer).strip()
        if body:
            ordinal = start_ord + len(chunks)
            chunks.append({
                'id': 'c%05d' % ordinal,
                'source': source,
                'ord': ordinal,
                'text': body,
                'tokens': estimate_tokens(body),
            })

    return chunks


def chunk_documents(documents, *, target_tokens=800, overlap_tokens=100):
    """Chunk [(source_label, text), ...] into one ordinal-continuous list."""
    chunks = []
    for source, text in documents:
        chunks.extend(chunk_text(text, source=source, target_tokens=target_tokens,
                                 overlap_tokens=overlap_tokens, start_ord=len(chunks)))
    return chunks


def group_for_map(chunks, max_input_tokens):
    """Greedily pack consecutive chunks into batches that fit one KB call.

    Never splits a chunk: a chunk too big for a whole batch gets a batch of its
    own, because a half-chunk would be worse input than a slightly oversized one.
    """
    if not chunks:
        return []
    budget = max(1, int(max_input_tokens or 1))
    batches = []
    current = []
    current_tokens = 0
    for chunk in chunks:
        tokens = chunk.get('tokens') or estimate_tokens(chunk.get('text', ''))
        if current and current_tokens + tokens > budget:
            batches.append(current)
            current, current_tokens = [], 0
        current.append(chunk)
        current_tokens += tokens
    if current:
        batches.append(current)
    return batches


def batch_text(batch):
    """Render one map batch back into prompt text, labelled by source."""
    parts = []
    last_source = object()
    for chunk in batch:
        source = chunk.get('source')
        if source != last_source:
            parts.append(f"\n\n--- {source or 'document'} ---")
            last_source = source
        parts.append(chunk.get('text', ''))
    return '\n\n'.join(part for part in parts if part).strip()
