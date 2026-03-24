"""Typesense backend adapter: schema mapping, search, filters, and multi-search.

Maps :class:`~search_service.schemas.config.IndexConfig` document models to
Typesense collection field definitions, translates orchestration
:class:`~search_service.adapters.base.BackendSearchRequest` objects into
Typesense search parameters, and normalizes Typesense hits into plain document
dicts for the executor.
"""

from __future__ import annotations

import json
import re
import types
from typing import Any, Union, cast, get_args, get_origin

import typesense
from pydantic import BaseModel
from typesense.types.collection import (
    CollectionCreateSchema,
    ReferenceCollectionFieldSchema,
    RegularCollectionFieldSchema,
)
from typesense.types.document import MultiSearchParameters, SearchParameters, SearchResponse
from typesense.types.multi_search import MultiSearchRequestSchema, MultiSearchResponse

from search_service.adapters.base import BackendSearchRequest, BackendSearchResponse
from search_service.schemas.config import IndexConfig

# ---------------------------------------------------------------------------
# Filter translation (orchestration dict -> Typesense filter_by string)
# ---------------------------------------------------------------------------

_FILTER_OPERATORS = {
    "$gt": ">",
    "$gte": ">=",
    "$lt": "<",
    "$lte": "<=",
    "$ne": "!=",
}


def _string_needs_backticks(value: str) -> bool:
    if value == "":
        return True
    return not re.fullmatch(r"[A-Za-z0-9_.-]+", value)


def _escape_backtick_string(value: str) -> str:
    """Wrap a string for Typesense filter_by; escape embedded backticks."""
    escaped = value.replace("`", r"\`")
    return f"`{escaped}`"


def _format_scalar_for_filter(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, str):
        if _string_needs_backticks(value):
            return _escape_backtick_string(value)
        return value
    return _escape_backtick_string(json.dumps(value))


def filters_to_filter_by(filters: dict[str, Any]) -> str | None:
    """Translate orchestration filter dicts into a Typesense ``filter_by`` string.

    Supports the same shapes as :class:`~search_service.adapters.in_memory.InMemoryAdapter`:

    - Scalar: exact match (``field:=value``).
    - ``list``: OR match (``field:=[a,b]``).
    - ``dict`` with ``$gt`` / ``$gte`` / ``$lt`` / ``$lte`` / ``$ne`` operators.

    Multiple top-level keys are combined with ``&&``.

    Raises:
        ValueError: If a dict-shaped condition uses keys other than the supported
            ``$gt``/``$gte``/``$lt``/``$lte``/``$ne`` operators, or is an empty dict.
            (Failing loudly avoids silently omitting ``filter_by`` and returning
            unfiltered results.)
    """
    if not filters:
        return None

    parts: list[str] = []
    for field_name, condition in filters.items():
        if isinstance(condition, dict):
            if not condition:
                raise ValueError(
                    f"Empty operator dict for filter field {field_name!r} is not supported "
                    "for Typesense filter_by."
                )
            unknown = [k for k in condition if k not in _FILTER_OPERATORS]
            if unknown:
                raise ValueError(
                    f"Unknown filter operator key(s) for field {field_name!r}: {unknown}. "
                    f"Supported keys: {sorted(_FILTER_OPERATORS)}."
                )
            for op_key, target in condition.items():
                ts_op = _FILTER_OPERATORS[op_key]
                rhs = _format_scalar_for_filter(target)
                if ts_op == "!=":
                    parts.append(f"{field_name}:!={rhs}")
                else:
                    parts.append(f"{field_name}:{ts_op}{rhs}")
        elif isinstance(condition, list):
            if not condition:
                continue
            inner = ",".join(_format_scalar_for_filter(v) for v in condition)
            parts.append(f"{field_name}:=[{inner}]")
        else:
            rhs = _format_scalar_for_filter(condition)
            parts.append(f"{field_name}:={rhs}")

    if not parts:
        return None

    return " && ".join(parts)


# ---------------------------------------------------------------------------
# Schema mapping (IndexConfig / Pydantic -> Typesense collection create)
# ---------------------------------------------------------------------------

