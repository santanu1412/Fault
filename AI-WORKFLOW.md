# AI Workflow

> How AI/LLM is used in the system, exact prompts, guardrails, and fallback behavior.

## Principle: AI Augments Communication, Not Decision Logic

The fault localization algorithm is **entirely deterministic** — a tree-walk boundary detector that is unit-testable and explainable. AI is used downstream for two narrow features that improve operator experience without affecting correctness.

## Feature 1: Dispatch Narrative

**Trigger**: Automatically on ticket creation.

**Input**: Structured incident JSON:
```json
{
  "kind": "span",
  "boundary_poles": [{"parent": "P-0042", "child": "P-0043"}],
  "coordinates": {"lat": 12.9716, "lon": 77.5946},
  "pincode": "560001",
  "households_affected": 120,
  "confidence": 0.82,
  "topology_basis": "inferred"
}
```

**System Prompt**:
```
You write short, factual dispatch briefs for electricity control-room operators
from structured incident data. Given fields for fault type, location, confidence,
and topology basis, produce 2–3 plain sentences: what kind of fault, where
(coordinates + PIN), how many households, and one line on confidence caveats if
topology was inferred rather than surveyed. Never invent facts not present in the
input. No speculation about cause.
```

**Output**: 2-3 sentence plain-English brief.

**Fallback**: If the API call fails, times out (3s), or no API key is configured:
```
"Span fault detected near coordinates (12.9716°N, 77.5946°E), PIN code 560001.
Approximately 120 households affected. Confidence: 82% (inferred topology —
verify span boundaries before dispatch)."
```

## Feature 2: Grounded Q&A

**Trigger**: Operator asks a question via the ticket detail panel.

**System Prompt**:
```
Answer the operator's question using only the ticket JSON provided. If the answer
isn't in the data, say so plainly and suggest what data would answer it. Do not
guess coordinates, times, or crew details.
```

**Guardrail**: The ticket JSON is the only context provided. No external data, no tool use, no web access.

**Fallback**: `"Unable to process question at this time. Please refer to the ticket details above."`

## What AI Does NOT Do

- ❌ Fault localization (deterministic algorithm only)
- ❌ Confidence scoring (weighted formula, not ML)
- ❌ Ticket state transitions (state machine rules)
- ❌ Topology inference (Prim's MST, not learned)
- ❌ False positive filtering (rule-based: debounce, outage window, sensor-suspect)

## Cost & Degradation

- **Cost**: ~$0.001 per narrative generation (short prompt + short completion)
- **Degradation**: System is fully functional without an API key. All AI features silently fall back to templates.
- **No API key required for deployment**: The `ANTHROPIC_API_KEY` environment variable is optional.

---

## Where AI Got It Wrong

This section documents cases where AI-generated code was incorrect or had to be thrown away during development.

1. **WebSocket implementation for SSE**: The initial AI-generated code used raw WebSocket upgrades with manual frame management. This was fragile and broke on proxy reconnects. Replaced with `StreamingResponse` using a standard SSE generator pattern, which is simpler and handles reconnection natively via `Last-Event-ID`.

2. **LLM-based confidence scoring**: An early suggestion was to use an LLM to assess "how confident are we in this fault location?" based on the topology and telemetry. This was fundamentally wrong — confidence should be a deterministic weighted formula so it's testable and explainable. Replaced with the four-factor formula (topology, device coverage, recency, RSSI) that produces the same score every time for the same inputs.

3. **Over-engineered deduplication**: AI initially generated a Bloom filter approach for telemetry deduplication. This was overkill for our scale (~500 msg/s) and harder to debug. Replaced with a simple PostgreSQL `UNIQUE(device_id, seq)` constraint and `ON CONFLICT DO NOTHING` — three lines of SQL that accomplish the same thing with full transactional guarantees.

4. **Map marker DOM churn**: The first AI-generated MapView created individual `<div>` DOM markers for every pole and re-created them on every poll. At 3,000 poles with 3s polling, this caused visible flicker and memory leaks. Replaced with MapLibre GeoJSON source layers (GPU-accelerated circles) updated via `source.setData()` — zero DOM manipulation per poll cycle.

5. **Missing edge cases in tree walk**: The initial AI-generated localization code didn't handle the case where a dark pole has live descendants (sensor suspect). It would have created false-positive tickets for every dead battery. Added `_has_any_live_descendant` check specifically to suppress these.

---

## Tools Used

| Tool | Used For |
|------|----------|
| **Claude (Anthropic)** | In-product: dispatch narrative generation and grounded Q&A |
| **Gemini / Antigravity IDE** | Development assistant: code generation, debugging, architecture review |
| **MapLibre GL JS** | Map rendering (open-source, no API key required) |
| **Docker Compose** | Containerized deployment (PostgreSQL + backend + frontend) |
| **pytest** | Unit and integration testing |

