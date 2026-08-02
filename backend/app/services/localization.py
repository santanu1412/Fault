"""Fault localization engine — deterministic tree-walk boundary detection.

This module is the core of the system. It is:
- Deterministic (no ML, no LLM)
- Unit-testable (pure function: localize(pole_states, topology) -> List[Incident])
- Explainable (every decision is traceable to tree structure + pole state)

Algorithm:
1. For each DT tree, walk top-down from root
2. Find live/dark boundaries (parent energized, child dark_confirmed)
3. Collect dark subtree below each boundary
4. Apply special case rules (DT fault, feeder fault, sensor suspect, scheduled outage)
5. Score confidence based on topology source, device coverage, recency, RSSI
6. Dedup/merge overlapping incidents
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.services.topology_builder import DtTree, TreeNode

logger = logging.getLogger("fault_system.localization")


@dataclass
class BoundaryEdge:
    """An edge where a live parent meets a dark child — the fault boundary."""
    parent_pole_id: str
    child_pole_id: str
    parent_lat: float
    parent_lon: float
    child_lat: float
    child_lon: float
    edge_source: str  # surveyed or inferred
    edge_confidence: float


@dataclass
class DetectedIncident:
    """A detected fault with all information needed to create a ticket."""
    kind: str  # span, dt, feeder, sensor_only
    boundary_edges: list[BoundaryEdge]
    dark_pole_ids: list[str]
    dark_poles_with_no_device: list[str]
    centroid_lat: float
    centroid_lon: float
    dt_id: str
    feeder_id: str
    pincode: str | None
    households_affected: int
    confidence: float
    topology_basis: str  # surveyed, inferred, mixed
    confidence_breakdown: dict = field(default_factory=dict)


@dataclass
class PoleStateInfo:
    """Snapshot of a pole's current state for localization."""
    pole_id: str
    energized: bool
    classification: str  # ok, dark_confirmed, sensor_suspect
    confidence: float
    last_confirmed_at: datetime | None
    has_device: bool
    rssi: float | None = None


def _collect_dark_subtree(node: TreeNode, pole_states: dict[str, PoleStateInfo]) -> list[str]:
    """Recursively collect all dark pole IDs in a subtree."""
    dark_ids = []
    state = pole_states.get(node.pole_id)

    if state and state.classification == "dark_confirmed":
        dark_ids.append(node.pole_id)

    for child in node.children:
        dark_ids.extend(_collect_dark_subtree(child, pole_states))

    return dark_ids


def _has_any_live_descendant(node: TreeNode, pole_states: dict[str, PoleStateInfo]) -> bool:
    """Check if any descendant of this node is live (energized and confirmed)."""
    for child in node.children:
        child_state = pole_states.get(child.pole_id)
        if child_state and child_state.energized and child_state.classification == "ok":
            return True
        if _has_any_live_descendant(child, pole_states):
            return True
    return False


def _is_node_dark(node: TreeNode, pole_states: dict[str, PoleStateInfo]) -> bool:
    """Check if a node is confirmed dark."""
    state = pole_states.get(node.pole_id)
    if state is None:
        # No device — can't confirm
        return False
    return state.classification == "dark_confirmed"


def _is_node_live(node: TreeNode, pole_states: dict[str, PoleStateInfo]) -> bool:
    """Check if a node is confirmed live (or functionally live with power passing through)."""
    state = pole_states.get(node.pole_id)
    if state is None:
        # No device — assume live (conservative) unless overridden
        return True
    if state.energized and state.classification == "ok":
        return True
    # If dark but has live descendants, power is flowing through it (sensor failure)
    if _has_any_live_descendant(node, pole_states):
        return True
    return False


