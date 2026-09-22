"""Normalized repository-facts collection boundaries."""

from .cache import (
    FactsCache,
    FactsSerializationError,
    deserialize_facts,
    facts_cache_key,
    mark_facts_stale,
    serialize_facts,
)
from .ports import (
    CollectionContext,
    CollectionError,
    CollectionLimits,
    CollectorPort,
    ProviderCollectorPort,
)
from .service import CollectionService
from .sourcecraft import (
    CredentialProvider,
    EnvironmentCredentialProvider,
    SourceCraftAppSecCollector,
    SourceCraftAuthError,
    SourceCraftCicdCollector,
    SourceCraftClient,
    SourceCraftCollector,
    SourceCraftIssuesCollector,
    SourceCraftPageSet,
    SourceCraftPayloadError,
    SourceCraftRepositoryCollector,
    SourceCraftResourceCollector,
    SourceCraftResponse,
    SourceCraftUnavailableError,
)

__all__ = [
    "CollectionContext",
    "CollectionError",
    "CollectionLimits",
    "CollectionService",
    "CollectorPort",
    "CredentialProvider",
    "EnvironmentCredentialProvider",
    "FactsCache",
    "FactsSerializationError",
    "ProviderCollectorPort",
    "SourceCraftAppSecCollector",
    "SourceCraftAuthError",
    "SourceCraftCicdCollector",
    "SourceCraftClient",
    "SourceCraftCollector",
    "SourceCraftIssuesCollector",
    "SourceCraftPageSet",
    "SourceCraftPayloadError",
    "SourceCraftRepositoryCollector",
    "SourceCraftResourceCollector",
    "SourceCraftResponse",
    "SourceCraftUnavailableError",
    "deserialize_facts",
    "facts_cache_key",
    "mark_facts_stale",
    "serialize_facts",
]
