# Palate --- Unified Product, Architecture & Query Surface

## Tagline

**What you forgot you wanted, when it matters.**

------------------------------------------------------------------------

# 1. Overview

**Palate** is a personal AI-powered decision system for the finer things
in life.

It captures, enriches, and operationalises your taste across
domains---wine, restaurants, music, cigars, and experiences---and uses
that memory to improve decisions in real time.

Core premise: \> You often know what you want---until the moment comes.

Palate resolves this by making taste **actionable under context**.

------------------------------------------------------------------------

# 2. Conceptual Reframe

Palate is: \> **A context-conditioned preference inference system**

## Formal Model

U(i \| c) = w_p \* P(i) + w_c \* M(i, c) + w_s \* S(i) - w_n \* N(i)

------------------------------------------------------------------------

# 3. Core System Layers

-   Memory
-   Enrichment
-   Context
-   Decision Engine

------------------------------------------------------------------------

# 4. Data Model (Condensed)

## Entity

``` json
{"id": "...", "type": "...", "canonical_name": "..."}
```

## Signals

``` json
{"type": "rating", "value": 4}
```

## Attributes (Latent)

``` json
{"intensity": 0.8, "richness": 0.9}
```

## Context

``` json
{"time_of_day": "evening", "intent": "relax"}
```

## Decision Memory

``` json
{"options": ["a","b"], "chosen": "b"}
```

------------------------------------------------------------------------

# 5. System Architecture

User Input → Parsing → Retrieval → Context Injection → Inference →
Ranking → Explanation

------------------------------------------------------------------------

# 6. Ranking

Phase 1: score = preference + context + familiarity + social

Phase 2: P(i \> j \| c)

------------------------------------------------------------------------

# 7. Core Use Cases

-   Wine list decisions\
-   Daily planning\
-   Restaurant selection\
-   Passive recall

------------------------------------------------------------------------

# 8. Query Surface (Product Definition)

This defines the **true product surface area**.

------------------------------------------------------------------------

## 1) Contextual Decision Queries (Primary)

**Pattern**\
"Given my current situation, what should I choose?"

**Examples** - "I feel like a premium oaky wine tonight" - "Something
quiet and intellectually stimulating in London"

**Mechanics** - intent extraction\
- attribute matching\
- context filtering\
- ranking

------------------------------------------------------------------------

## 2) Option Set Evaluation (Critical)

**Pattern**\
"Here are my options --- which should I pick?"

**Examples** - wine list\
- restaurant shortlist

**Output** - ranked options\
- explanation

------------------------------------------------------------------------

## 3) Memory-Augmented Decisions (Core Differentiator)

**Pattern**\
"What do I already know about this?"

**Examples** - "Have I tried this?"\
- "Who suggested this?"

**Output** - ratings\
- notes\
- provenance

------------------------------------------------------------------------

## 4) Attribute-Based Retrieval

**Pattern**\
"Show me things matching a style"

**Examples** - "Oaky wines I liked"\
- "Casual lively restaurants"

**Requirement** - structured attributes (not text only)

------------------------------------------------------------------------

## 5) Passive Recall

**Pattern**\
"Surface things I saved but forgot"

**Examples** - "What did I save for weekends?"

**Role** - solves recall failure

------------------------------------------------------------------------

## 6) Social Context Queries

**Pattern**\
"What came from specific people?"

**Examples** - "Wines Mike suggested"

**Importance** - strong ranking signal

------------------------------------------------------------------------

## 7) Negative Filtering

**Pattern**\
"Avoid things I didn't like"

**Examples** - "Exclude wines \< 3 rating"

**Role** - trust preservation

------------------------------------------------------------------------

## 8) Hybrid Queries

**Pattern**\
Combine multiple constraints

**Examples** - "Oaky wines on this list I haven't tried"\
- "Quiet things I saved nearby"

------------------------------------------------------------------------

## 9) Fuzzy Recall

**Pattern**\
"Approximate memory"

**Examples** - "That place with a view"

**Requirement** - embeddings / semantic search

------------------------------------------------------------------------

## 10) Exploration (Secondary)

**Pattern**\
"Suggest something new"

**Examples** - "Wines similar to what I like"

**Note** - lower priority

------------------------------------------------------------------------

# 9. Core Insight

All queries reduce to:

**Context + Intent + Memory → Ranked Output + Explanation**

------------------------------------------------------------------------

# 10. Prioritisation

## Must-have

1.  Option set evaluation\
2.  Contextual decisions\
3.  Memory recall

## Next

4.  Attribute retrieval\
5.  Hybrid queries

## Later

6.  Fuzzy recall\
7.  Exploration

------------------------------------------------------------------------

# 11. MVP Scope

Build first: - context model\
- decision logging\
- heuristic ranking

------------------------------------------------------------------------

# 12. Positioning

Not: \> discovery engine

But: \> decision layer over personal memory

------------------------------------------------------------------------

# Final Thought

Palate's value is not storing taste.

It is: \> learning what works, when it matters
