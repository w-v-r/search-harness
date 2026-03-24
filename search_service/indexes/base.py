from __future__ import annotations

from typing import TYPE_CHECKING, Any

from search_service._internal.context import SearchContext
from search_service.exceptions import SearchExecutionError
from search_service.indexes.runtime import (
    continue_orchestrated_search,
    execute_orchestrated_search,
    execute_search,
)
from search_service.schemas.config import IndexConfig
from search_service.schemas.enums import InteractionMode
from search_service.schemas.result import SearchResultEnvelope
from search_service.telemetry.tracer import Tracer

if TYPE_CHECKING:
    from search_service.orchestration.analyzer import QueryAnalyzer


class SearchIndex:
    """A configured search index that can execute searches.

    Created via `client.indexes.create(config)`. Holds the index
    configuration and provides the search API surface.

    When an analyzer is provided, searches use the full orchestrated
    pipeline (analyze -> plan -> execute -> evaluate). Without an
    analyzer, searches fall back to the direct pipeline.
    """

    def __init__(
        self,
        config: IndexConfig,
        tracer: Tracer,
        *,
        analyzer: QueryAnalyzer | None = None,
        sessions: dict[str, SearchContext] | None = None,
    ) -> None:
        self._config = config
        self._tracer = tracer
        self._analyzer = analyzer
        self._sessions = sessions if sessions is not None else {}

    @property
    def config(self) -> IndexConfig:
        return self._config

    @property
    def name(self) -> str:
        return self._config.name

    @property
    def analyzer(self) -> QueryAnalyzer | None:
        return self._analyzer

    @property
    def tracer(self) -> Tracer:
        return self._tracer

    def search(
        self,
        query: str,
        *,
        interaction_mode: InteractionMode | None = None,
        filters: dict[str, Any] | None = None,
    ) -> SearchResultEnvelope:
        """Execute a search query against this index.

        When an analyzer is configured, runs the full orchestrated
        pipeline (analyze -> plan -> execute -> evaluate loop).
        Otherwise, runs the direct search pipeline.

        Args:
            query: The user's search query string.
            interaction_mode: Override the index's default interaction mode
                for this search. If None, uses the index's default.
            filters: Optional pre-specified filters to apply.

        Returns:
            SearchResultEnvelope with status, results, and trace.
        """
        if self._analyzer is not None:
            return execute_orchestrated_search(
                query,
                self._config,
                self._tracer,
                self._analyzer,
                interaction_mode=interaction_mode,
                filters=filters,
                sessions=self._sessions,
            )

        return execute_search(
            query,
            self._config,
            self._tracer,
            interaction_mode=interaction_mode,
            filters=filters,
        )

    def continue_search(
        self,
        trace_id: str,
        user_input: dict[str, Any],
    ) -> SearchResultEnvelope:
        """Continue a search that returned status='needs_input'.

        Resumes the search pipeline with the user's response to a
        follow-up request. The trace is preserved across continuations.

        Args:
            trace_id: The trace_id from the original SearchResultEnvelope.
            user_input: User's response matching the follow_up.input_schema.

        Returns:
            SearchResultEnvelope with updated status and results.
        """
        if self._analyzer is None:
            raise SearchExecutionError(
                "continue_search requires an index configured with a QueryAnalyzer"
            )
        return continue_orchestrated_search(
            trace_id,
            user_input,
            self._config,
            self._tracer,
            sessions=self._sessions,
        )

    def __repr__(self) -> str:
        return f"SearchIndex(name={self.name!r})"
