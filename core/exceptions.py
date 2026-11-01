"""Shared application exceptions."""


class DependencyUnavailable(RuntimeError):
    """Raised when a configured local dependency cannot be reached."""

