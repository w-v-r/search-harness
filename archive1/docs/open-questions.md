# Open Questions

These areas are deliberately left flexible in the v0 codebase. They should remain configurable rather than prematurely fixed.

## 1. Exact Prompt Templates

The LLM prompts for classification, extraction, planning, and follow-up generation are not locked down. v0 will ship with working defaults, but the prompt strategy should be easy to swap and iterate on.

## 2. Confidence Scoring Strategy

How confidence scores are computed for ambiguity detection, result quality assessment, and branch comparison is not finalized. v0 will use simple heuristics; a calibrated model may replace them later.

## 3. Branch Merge Strategy

When AITL runs multiple branches, how results are merged (interleaved, ranked, deduplicated) is underspecified. v0 will use a simple concatenation/dedup approach.

## 4. Query Classification Taxonomy

Query types are developer-defined strings, not a system enum (see decisions.md #8). The harness classifies queries against the index's `expected_query_types` vocabulary. The open question is how much structure to provide around classification: should the harness suggest conventions, ship example taxonomies, or leave it entirely to the developer?

## 5. Dynamic Follow-Up Schema Approach

Whether dynamic follow-up schemas use a library like dydantic directly or a custom schema builder abstraction is not decided. v0 will experiment and pick the simpler path.

## 6. Backend Query DSL Translation Model

The exact model for translating a generic search plan into backend-native query DSL (Typesense multi_search, Elasticsearch query DSL, SQL) is underspecified. The adapter protocol defines the boundary, but the internal translation strategy may evolve.
