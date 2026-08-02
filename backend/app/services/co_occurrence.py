"""Outage Co-Occurrence Topology Refinement Service.

Mines historical outage logs to detect electrically correlated pole pairs and refine
MST edge weights for un-surveyed branching topologies.

Math & Safeguards:
  - Overlap Coefficient: C(i, j) = joint_dark(i, j) / min(N_i, N_j)
  - Refined Weight: W_refined(i, j) = W_haversine(i, j) * (1.0 - ALPHA * C(i, j))
  - Pair Explosion Guard: Excludes bulk/substation outages (>250 dark poles).
  - Support & Confidence Gating: Minimum 5 joint incidents & 80% confidence threshold.
"""

from __future__ import annotations

import logging

from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.incident import Incident
from app.models.pole import Pole

logger = logging.getLogger("fault_system.co_occurrence")

ALPHA: float = 0.5                     # max 50% weight reduction
MIN_CONFIDENCE: float = 0.80           # co-occurrence confidence threshold
MIN_SUPPORT: int = 5                   # minimum joint dark incidents required
DEFAULT_LOOKBACK_DAYS: int = 540       # 18-month historical lookback window
MAX_INCIDENT_DARK_POLES: int = 250     # ignore bulk substation trips (>250 poles)


@dataclass(frozen=True)
class CoOccurrenceConfig:
    """Configuration parameters for topology refinement tuning."""

    alpha: float = ALPHA
    min_confidence: float = MIN_CONFIDENCE
    min_support: int = MIN_SUPPORT
    lookback_days: int = DEFAULT_LOOKBACK_DAYS
    max_incident_dark_poles: int = MAX_INCIDENT_DARK_POLES
    same_feeder_only: bool = True

    def validate(self) -> None:
        if not 0.0 <= self.alpha <= 1.0:
            raise ValueError("alpha must be in [0, 1]")
        if not 0.0 <= self.min_confidence <= 1.0:
            raise ValueError("min_confidence must be in [0, 1]")
        if self.min_support < 1:
            raise ValueError("min_support must be >= 1")


DEFAULT_CONFIG = CoOccurrenceConfig()


def pair_key(a: str, b: str) -> tuple[str, str]:
    """Return a canonical, order-independent tuple for an unordered pole pair."""
    return (a, b) if a <= b else (b, a)


@dataclass(slots=True, frozen=True)
class PairStats:
    """Statistical co-occurrence evidence for a pair of poles."""

    pole_a: str
    pole_b: str
    joint_incidents: int
    incidents_a: int
    incidents_b: int
    confidence: float

    @property
    def qualifies(self) -> bool:
        return (
            self.joint_incidents >= MIN_SUPPORT
            and self.confidence >= MIN_CONFIDENCE
        )


@dataclass(slots=True, frozen=True)
class WeightAdjustment:
    """Audit record for a refined MST topology edge."""

    pole_a: str
    pole_b: str
    original_weight: float
    refined_weight: float
    confidence: float
    joint_incidents: int


async def calculate_co_occurrence_matrix(
    session: AsyncSession,
    config: CoOccurrenceConfig = DEFAULT_CONFIG,
) -> dict[tuple[str, str], PairStats]:
    """Mine historical incident logs and return qualified co-occurring pole pairs.

    Filters out bulk substation trips to prevent pair explosion and feeder leakage.
    """
    config.validate()
    cutoff_dt = datetime.now(timezone.utc) - timedelta(days=config.lookback_days)

    # 1. Fetch historical incidents within the lookback window
    stmt = (
        select(Incident.dark_pole_ids)
        .where(Incident.created_at >= cutoff_dt)
    )
    result = await session.execute(stmt)
    rows = result.all()

    pole_incident_counts: dict[str, int] = {}
    pair_joint_counts: dict[tuple[str, str], int] = {}

    incidents_processed = 0
    incidents_skipped_bulk = 0

    # 2. Accumulate per-pole and joint-pair dark occurrence frequencies
    for row in rows:
        dark_ids: list[str] = row[0] or []
        num_dark = len(dark_ids)

        if num_dark == 0:
            continue

        # Pair Explosion Guard: Ignore bulk substation-wide outages
        if num_dark > config.max_incident_dark_poles:
            incidents_skipped_bulk += 1
            continue

        incidents_processed += 1
        unique_poles = sorted(set(dark_ids))

        # Update per-pole incident counts
        for pid in unique_poles:
            pole_incident_counts[pid] = pole_incident_counts.get(pid, 0) + 1

        # Update pairwise joint counts (sub-quad absolute upper bound: max 250 poles)
        for i in range(len(unique_poles)):
            p1 = unique_poles[i]
            for j in range(i + 1, len(unique_poles)):
                p2 = unique_poles[j]
                pk = pair_key(p1, p2)
                pair_joint_counts[pk] = pair_joint_counts.get(pk, 0) + 1

    logger.info(
        f"Co-occurrence analysis: {incidents_processed} incidents processed, "
        f"{incidents_skipped_bulk} bulk outages skipped, "
        f"{len(pair_joint_counts)} unique candidate pairs evaluated."
    )

    # 3. Compute Szymkiewicz-Simpson confidence score per pair
    matrix: dict[tuple[str, str], PairStats] = {}

    for (p1, p2), joint_cnt in pair_joint_counts.items():
        if joint_cnt < config.min_support:
            continue

        n_a = pole_incident_counts.get(p1, joint_cnt)
        n_b = pole_incident_counts.get(p2, joint_cnt)
        denominator = min(n_a, n_b)

        confidence = joint_cnt / denominator if denominator > 0 else 0.0
        confidence = min(1.0, confidence)  # Clamp to [0, 1]

        stats = PairStats(
            pole_a=p1,
            pole_b=p2,
            joint_incidents=joint_cnt,
            incidents_a=n_a,
            incidents_b=n_b,
            confidence=confidence,
        )

        if stats.qualifies:
            matrix[pair_key(p1, p2)] = stats

    logger.info(f"Qualified {len(matrix)} topology refinement pole pairs.")
    return matrix


def refine_edge_weights(
    edges: list[tuple[str, str, float]],
    matrix: dict[tuple[str, str], PairStats],
    alpha: float = ALPHA,
) -> tuple[list[tuple[str, str, float]], list[WeightAdjustment]]:
    """Bias MST edge weights using the historical co-occurrence matrix.

    Returns refined edge list along with audit adjustment records.
    """
    refined_edges: list[tuple[str, str, float]] = []
    adjustments: list[WeightAdjustment] = []

    for u, v, weight in edges:
        pk = pair_key(u, v)
        pair_stats = matrix.get(pk)

        if pair_stats and pair_stats.qualifies:
            # W_refined = W_haversine * (1.0 - alpha * confidence)
            reduction_factor = 1.0 - (alpha * pair_stats.confidence)
            new_weight = weight * reduction_factor

            refined_edges.append((u, v, new_weight))
            adjustments.append(
                WeightAdjustment(
                    pole_a=u,
                    pole_b=v,
                    original_weight=weight,
                    refined_weight=new_weight,
                    confidence=pair_stats.confidence,
                    joint_incidents=pair_stats.joint_incidents,
                )
            )
        else:
            refined_edges.append((u, v, weight))

    return refined_edges, adjustments
