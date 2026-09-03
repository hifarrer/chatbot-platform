"""Training failure taxonomy and the copy a customer actually reads.

The bug this exists to kill: training used to swallow every exception, fall
through to a broken fallback, and report "Chatbot trained successfully!". A
failure now has a stable machine code (for the front end and the logs) and a
sentence that tells the owner what to do about it.
"""


class TrainingError(Exception):
    """A training run that cannot complete. Carries a stable code, not just text."""

    def __init__(self, code, detail=None, *, phase=None, **fmt):
        self.code = code
        self.detail = detail
        self.phase = phase
        self.fmt = fmt
        super().__init__(detail or code)

    def friendly(self):
        return friendly_error(self.code, **self.fmt)

    def __str__(self):
        return self.detail or self.code


# Rules for this copy: say what happened, say whether their bot still works, and
# say what they can do next. Never show a stack trace or a model id - the raw
# detail goes in a collapsed <details> for support.
ERROR_COPY = {
    'no_api_key':
        "Training is temporarily unavailable because the AI service is not configured. "
        "Please contact support.",
    'openai_auth':
        "We couldn't reach the AI service with the current credentials. Your previous "
        "training is unchanged. Please contact support.",
    'openai_forbidden':
        "The AI service refused this request. Your previous training is unchanged. "
        "Please contact support.",
    'openai_model_missing':
        "The AI model for this chatbot is unavailable. Try a different model on the "
        "chatbot's settings, or contact support.",
    'openai_unavailable':
        "The AI service is busy or unreachable right now. Your previous training is "
        "unchanged - please try again in a few minutes.",
    'openai_timeout':
        "Training took too long and was stopped. Your previous training is unchanged. "
        "Try again, or split very large documents into smaller files.",
    'openai_bad_request':
        "The AI service rejected this training request. This usually means a document "
        "is too large - try splitting it into smaller files.",
    'no_text_extracted':
        "We couldn't read any text from: {files}. Scanned or image-only PDFs need to be "
        "converted to text before they can be used for training.",
    'corpus_too_large':
        "Your documents total {chars} characters, which is over the {limit} limit. "
        "Please remove or split some files and try again.",
    'too_many_chunks':
        "Your documents produced too many sections to index ({chunks}, limit {limit}). "
        "Please train on fewer files at a time.",
    'kb_empty':
        "The AI couldn't extract any usable facts from these documents. Check that they "
        "contain readable text rather than images or scans.",
    'kb_invalid_json':
        "The AI returned a malformed knowledge base. This is usually transient - please "
        "try again.",
    'file_missing':
        "A document file is missing from the server: {files}. Please re-upload it and "
        "train again.",
    'no_documents':
        "Please upload at least one document before training.",
    'interrupted':
        "Training was interrupted by a server restart. Your previous training is "
        "unchanged - please try again.",
    'cancelled':
        "Training was cancelled.",
    'storage_unavailable':
        "We couldn't save your file - the storage service isn't responding. Nothing was "
        "changed. Please try again in a moment.",
    'storage_auth':
        "File storage is misconfigured. Please contact support.",
    'storage_bad_request':
        "The storage service rejected that file. Please try again, or contact support if "
        "it keeps happening.",
    'storage_not_found':
        "That file is no longer in storage. Please re-upload it.",
    'storage_too_large':
        "That file is too large to store. Please upload a smaller one.",
    'internal':
        "Something went wrong during training. Your previous training is unchanged - "
        "please try again, or contact support if it keeps happening.",
}

FALLBACK_COPY = ERROR_COPY['internal']


def friendly_error(code, **fmt):
    """User-facing sentence for an error code. Never raises, never returns None."""
    template = ERROR_COPY.get(code or '', FALLBACK_COPY)
    if not fmt:
        return template
    try:
        return template.format(**fmt)
    except (KeyError, IndexError, ValueError):
        # A missing format field must not cost the user their error message.
        return template
