from __future__ import annotations


class ClifError(Exception):
    """Base class for all library-specific errors."""


class ClifParseError(ClifError):
    """Raised when CLIF text cannot be parsed into a document.

    ``category`` uses the same diagnostic categories as
    :class:`~pyclif.model.ValidationIssue`.
    """

    def __init__(
        self,
        message: str,
        *,
        line: int = 0,
        category: str = "syntax",
        text: str = "",
    ) -> None:
        super().__init__(message)
        self.message = message
        self.line = line
        self.category = category
        self.text = text
