"""Package-owned exception hierarchy."""


class SteleError(Exception):
    """Base exception for all public package errors."""


class ConfigError(SteleError):
    """Configuration is invalid or unsupported."""


class BackendError(SteleError):
    """Backend operation failed."""


class ArtifactNotFound(SteleError):
    """Artifact reference does not exist."""


class CapabilityError(SteleError):
    """Requested capability is not supported by the configured backend."""


class ReferenceError(SteleError):
    """Reference parsing or validation failed."""


class SignatureError(ReferenceError):
    """Reference signature validation failed."""


class PIIBlockedError(SteleError):
    """A PII policy blocked the requested output."""


class OptionalDependencyError(SteleError):
    """An optional dependency required by a configured feature is missing."""


class IndexingError(SteleError):
    """Indexing failed."""


class ValidationError(SteleError):
    """Input failed validation before any backend call."""

