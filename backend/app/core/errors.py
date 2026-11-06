"""Domain errors with user-meaningful messages.

Every error carries a stable `code` (for the frontend to branch on), a message
written for humans, and whether retrying could help.
"""

from __future__ import annotations


class StudioError(Exception):
    code = "studio_error"
    status_code = 400
    retryable = False

    def __init__(self, message: str, *, code: str | None = None, retryable: bool | None = None, details: dict | None = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if retryable is not None:
            self.retryable = retryable
        self.details = details or {}

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "retryable": self.retryable, "details": self.details}


class NotFoundError(StudioError):
    code = "not_found"
    status_code = 404


class PermissionDeniedError(StudioError):
    code = "forbidden"
    status_code = 403


class AuthError(StudioError):
    code = "unauthorized"
    status_code = 401


class ValidationFailed(StudioError):
    code = "validation_failed"
    status_code = 422


class ConflictError(StudioError):
    code = "conflict"
    status_code = 409


class RateLimitedError(StudioError):
    code = "rate_limited"
    status_code = 429
    retryable = True


class UnsupportedFileError(StudioError):
    code = "unsupported_file"
    status_code = 415


class CorruptedFileError(StudioError):
    code = "corrupted_file"
    status_code = 422


class InsufficientStorageError(StudioError):
    code = "insufficient_storage"
    status_code = 507
    retryable = True


class ProviderError(StudioError):
    """An external engine (TTS, OCR, LLM, embeddings) failed."""

    code = "provider_error"
    status_code = 502
    retryable = True

    def __init__(self, provider: str, message: str, *, retryable: bool = True, code: str | None = None):
        super().__init__(message, code=code, retryable=retryable, details={"provider": provider})
        self.provider = provider


class ProviderUnavailableError(ProviderError):
    code = "provider_unavailable"
    status_code = 503


class ProviderTimeoutError(ProviderError):
    code = "provider_timeout"
    status_code = 504


class ProviderRateLimitError(ProviderError):
    code = "provider_rate_limited"
    status_code = 429


class UnsupportedLanguageError(StudioError):
    code = "unsupported_language"
    status_code = 422


class JobCancelled(Exception):
    """Raised inside workers when a job was cancelled or paused by the user."""

    def __init__(self, paused: bool = False):
        super().__init__("paused" if paused else "cancelled")
        self.paused = paused