def _compute_confidence(
    boundary_edges: list[BoundaryEdge],
    dark_pole_ids: list[str],
    pole_states: dict[str, PoleStateInfo],
    topology_source: str,
) -> tuple[float, dict]:
    """Compute confidence score for an incident.

    Factors:
    - Topology source (surveyed vs inferred): 0.4 weight
    - % of boundary-adjacent poles with devices: 0.3 weight
    - Recency of last heartbeat at boundary: 0.2 weight
    - Average RSSI at boundary: 0.1 weight
    """
    # Factor 1: Topology source
    if topology_source == "surveyed":
        topo_score = 1.0
    elif topology_source == "inferred":
        # Average confidence of boundary edges
        if boundary_edges:
            topo_score = sum(e.edge_confidence for e in boundary_edges) / len(boundary_edges)
        else:
            topo_score = 0.5
    else:  # mixed
        topo_score = 0.7

    # Factor 2: Device coverage at boundary
    boundary_pole_ids = set()
    for edge in boundary_edges:
        boundary_pole_ids.add(edge.parent_pole_id)
        boundary_pole_ids.add(edge.child_pole_id)

    if boundary_pole_ids:
        has_device = sum(
            1 for pid in boundary_pole_ids
            if pole_states.get(pid) and pole_states[pid].has_device
        )
        device_score = has_device / len(boundary_pole_ids)
    else:
        device_score = 0.5

    # Factor 3: Recency
    now = datetime.now(timezone.utc)
    recency_scores = []
    for edge in boundary_edges:
        for pid in [edge.parent_pole_id, edge.child_pole_id]:
            state = pole_states.get(pid)
            if state and state.last_confirmed_at:
                age_minutes = (now - state.last_confirmed_at).total_seconds() / 60
                # Full confidence if < 5 min old, degrading to 0 at 60 min
                recency_scores.append(max(0, 1.0 - (age_minutes / 60)))

    recency_score = sum(recency_scores) / len(recency_scores) if recency_scores else 0.5

    # Factor 4: RSSI at boundary
    rssi_values = []
    for edge in boundary_edges:
        for pid in [edge.parent_pole_id, edge.child_pole_id]:
            state = pole_states.get(pid)
            if state and state.rssi is not None:
                # Normalize RSSI: -50 dBm = 1.0, -100 dBm = 0.0
                rssi_normalized = max(0, min(1, (state.rssi + 100) / 50))
                rssi_values.append(rssi_normalized)

    rssi_score = sum(rssi_values) / len(rssi_values) if rssi_values else 0.5

    # Weighted combination
    confidence = (
        0.4 * topo_score
        + 0.3 * device_score
        + 0.2 * recency_score
        + 0.1 * rssi_score
    )

    breakdown = {
        "topology": round(topo_score, 3),
        "device_coverage": round(device_score, 3),
        "recency": round(recency_score, 3),
        "rssi": round(rssi_score, 3),
        "overall": round(confidence, 3),
    }

    return round(confidence, 3), breakdown


def _determine_topology_basis(
    boundary_edges: list[BoundaryEdge],
    dark_pole_ids: list[str],
    tree: DtTree,
) -> str:
    """Determine if an incident's topology is surveyed, inferred, or mixed."""
    sources = set()
    for edge in boundary_edges:
        if edge.edge_source:
            sources.add(edge.edge_source)
    for pid in dark_pole_ids:
        node = tree.nodes.get(pid)
        if node and node.edge_source:
            sources.add(node.edge_source)

    if "surveyed" in sources and "inferred" in sources:
        return "mixed"
    elif "inferred" in sources:
        return "inferred"
    elif "surveyed" in sources:
        return "surveyed"
    return tree.topology_source


