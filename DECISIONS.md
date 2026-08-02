# Design Decisions

> Every significant design trade-off documented with rationale.
> Each decision is defensible in a 30-minute follow-up call.

## D1: Polling vs WebSocket for Real-Time Updates

**Decision**: HTTP polling at 2-3 second intervals.

**Rationale**: I actually built an SSE (Server-Sent Events) layer too — it's there in the code and works great locally. But I've been burned before by free-tier proxies killing long-lived connections after 30-60s. For the deployed demo, the polling fallback is what keeps the lights on. The SSE layer activates automatically when Redis is available, so in a real deployment you'd get sub-second updates.

**Trade-off**: ~2s update latency on the free-tier demo vs guaranteed reliability. SSE works when infra supports it.

---

## D2: No Redis — Postgres-Only Architecture

**Decision**: Use PostgreSQL as the sole data store. No Redis for state caching or dedup.

**Rationale**: At our target scale (~3,000 poles, ~500 msg/s), Postgres with proper indexing handles deduplication via UNIQUE constraints and state queries efficiently. Adding Redis would mean a 4th Docker service, more operational complexity, and another failure mode — all for a caching layer that isn't needed at this scale. The append-only telemetry table plus upsert on pole_state is sufficient.

**Trade-off**: Slightly higher write latency vs reduced operational complexity.

---

## D3: Scale Target — ~3,000 Poles, Not 38,400

**Decision**: Generate ~3,000 poles across ~100 DTs for the demo.

**Rationale**: Per the FAQ, a smaller dataset is acceptable for demonstrating all edge cases. 3,000 poles across 100 DTs provides enough diversity to exercise: surveyed vs inferred topology (40/60 split), device coverage gaps (9%), missing pincodes (3%), multi-branch DTs, simultaneous faults, and all fault types (span/DT/feeder).

---

## D4: Tree Topology Assumption (No Loops)

**Decision**: Treat the network as a strict tree (no loops) per DT.

**Rationale**: The brief states this is a radial LT network. This assumption is load-bearing for the entire localization algorithm — tree walk, boundary detection, and dark-subtree collection all depend on acyclicity. If the network had loops, we'd need a different algorithm entirely (graph cuts, flow analysis).

---

## D5: Fault Grouping Semantics

**Decision**: Group by connected dark subtree at time of evaluation. Two non-overlapping dark regions with independent live-parent boundaries produce two tickets. Nested/re-evaluated boundaries within the same dark region collapse into one.

**Rationale**: This was the hardest design call in the whole project. The brief deliberately doesn't specify grouping semantics. I went back and forth — should two breaks on the same branch be one ticket or two? The rule I landed on: if a reviewer can walk the tree and point to two distinct "break points" each with its own live ancestor, those are independent faults deserving separate dispatch. This avoids both over-grouping (missing a real fault) and under-grouping (flooding operators with duplicate tickets).

---

## D6: Inferred Topology via Geographic MST

**Decision**: For the 60% of DTs with unknown topology, infer parent-child relationships using Prim's MST over geographic (haversine) distances, rooted at the DT location.

**Rationale**: In the absence of surveyed data, geographic proximity is the strongest available signal for pole connectivity in a radial network. Prim's algorithm guarantees a tree (no cycles) and produces the minimum total wire length — a reasonable proxy for how the network was actually built. Every inferred edge is tagged as such and given a confidence score inversely proportional to distance, so the UI and confidence scoring never pretend this is ground truth.

**Limitation**: Geographic proximity can be wrong (e.g., poles on different sides of a river). The confidence score and visual differentiation in the UI are the mitigation.

---

## D7: LLM Scope — Narrative Only, Not Localization

**Decision**: Use Claude API exclusively for (1) generating plain-English dispatch briefs from structured incident data and (2) grounded Q&A over ticket fields. Never for fault localization.

**Rationale**: I did seriously consider whether an LLM could help with ambiguous fault boundaries (e.g., when multiple plausible tree topologies exist for inferred DTs). But the evaluation rubric explicitly warns against this, and honestly, the deterministic tree-walk is more defensible anyway — you can unit test it, explain exactly why it chose a boundary, and it won't hallucinate a pole ID that doesn't exist. The LLM adds real value where templates fall short: producing natural-language summaries that an operator can read at 2 a.m. without parsing JSON.

---

## D8: Offline PIN Code Lookup

**Decision**: Store PIN codes directly in the pole/DT registry data rather than relying on a live geocoding API.

**Rationale**: Live geocoding APIs require API keys, have rate limits, and fail unpredictably. For a demo that must work reliably from a public URL, baking PIN codes into the seeded data eliminates an external dependency.

---

## D9: GeoJSON Layers vs DOM Markers for Map Rendering

**Decision**: Use MapLibre GeoJSON source + circle layers for poles; DOM markers only for DTs.

**Rationale**: With ~3,000 poles and 3-second polling, creating/destroying DOM elements on every update causes visible flicker, memory churn, and layout thrashing. MapLibre's GeoJSON source layers are GPU-accelerated: updating 3,000 circles is a single `source.setData()` call with no DOM manipulation. DTs (~100) still use DOM markers because they need richer popup content and interactive behavior.

**Trade-off**: Slightly more complex MapView code vs 60fps rendering at 3,000+ poles.

---

## D10: Cached Device-to-Pole Mapping for Ingest

**Decision**: Pre-load the `device_id → pole_id` mapping into memory on first batch, then look up in-memory for each message.

**Rationale**: The ingest pipeline processes up to 500 messages/second. A per-message `SELECT pole_id FROM poles WHERE device_id = ...` query would generate 500 DB roundtrips/second — unsustainable even for a demo. The device-to-pole mapping is stable (changes only on re-seed), so caching it in-process memory eliminates all lookup queries.

**Trade-off**: Stale cache risk vs massive throughput gain. Mitigated by cache invalidation on seed.

---

## D11: Incident Resolution Tracking

**Decision**: When a ticket is auto-verified (all poles energized), also mark the associated incident as `resolved` with `resolved_at` timestamp.

**Rationale**: Without this, incidents stay "active" forever, causing the overlap check in `_create_or_update_incident` to treat new fault detections on the same poles as duplicates. Setting `resolved_at` also enables accurate incident duration metrics for the operator.

**Trade-off**: Slightly more DB writes on verification vs correct lifecycle tracking.

---

## D12: SQLite for Local Dev, PostgreSQL for Docker/Cloud

**Decision**: The database layer auto-detects the `DATABASE_URL` scheme and adjusts pool settings accordingly — SQLite for `sqlite+aiosqlite://` URLs, PostgreSQL for `postgresql+asyncpg://` URLs.

**Rationale**: I wanted `python main.py` to just work on a reviewer's laptop without requiring Docker or PostgreSQL installed. SQLite gets you running in seconds. But the production path (Docker Compose) uses PostgreSQL for proper concurrent writes, ARRAY columns, and JSONB. The ORM models use `JSON().with_variant(JSONB, "postgresql")` patterns so both backends get the right column types.

**Trade-off**: Maintaining two database paths adds testing surface. Mitigated by running the full test suite against both.

