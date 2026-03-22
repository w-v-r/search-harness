# Search Service v0

Simple retrieval disappoints. Queries are underspecified, ambiguous, or both -- and single-shot search just shrugs and returns whatever it finds.

This SDK is a **search harness**: an opinionated, low-latency framework that wraps an existing search backend and **iterates toward the right answer**. It detects ambiguity, extracts structure, asks follow-up questions when they matter, and takes bounded additional search steps -- all while preserving the original query and surfacing every decision as a trace.

Inside the harness: an index, a backend adapter, LLM-powered query understanding. But those are components. The harness is the logic that ties them together -- the structure and opinions that let you go much further with search than simple retrieval ever could.

This is **not an agent**. It is a harness. Bounded, predictable, fast.

## Product Thesis

Most search queries against structured business data are underspecified. Users say *"show me Telstra stuff"* and mean something precise -- but the system has to figure out what.

This SDK treats search as a **decision process under uncertainty**:

- Detect when a query is ambiguous or underspecified
- Extract structured signals (entities, filters, intent) from natural language
- Run the best possible first search
- Decide whether to stop, ask a structured follow-up, or take another bounded search step
- **Always preserve the original query** and surface the full reasoning trace to the developer

The differentiator is not the retrieval and not the LLM -- it is the **iterated search** that navigates uncertainty, asks for clarification when it matters, and never silently discards the user's original intent.

### Search Principles

1. **The original query is always preserved.** Autonomous reformulations are additive, not substitutive. If the harness runs a modified query, it appears as an additional branch -- never a replacement.
2. **Ambiguity is surfaced, not hidden.** When uncertainty is material, the harness tells the developer what it found and what is missing, rather than guessing silently.
3. **AITL is bounded and observable.** Every autonomous step is traced. The harness does not run open-ended loops or make unbounded decisions.
4. **Traces are a product feature, not infrastructure.** Teams will not trust LLM-in-the-loop search unless they can inspect what happened. Every decision step -- classification, extraction, planning, execution, evaluation -- is captured and available to the developer.

### Interaction Modes

**HITL (Human in the Loop)** -- When ambiguity is material, the system returns a structured follow-up request (`needs_input`) with a schema the application can render however it wants. The search service returns structure, not UI.

**AITL (AI in the Loop)** -- Controlled navigation under uncertainty. The harness takes a small, bounded number of additional search actions: add filters from extracted structure, branch once, merge results. Max 2-3 iterations, max 2 branches, original query path always preserved. AITL is cautious by design -- it acts when it can reduce uncertainty, not when it can merely do more.

## Designed For

### Company / Entity Search

Queries like *"show me Telstra stuff"*, *"find Apple in Australia"*, *"show me all entities related to Acme."* The problems: ambiguous entity names, underspecified target type, missing disambiguating filters, noisy results from broad search.

### Document + Metadata Search

Queries like *"show me contracts for Telstra from last year"*, *"find onboarding docs for enterprise customers."* The problems: users mix content terms with metadata constraints, applications know the metadata structure but users do not, search should extract structure and turn it into filters.

These two use cases anchor v0 and prevent the product from drifting into generic LLM middleware.

## Target Users

- SaaS teams building user-facing app search
- Internal app developers searching structured business data

Optimized for **human-computer interaction around search** -- making structured data feel searchable and trustworthy -- not retrieval quality in isolation.

## Quick Start

The harness is an orchestrator that owns indexes, not a thin wrapper around a backend. You create a client, define indexes with their schema, adapter, and the kinds of queries you expect. The harness uses that configuration to shape classification, follow-ups, and search planning.

```python
from search_service import SearchClient, TypesenseAdapter
from my_models import CompanySchema

client = SearchClient(model="mercury-2", debug=True)

companies = client.indexes.create(
    name="companies",
    schema=CompanySchema,
    adapter=TypesenseAdapter(host="localhost", port=8108, api_key="xyz"),
    search_backend="keyword_filters",
    default_interaction_mode="hitl",
    searchable_fields=["company_name", "aliases", "description"],
    filterable_fields=["country", "industry", "status"],
    display_fields=["company_name", "country", "status"],
    expected_query_types=["entity_lookup", "name_search"],
)

result = companies.search("show me Telstra stuff")

if result.status == "needs_input":
    result = companies.continue_search(
        trace_id=result.trace_id,
        user_input={"entity_type": "company", "country": "AU"},
    )
```

### What `needs_input` looks like

When the harness detects material ambiguity, it returns a structured envelope -- not a boolean and hidden magic:

```json
{
  "status": "needs_input",
  "original_query": "show me Telstra stuff",
  "follow_up": {
    "reason": "underspecified_query",
    "message": "I found multiple possible interpretations of your query.",
    "input_schema": {
      "type": "object",
      "properties": {
        "entity_type": {"type": "string", "enum": ["company", "documents", "tickets"]},
        "region": {"type": "string"},
        "time_range": {"type": "string"}
      },
      "required": ["entity_type"]
    },
    "candidates": [
      {"label": "Telstra company records", "confidence": 0.62},
      {"label": "Telstra-related documents", "confidence": 0.31}
    ]
  },
  "trace_id": "abc-123"
}
```

The application owns how this is rendered -- dropdowns, forms, confirmation dialogs. The harness returns structure, not UI.

## v0 Scope

### In scope

- Python SDK
- Structured search only (existing backend wrapped via adapter, Typesense first)
- Keyword + filters retrieval
- Ambiguity detection and underspecified query handling
- Query analysis and classification
- Entity extraction and structured filter proposal
- HITL flow: structured follow-up via `needs_input` responses
- AITL flow: bounded iterative search with branch-and-merge (max 2-3 iterations, max 2 branches)
- Original query preservation across all branches and iterations
- Transparent traces capturing every decision step
- Opinionated defaults with escape hatches

### Out of scope

- Unstructured long-document recursive search
- Multimodal search
- Learning-to-rank
- Hosted control plane / admin UI
- Authentication / billing / multitenancy
- Browser UI
- Full vector / hybrid retrieval in v0 core

## Architecture

The system is layered so that the orchestration logic (where the product value lives) is independent from the underlying search backend. The backend adapter is swappable by design -- Typesense is the first real adapter, but it is not the identity of the product. The in-memory adapter ships for development and testing.

1. **SDK Layer** -- Developer-facing Python API (client, index, search, continue_search, trace)
2. **Orchestration Layer** -- Ambiguity detection, query understanding, search planning, iteration control, follow-up generation, stopping decisions
3. **Adapter Layer** -- Backend abstraction (in-memory, Typesense, future adapters). All backend communication goes through the adapter protocol.
4. **Model Layer** -- LLM providers for classification, extraction, and planning decisions
5. **Trace / Telemetry Layer** -- Step-level observability capturing every decision in the search process. Traces are first-class output, not just logging.

## Development

```bash
pip install -e ".[dev]"
pytest
```

## License

MIT