def _split_optional(annotation: Any) -> tuple[Any, bool]:
    """If annotation is ``T | None``, return (T, True)."""
    origin = get_origin(annotation)
    if origin is Union or origin is types.UnionType:
        args = get_args(annotation)
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1 and type(None) in args:
            return non_none[0], True
    return annotation, False


def _annotation_to_typesense_type(annotation: Any) -> str:
    """Map a simple Pydantic field annotation to a Typesense field ``type`` string."""
    ann, _ = _split_optional(annotation)
    origin = get_origin(ann)

    if origin is list:
        args = get_args(ann)
        inner = args[0] if args else str
        inner_plain, _ = _split_optional(inner)
        inner_origin = get_origin(inner_plain)
        if inner_origin is list:
            return "string[]"
        if inner_plain is str:
            return "string[]"
        if inner_plain is int:
            return "int64[]"
        if inner_plain is float:
            return "float[]"
        if inner_plain is bool:
            return "bool[]"
        return "string[]"

    if ann is str:
        return "string"
    if ann is int:
        return "int64"
    if ann is float:
        return "float"
    if ann is bool:
        return "bool"

    if origin is dict:
        return "object"

    return "string"


def field_schema_from_model(model: type) -> list[RegularCollectionFieldSchema]:
    """Build Typesense field definitions from a Pydantic v2 ``BaseModel`` subclass."""
    if not (isinstance(model, type) and issubclass(model, BaseModel)):
        return []

    fields: list[RegularCollectionFieldSchema] = []
    for name, finfo in model.model_fields.items():
        ann = finfo.annotation
        ts_type = _annotation_to_typesense_type(ann)
        _, is_optional = _split_optional(ann)
        field = cast(
            RegularCollectionFieldSchema,
            {
                "name": name,
                "type": ts_type,
                **({"optional": True} if (is_optional or finfo.is_required() is False) else {}),
            },
        )
        fields.append(field)

    return fields


def collection_schema_from_index_config(config: IndexConfig) -> CollectionCreateSchema:
    """Map an :class:`~search_service.schemas.config.IndexConfig` to a Typesense ``CollectionCreateSchema``.

    Collection ``name`` is the index :attr:`~search_service.schemas.config.IndexConfig.name`.
    Fields are derived from ``document_schema`` when it is a Pydantic model; every
    declared field becomes a Typesense field. Faceting is enabled for fields listed
    in ``filterable_fields``.
    """
    schema_model = config.document_schema
    raw_fields = field_schema_from_model(schema_model)

    filterable = set(config.filterable_fields)
    merged: list[RegularCollectionFieldSchema | ReferenceCollectionFieldSchema] = []
    for f in raw_fields:
        name = f["name"]
        copy = cast(RegularCollectionFieldSchema, dict(f))
        if name in filterable:
            copy["facet"] = True
        merged.append(copy)

    return cast(
        CollectionCreateSchema,
        {
            "name": config.name,
            "fields": merged,
        },
    )


def create_collection_if_missing(client: typesense.Client, config: IndexConfig) -> None:
    """Create the Typesense collection from ``config`` if it does not exist.

    No-op when the collection is already present. Callers typically run this
    once at startup or in migrations before indexing documents.
    """
    name = config.name
    if name in client.collections:
        return
    schema = collection_schema_from_index_config(config)
    client.collections.create(schema)


# ---------------------------------------------------------------------------
# Search parameter building
# ---------------------------------------------------------------------------

def _query_by_fields(request: BackendSearchRequest, fallback: list[str]) -> list[str]:
    return list(request.fields) if request.fields else list(fallback)


def build_search_parameters(
    request: BackendSearchRequest,
    *,
    query_by: list[str],
) -> SearchParameters:
    """Translate a :class:`BackendSearchRequest` into Typesense ``SearchParameters``."""
    if not query_by:
        raise ValueError(
            "query_by must name at least one field; pass BackendSearchRequest.fields "
            "or configure the adapter with non-empty searchable_fields."
        )
    qb = ",".join(query_by)
    params: SearchParameters = {
        "q": request.query if request.query.strip() else "*",
        "query_by": qb,
        "per_page": request.limit,
        "offset": request.offset,
    }
    fb = filters_to_filter_by(request.filters)
    if fb:
        params["filter_by"] = fb
    return params


