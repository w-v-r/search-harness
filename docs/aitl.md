# AITL: AI in the Loop

## What AITL Is

AITL is a **bounded decision loop** for navigating search under uncertainty. When a single retrieval pass is not enough -- the query is ambiguous, the results are weak, or extracted structure suggests a better search is available -- AITL takes additional steps to converge on a good answer.

It is controlled navigation. Not an agent.

An agent has open-ended goals, reasons about what to do in an unbounded way, and may take an unpredictable number of actions. AITL has a fixed budget, a fixed set of allowed actions, and makes decisions based on concrete context. It runs a short, observable loop and stops.

## What AITL Is Not

- Not an agent. No open-ended planning, no tool use, no self-directed goal-setting.
- Not a retry loop. It does not blindly repeat the same search. Each step must use new information.
- Not a query rewriter. If it reformulates, the reformulation is an additional branch, not a replacement. The original query is always preserved.
- Not unbounded. Hard limits on iterations and branches. The loop terminates predictably.

## What AITL Knows

The AITL decision loop operates with three categories of context. These are not vague background knowledge -- they are concrete inputs available at each decision point.

### 1. Instructions

Static context set at the start of the search. Does not change during iteration.

- **Interaction mode:** AITL (confirmed -- the harness chose or was told to use autonomous navigation)
- **Budget:** Maximum iterations allowed (default 2-3). Maximum branches allowed (default 2).
- **Confidence thresholds:** When results are good enough to stop.
- **Index configuration:** Searchable fields, filterable fields, entity types, display fields. What the index looks like and what structure is available.
- **Profiles / expected query types:** What kinds of queries are expected for this index. Shapes what extraction and classification the harness attempts.
- **Invariants:** Original query must be preserved. Reformulations are additive. Every step is traced.

### 2. Self-Knowledge

Dynamic context that updates after each step. This is what makes AITL budget-aware.

- **Iterations used:** How many search steps have been taken so far.
- **Iterations remaining:** How many more steps are available. This is the most important signal for action selection -- if one iteration remains, spend it on the highest-value action available, not a speculative probe.
- **Branches created:** How many parallel search paths exist.
- **Branches remaining:** Whether branching is still an option.
- **Actions taken:** What queries have been run, what filters have been applied, what reformulations have been tried. Prevents repeating the same action.
- **Current state:** Just started, mid-iteration, approaching budget limit, at final iteration.

### 3. Problem State

Accumulated information about the specific search problem. Grows with each step.

- **Original query:** The raw user input. Never modified, always available.
- **Query analysis:** Classification (entity_lookup, document_lookup, etc.), extracted entities, proposed filters, ambiguity level.
- **Search results so far:** Results from each executed search step, per branch. Result counts, scores, matched fields.
- **Confidence assessment:** How good the current results are. Whether they answer the likely intent.
- **Extracted but unapplied structure:** Filters or entities that have been identified but not yet used in a search. This is a key input for deciding the next action -- if structure has been extracted but not applied, applying it is usually the highest-value next step.
- **What's missing:** Gaps identified by the evaluator. Missing disambiguating filters, ambiguous entity resolution, result set too broad or too narrow.

## How AITL Decides

At each step, the decision loop asks a simple question: **given what I know and what I have left, what is the most valuable thing I can do?**

The decision is not open-ended reasoning. It is a structured choice from a small set of allowed actions:

1. **Stop and return results.** Confidence is acceptable. Results answer the likely intent.
2. **Apply extracted filters.** Structure has been identified but not yet used. This is almost always the highest-value action when available.
3. **Branch.** Run the original query alongside a filter-augmented or reformulated version. Only if branch budget remains.
4. **Escalate to needs_input.** Uncertainty is too high to resolve autonomously. Return structured follow-up to the application. (AITL can decide it cannot proceed and fall back to HITL-style output.)

### Budget Awareness

The remaining budget directly affects action selection:

- **Multiple iterations remaining:** Can afford a speculative step (e.g., try a reformulation, see if it helps).
- **One iteration remaining:** Must choose the single highest-value action. No room for speculation. If extracted structure is available, apply it. If not, stop or escalate.
- **Budget exhausted:** Return whatever results are available. Trace captures why.

This is the core difference from an agent: the AITL does not reason about whether to continue. The budget decides. The AITL only decides *what to do* within the budget it has left.

## How AITL Relates to HITL

AITL and HITL are not separate systems. They share the same pipeline:

- Same query analyzer, same classifier, same extractor
- Same adapter protocol, same result envelope, same trace system
- Same evaluator logic for assessing results

The difference is the **response to uncertainty**:

| Situation | HITL | AITL |
|---|---|---|
| Ambiguity detected | Return `needs_input` immediately | Try to resolve within budget, escalate if it cannot |
| Weak results | Return results with low confidence | Try filter augmentation or branching within budget |
| Missing structure | Ask the user | Attempt extraction, apply if confident enough |
| Budget exhausted | N/A | Return best available results, trace captures reasoning |

AITL can always fall back to a `needs_input` response if autonomous resolution fails. The modes are a spectrum, not a wall.

## Trace Contract

Every AITL step produces a trace entry. The trace captures:

- What action was chosen and why
- What context was available at the decision point (iterations remaining, branches remaining, extracted structure)
- What the outcome was (result count, confidence, new information gained)
- Whether the action was valuable (did it improve results or reduce uncertainty?)

This is what makes AITL trustworthy. The developer can inspect every decision after the fact and understand whether the harness spent its budget well.
