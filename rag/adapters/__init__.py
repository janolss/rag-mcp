"""Document format adapters."""

from rag.adapters.base import (
    AdapterError,
    DocumentAdapter,
    ExtractedDocument,
    adapter_registry,
    select_adapter,
)

__all__ = [
    "AdapterError",
    "DocumentAdapter",
    "ExtractedDocument",
    "adapter_registry",
    "select_adapter",
]