def localize_dt(
    tree: DtTree,
    pole_states: dict[str, PoleStateInfo],
    scheduled_outage_targets: set[str] | None = None,
) -> list[DetectedIncident]:
    """Localize faults within a single DT's tree.

    This is the core algorithm — a single top-down tree walk.

    Returns a list of detected incidents (may be 0, 1, or multiple for
    simultaneous faults on different branches).
    """
    if tree.root is None or not tree.root.children:
        return []

    if scheduled_outage_targets is None:
        scheduled_outage_targets = set()

    # Check if this DT is in a scheduled outage
    if tree.dt_id in scheduled_outage_targets:
        logger.debug(f"DT {tree.dt_id} in scheduled outage — skipping.")
        return []

    incidents = []

    # Special case: Check for DT-level fault
    # If the root's direct children are ALL dark, this is a DT-level fault
    root_children_states = []
    for child in tree.root.children:
        child_state = pole_states.get(child.pole_id)
        if child_state:
            root_children_states.append(child_state)

    if root_children_states and all(
        s.classification == "dark_confirmed" for s in root_children_states
    ):
        # All direct children dark — DT-level fault
        all_dark = _collect_dark_subtree(tree.root, pole_states)

        if all_dark:
            # Check if this is really a sensor issue (any live descendants at all?)
            # If even one deep descendant is live, some individual poles have dead sensors
            any_live = _has_any_live_descendant(tree.root, pole_states)

            if not any_live:
                # True DT-level fault
                boundary_edges = [
                    BoundaryEdge(
                        parent_pole_id=tree.root.pole_id,
                        child_pole_id=child.pole_id,
                        parent_lat=tree.root.lat,
                        parent_lon=tree.root.lon,
                        child_lat=child.lat,
                        child_lon=child.lon,
                        edge_source=child.edge_source,
                        edge_confidence=child.edge_confidence,
                    )
                    for child in tree.root.children
                ]
                # Compute centroid of dark subtree
                dark_nodes = [tree.nodes[pid] for pid in all_dark if pid in tree.nodes]
                if dark_nodes:
                    centroid_lat = sum(n.lat for n in dark_nodes) / len(dark_nodes)
                    centroid_lon = sum(n.lon for n in dark_nodes) / len(dark_nodes)
                else:
                    centroid_lat = tree.dt_lat
                    centroid_lon = tree.dt_lon

                # Find pincode from any pole in the dark set
                pincode = None
                for pid in all_dark:
                    state = pole_states.get(pid)
                    if state:
                        # We'll look up pincode from the pole registry in the caller
                        pass

                dark_no_device = [
                    pid for pid in all_dark
                    if pid in tree.nodes and tree.nodes[pid].device_id is None
                ]

                topo_basis = _determine_topology_basis(boundary_edges, all_dark, tree)
                confidence, breakdown = _compute_confidence(
                    boundary_edges, all_dark, pole_states, topo_basis
                )

                incidents.append(DetectedIncident(
                    kind="dt",
                    boundary_edges=boundary_edges,
                    dark_pole_ids=all_dark,
                    dark_poles_with_no_device=dark_no_device,
                    centroid_lat=centroid_lat,
                    centroid_lon=centroid_lon,
                    dt_id=tree.dt_id,
                    feeder_id=tree.feeder_id,
                    pincode=pincode,
                    households_affected=tree.households_served,
                    confidence=confidence,
                    topology_basis=topo_basis,
                    confidence_breakdown=breakdown,
                ))

                return incidents  # DT-level fault subsumes all span-level faults

    # Normal case: Walk the tree top-down looking for live→dark boundaries
    _walk_for_boundaries(tree.root, tree, pole_states, scheduled_outage_targets, incidents)

    return incidents


def _walk_for_boundaries(
    node: TreeNode,
    tree: DtTree,
    pole_states: dict[str, PoleStateInfo],
    scheduled_outage_targets: set[str],
    incidents: list[DetectedIncident],
) -> None:
    """Recursive top-down walk to find live/dark boundary edges."""
    for child in node.children:
        parent_live = _is_node_live(node, pole_states)
        child_dark = _is_node_dark(child, pole_states)

        if parent_live and child_dark:
            # Check for sensor-suspect case: dark pole with live children
            if _has_any_live_descendant(child, pole_states):
                # This pole is dark but has live descendants —
                # likely a sensor fault, not a line fault
                logger.debug(
                    f"Sensor suspect: {child.pole_id} dark but has live descendants."
                )
                # Continue walking to find real boundaries below
                _walk_for_boundaries(child, tree, pole_states, scheduled_outage_targets, incidents)
                continue

            # Check scheduled outage
            if child.pole_id in scheduled_outage_targets:
                continue

            # Found a fault boundary!
            boundary_edge = BoundaryEdge(
                parent_pole_id=node.pole_id,
                child_pole_id=child.pole_id,
                parent_lat=node.lat,
                parent_lon=node.lon,
                child_lat=child.lat,
                child_lon=child.lon,
                edge_source=child.edge_source,
                edge_confidence=child.edge_confidence,
            )

            # Collect all dark poles in the subtree below this boundary
            dark_subtree = _collect_dark_subtree(child, pole_states)

            if not dark_subtree:
                continue

            # Compute centroid of dark subtree
            dark_nodes = [tree.nodes[pid] for pid in dark_subtree if pid in tree.nodes]
            if dark_nodes:
                centroid_lat = sum(n.lat for n in dark_nodes) / len(dark_nodes)
                centroid_lon = sum(n.lon for n in dark_nodes) / len(dark_nodes)
            else:
                centroid_lat = child.lat
                centroid_lon = child.lon

            dark_no_device = [
                pid for pid in dark_subtree
                if pid in tree.nodes and tree.nodes[pid].device_id is None
            ]

            # Estimate households: proportional to fraction of DT's poles
            total_poles_in_dt = len(tree.nodes) - 1  # exclude ROOT
            if total_poles_in_dt > 0:
                fraction = len(dark_subtree) / total_poles_in_dt
                households = int(tree.households_served * fraction)
            else:
                households = 0

            topo_basis = _determine_topology_basis([boundary_edge], dark_subtree, tree)
            confidence, breakdown = _compute_confidence(
                [boundary_edge], dark_subtree, pole_states, topo_basis
            )

            incidents.append(DetectedIncident(
                kind="span",
                boundary_edges=[boundary_edge],
                dark_pole_ids=dark_subtree,
                dark_poles_with_no_device=dark_no_device,
                centroid_lat=centroid_lat,
                centroid_lon=centroid_lon,
                dt_id=tree.dt_id,
                feeder_id=tree.feeder_id,
                pincode=None,  # Will be resolved from pole registry
                households_affected=households,
                confidence=confidence,
                topology_basis=topo_basis,
                confidence_breakdown=breakdown,
            ))

        elif not child_dark:
            # Child is live — continue walking down to find boundaries deeper
            _walk_for_boundaries(child, tree, pole_states, scheduled_outage_targets, incidents)