def _search_response_to_backend(
    response: SearchResponse[Any],
    *,
    raw_extra: dict[str, Any] | None = None,
) -> BackendSearchResponse:
    """Normalize a Typesense ``SearchResponse`` into a :class:`BackendSearchResponse`."""
    hits_raw = response.get("hits") or []
    hits: list[dict[str, Any]] = []
    for h in hits_raw:
        # Only expose stored document fields; scores/highlights remain in raw_response.
        doc = dict(h.get("document") or {})
        hits.append(doc)

    raw: dict[str, Any] = dict(response)
    if raw_extra:
        raw["_adapter"] = raw_extra

    return BackendSearchResponse(
        hits=hits,
        total_count=int(response.get("found") or 0),
        query_time_ms=float(response.get("search_time_ms") or 0),
        raw_response=raw,
    )


def multi_search_request_from_branches(
    collection_name: str,
    requests: list[BackendSearchRequest],
    *,
    default_query_by: list[str],
) -> MultiSearchRequestSchema:
    """Build a federated multi-search body from parallel branch requests.

    Each :class:`BackendSearchRequest` becomes one entry in ``searches`` with the
    same ``collection``. Per-request ``query_by`` comes from ``request.fields`` or
    ``default_query_by``.
    """
    searches: list[MultiSearchParameters] = []
    for req in requests:
        qb = _query_by_fields(req, default_query_by)
        base = build_search_parameters(req, query_by=qb)
        merged: dict[str, Any] = {**cast(dict[str, Any], base), "collection": collection_name}
        searches.append(cast(MultiSearchParameters, merged))
    return {"searches": searches}


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class TypesenseAdapter:
    """Typesense implementation of :class:`~search_service.adapters.base.SearchAdapter`.

    Parameters
    ----------
    client:
        Configured ``typesense.Client`` instance.
    collection_name:
        Typesense collection name (often the same as :attr:`IndexConfig.name`).
    searchable_fields:
        Default ``query_by`` fields when :attr:`BackendSearchRequest.fields` is empty.
    """

    def __init__(
        self,
        client: typesense.Client,
        collection_name: str,
        searchable_fields: list[str],
    ) -> None:
        self._client = client
        self._collection_name = collection_name
        self._searchable_fields = list(searchable_fields)

    @property
    def client(self) -> typesense.Client:
        return self._client

    @property
    def collection_name(self) -> str:
        return self._collection_name

    def search(self, request: BackendSearchRequest) -> BackendSearchResponse:
        """Run a single collection search (wraps ``documents.search``)."""
        query_by = _query_by_fields(request, self._searchable_fields)
        params = build_search_parameters(request, query_by=query_by)
        coll = self._client.collections[self._collection_name]
        response = coll.documents.search(params)
        return _search_response_to_backend(
            response,
            raw_extra={"mode": "single", "collection": self._collection_name},
        )

    def multi_search(self, requests: list[BackendSearchRequest]) -> list[BackendSearchResponse]:
        """Run multiple searches in one HTTP round-trip (Typesense multi-search).

        Uses the adapter's default ``searchable_fields`` for ``query_by`` when a
        request's ``fields`` list is empty. Order of results matches ``requests``.
        """
        if not requests:
            return []

        body = multi_search_request_from_branches(
            self._collection_name,
            requests,
            default_query_by=self._searchable_fields,
        )
        combined: MultiSearchResponse = self._client.multi_search.perform(body)
        results = combined.get("results") or []
        out: list[BackendSearchResponse] = []
        for i, ts_response in enumerate(results):
            extra = {"mode": "multi", "index": i, "collection": self._collection_name}
            out.append(_search_response_to_backend(ts_response, raw_extra=extra))
        return out
