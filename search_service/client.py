from __future__ import annotations

from typing import TYPE_CHECKING

from search_service._internal.context import SearchContext
from search_service.exceptions import IndexAlreadyExistsError, IndexNotFoundError
from search_service.indexes.base import SearchIndex
from search_service.schemas.config import IndexConfig
from search_service.telemetry.tracer import Tracer

if TYPE_CHECKING:
    from search_service.orchestration.analyzer import QueryAnalyzer


class IndexManager:
    """Manages the lifecycle of search indexes owned by a SearchClient.

    Accessed via `client.indexes`. Provides create, get, delete, and list
    operations for SearchIndex instances.
    """

    def __init__(
        self,
        tracer: Tracer,
        *,
        search_sessions: dict[str, SearchContext],
    ) -> None:
        self._store: dict[str, SearchIndex] = {}
        self._tracer = tracer
        self._search_sessions = search_sessions

    def create(
        self,
        config: IndexConfig,
        *,
        analyzer: QueryAnalyzer | None = None,
    ) -> SearchIndex:
        """Create a new search index from the given configuration.

        Args:
            config: IndexConfig defining the index identity, fields,
                adapter, and optional policy.
            analyzer: Optional QueryAnalyzer for LLM-powered search.
                When provided, searches use the orchestrated pipeline.

        Returns:
            A configured SearchIndex ready for search calls.

        Raises:
            IndexAlreadyExistsError: If an index with the same name exists.
        """
        if config.name in self._store:
            raise IndexAlreadyExistsError(config.name)

        index = SearchIndex(
            config,
            self._tracer,
            analyzer=analyzer,
            sessions=self._search_sessions,
        )
        self._store[config.name] = index
        return index

    def get(self, name: str) -> SearchIndex:
        """Retrieve an existing index by name.

        Raises:
            IndexNotFoundError: If no index with the given name exists.
        """
        if name not in self._store:
            raise IndexNotFoundError(name)
        return self._store[name]

    def delete(self, name: str) -> None:
        """Delete an index by name.

        Raises:
            IndexNotFoundError: If no index with the given name exists.
        """
        if name not in self._store:
            raise IndexNotFoundError(name)
        del self._store[name]

    def list(self) -> list[SearchIndex]:
        """Return all registered indexes."""
        return list(self._store.values())

    def __contains__(self, name: str) -> bool:
        return name in self._store

    def __len__(self) -> int:
        return len(self._store)

    def __repr__(self) -> str:
        names = list(self._store.keys())
        return f"IndexManager(indexes={names})"


class SearchClient:
    """Entry point for the search service SDK.

    Follows the standard Client -> Index pattern used by comparable
    search SDKs (Pinecone, Typesense, Algolia, etc.). The client owns
    indexes directly -- there is no intermediate App layer.

    Usage::

        from search_service import SearchClient, IndexConfig

        client = SearchClient()
        index = client.indexes.create(IndexConfig(
            name="companies",
            schema=CompanyDocument,
            adapter=my_adapter,
            searchable_fields=["name", "description"],
            id_field="id",
        ))
        result = index.search("Telstra")
    """

    def __init__(self) -> None:
        self._tracer = Tracer()
        self._search_sessions: dict[str, SearchContext] = {}
        self._indexes = IndexManager(self._tracer, search_sessions=self._search_sessions)

    @property
    def indexes(self) -> IndexManager:
        """Access the index manager for creating, retrieving, and managing indexes."""
        return self._indexes

    @property
    def tracer(self) -> Tracer:
        """Access the shared tracer for retrieving search traces."""
        return self._tracer

    def __repr__(self) -> str:
        return f"SearchClient(indexes={len(self._indexes)})"