def localize_feeder(
    feeder_id: str,
    dt_trees: dict[str, DtTree],
    pole_states: dict[str, PoleStateInfo],
    scheduled_outage_targets: set[str] | None = None,
) -> list[DetectedIncident]:
    """Check if an entire feeder is down (all DTs dark) — returns a single feeder-level incident."""
    feeder_dts = {
        dt_id: tree for dt_id, tree in dt_trees.items()
        if tree.feeder_id == feeder_id
    }

    if not feeder_dts:
        return []

    # Check if ALL DTs on this feeder have all-dark poles
    all_dts_dark = True
    all_dark_poles = []
    total_households = 0

    for dt_id, tree in feeder_dts.items():
        if tree.root is None:
            continue

        has_any_live = False
        for node in tree.nodes.values():
            if node.pole_id.startswith("ROOT-"):
                continue
            state = pole_states.get(node.pole_id)
            if state and state.energized and state.classification == "ok":
                has_any_live = True
                break

        if has_any_live:
            all_dts_dark = False
            break

        # Collect dark poles from this DT
        dt_dark = [
            pid for pid, state in pole_states.items()
            if state.classification == "dark_confirmed"
            and pid in tree.nodes
        ]
        all_dark_poles.extend(dt_dark)
        total_households += tree.households_served

    if not all_dts_dark or not all_dark_poles:
        return []

    # Feeder-level fault
    # Centroid = average of all DT locations
    feeder_trees = list(feeder_dts.values())
    centroid_lat = sum(t.dt_lat for t in feeder_trees) / len(feeder_trees)
    centroid_lon = sum(t.dt_lon for t in feeder_trees) / len(feeder_trees)

    confidence, breakdown = _compute_confidence(
        [],  # No specific boundary for feeder-level
        all_dark_poles,
        pole_states,
        "mixed",
    )

    return [DetectedIncident(
        kind="feeder",
        boundary_edges=[],
        dark_pole_ids=all_dark_poles,
        dark_poles_with_no_device=[],
        centroid_lat=centroid_lat,
        centroid_lon=centroid_lon,
        dt_id="",
        feeder_id=feeder_id,
        pincode=None,
        households_affected=total_households,
        confidence=confidence,
        topology_basis="mixed",
        confidence_breakdown=breakdown,
    )]


def localize_all(
    trees: dict[str, DtTree],
    pole_states: dict[str, PoleStateInfo],
    scheduled_outage_targets: set[str] | None = None,
) -> list[DetectedIncident]:
    """Run localization across all DT trees.

    This is the main entry point for the localization engine.
    """
    if scheduled_outage_targets is None:
        scheduled_outage_targets = set()

    all_incidents: list[DetectedIncident] = []

    # First, check for feeder-level faults
    feeder_ids = {tree.feeder_id for tree in trees.values()}
    feeder_faults = set()

    for feeder_id in feeder_ids:
        feeder_incidents = localize_feeder(
            feeder_id, trees, pole_states, scheduled_outage_targets
        )
        if feeder_incidents:
            all_incidents.extend(feeder_incidents)
            feeder_faults.add(feeder_id)

    # Then, for feeders NOT already identified as fully down,
    # run per-DT localization
    for dt_id, tree in trees.items():
        if tree.feeder_id in feeder_faults:
            continue  # Already covered by feeder-level fault

        dt_incidents = localize_dt(tree, pole_states, scheduled_outage_targets)
        all_incidents.extend(dt_incidents)

    logger.info(f"Localization found {len(all_incidents)} incidents.")
    return all_incidents
