from __future__ import annotations


class WeoroldError(Exception):
    """Base exception for public weorold failures."""


class DataSourceError(WeoroldError, RuntimeError):
    """Failure while retrieving or decoding an external data source."""
