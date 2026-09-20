"""Repository fact collection ports and private execution context."""

from .cache import (
    FactsCache,
    FactsSerializationError,
    deserialize_facts,
    facts_cache_key,
    mark_facts_stale,
    serialize_facts,
)
from .compatibility import (
    CodeHealthCollector,
    PyDrillerActivityCollector,
    SourceCraftAppSecCollector,
    SourceCraftCicdCollector,
    SourceCraftIssuesCollector,
    ValeDocumentationCollector,
)
from .ports import (
    CollectionContext,
    CollectionError,
    CollectionLimits,
    CollectorPort,
    ProviderCollectorPort,
)

__all__ = [
    "CodeHealthCollector",
    "CollectionContext",
    "CollectionError",
    "CollectionLimits",
    "CollectorPort",
    "FactsCache",
    "FactsSerializationError",
    "ProviderCollectorPort",
    "PyDrillerActivityCollector",
    "SourceCraftAppSecCollector",
    "SourceCraftCicdCollector",
    "SourceCraftIssuesCollector",
    "ValeDocumentationCollector",
    "deserialize_facts",
    "facts_cache_key",
    "mark_facts_stale",
    "serialize_facts",
]
