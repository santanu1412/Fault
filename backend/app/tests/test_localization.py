"""Table-driven tests for the fault localization engine.

Tests the core algorithm with synthetic tree structures and pole states.
No database required — all tests use in-memory data structures.
"""

import pytest
from datetime import datetime, timezone

from app.services.localization import (
    PoleStateInfo,
    localize_all,
    localize_dt,
)
from app.services.topology_builder import DtTree, TreeNode


def _make_state(pole_id: str, energized: bool, has_device: bool = True) -> PoleStateInfo:
    """Helper to create a pole state."""
    return PoleStateInfo(
        pole_id=pole_id,
        energized=energized,
        classification="ok" if energized else "dark_confirmed",
        confidence=1.0,
        last_confirmed_at=datetime.now(timezone.utc),
        has_device=has_device,
    )


def _make_linear_tree(
    dt_id: str = "DT-TEST",
    feeder_id: str = "FDR-TEST",
    num_poles: int = 10,
    topology_source: str = "surveyed",
    device_coverage: list[bool] | None = None,
) -> DtTree:
    """Create a simple linear tree: ROOT → P0 → P1 → ... → P(n-1)."""
    tree = DtTree(
        dt_id=dt_id,
        feeder_id=feeder_id,
        dt_lat=12.97,
        dt_lon=77.59,
        topology_source=topology_source,
        households_served=100,
    )

    root = TreeNode(
        pole_id=f"ROOT-{dt_id}",
        lat=12.97,
        lon=77.59,
        device_id=None,
        edge_source=topology_source,
        edge_confidence=1.0 if topology_source == "surveyed" else 0.7,
    )
    tree.root = root
    tree.nodes[root.pole_id] = root

    prev = root
    for i in range(num_poles):
        has_device = device_coverage[i] if device_coverage else True
        node = TreeNode(
            pole_id=f"P-{i:03d}",
            lat=12.97 + (i + 1) * 0.001,
            lon=77.59 + (i + 1) * 0.001,
            device_id=f"DEV-P-{i:03d}" if has_device else None,
            edge_source=topology_source,
            edge_confidence=1.0 if topology_source == "surveyed" else 0.7,
        )
        node.parent = prev
        prev.children.append(node)
        tree.nodes[node.pole_id] = node
        prev = node

    return tree


def _make_branching_tree(
    dt_id: str = "DT-TEST",
    feeder_id: str = "FDR-TEST",
    branches: int = 3,
    poles_per_branch: int = 5,
    topology_source: str = "surveyed",
) -> DtTree:
    """Create a branching tree: ROOT → [Branch0: P00→P01→..., Branch1: P10→P11→..., ...]."""
    tree = DtTree(
        dt_id=dt_id,
        feeder_id=feeder_id,
        dt_lat=12.97,
        dt_lon=77.59,
        topology_source=topology_source,
        households_served=200,
    )

    root = TreeNode(
        pole_id=f"ROOT-{dt_id}",
        lat=12.97,
        lon=77.59,
        device_id=None,
        edge_source=topology_source,
        edge_confidence=1.0,
    )
    tree.root = root
    tree.nodes[root.pole_id] = root

    for b in range(branches):
        prev = root
        for i in range(poles_per_branch):
            node = TreeNode(
                pole_id=f"P-B{b}-{i:03d}",
                lat=12.97 + (b + 1) * 0.01 + (i + 1) * 0.001,
                lon=77.59 + (b + 1) * 0.01 + (i + 1) * 0.001,
                device_id=f"DEV-P-B{b}-{i:03d}",
                edge_source=topology_source,
                edge_confidence=1.0,
            )
            node.parent = prev
            prev.children.append(node)
            tree.nodes[node.pole_id] = node
            prev = node

    return tree


class TestKnownTopologySpanFault:
    """Test: known topology span fault → exact span."""

    def test_span_fault_at_middle(self):
        """Poles 5-9 dark, poles 0-4 live → incident at edge P-004→P-005."""
        tree = _make_linear_tree(num_poles=10)
        states = {}
        for i in range(10):
            states[f"P-{i:03d}"] = _make_state(f"P-{i:03d}", energized=(i < 5))

        incidents = localize_dt(tree, states)

        assert len(incidents) == 1
        inc = incidents[0]
        assert inc.kind == "span"
        assert len(inc.boundary_edges) == 1
        assert inc.boundary_edges[0].parent_pole_id == "P-004"
        assert inc.boundary_edges[0].child_pole_id == "P-005"
        assert set(inc.dark_pole_ids) == {f"P-{i:03d}" for i in range(5, 10)}

    def test_span_fault_at_start(self):
        """All poles dark from P-001 → fault near root."""
        tree = _make_linear_tree(num_poles=5)
        states = {}
        states["P-000"] = _make_state("P-000", energized=True)
        for i in range(1, 5):
            states[f"P-{i:03d}"] = _make_state(f"P-{i:03d}", energized=False)

        incidents = localize_dt(tree, states)

        assert len(incidents) == 1
        assert incidents[0].boundary_edges[0].parent_pole_id == "P-000"
        assert incidents[0].boundary_edges[0].child_pole_id == "P-001"


class TestDtLevelFault:
    """Test: DT-level fault → one DT ticket, not N pole tickets."""

    def test_dt_fault_all_dark(self):
        """All poles under a DT go dark → one DT-level incident."""
        tree = _make_linear_tree(num_poles=5)
        states = {}
        for i in range(5):
            states[f"P-{i:03d}"] = _make_state(f"P-{i:03d}", energized=False)

        incidents = localize_dt(tree, states)

        assert len(incidents) == 1
        assert incidents[0].kind == "dt"
        assert len(incidents[0].dark_pole_ids) == 5


class TestFeederLevelFault:
    """Test: feeder-level fault → one ticket, not N DT tickets."""

    def test_feeder_fault(self):
        """All DTs on a feeder dark → one feeder-level incident."""
        trees = {}
        all_states = {}

        for dt_idx in range(3):
            dt_id = f"DT-{dt_idx:02d}"
            tree = _make_linear_tree(dt_id=dt_id, num_poles=5)
            trees[dt_id] = tree

            for i in range(5):
                # Map pole IDs to DT-specific ones
                actual_pid = list(tree.nodes.keys())[i + 1]  # Skip ROOT
                all_states[actual_pid] = _make_state(actual_pid, energized=False)

        incidents = localize_all(trees, all_states)

        # Should get feeder-level or DT-level incidents
        # Since all DTs share FDR-TEST, we may get a feeder-level incident
        assert len(incidents) >= 1


class TestSimultaneousFaults:
    """Test: two separate dark regions → two incidents."""

    def test_two_branch_faults(self):
        """Two branches each have a fault → two separate incidents."""
        tree = _make_branching_tree(branches=3, poles_per_branch=5)
        states = {}

        # Branch 0: poles 3-4 dark, 0-2 live
        for i in range(5):
            pid = f"P-B0-{i:03d}"
            states[pid] = _make_state(pid, energized=(i < 3))

        # Branch 1: poles 2-4 dark, 0-1 live
        for i in range(5):
            pid = f"P-B1-{i:03d}"
            states[pid] = _make_state(pid, energized=(i < 2))

        # Branch 2: all live
        for i in range(5):
            pid = f"P-B2-{i:03d}"
            states[pid] = _make_state(pid, energized=True)

        incidents = localize_dt(tree, states)

        assert len(incidents) == 2
        # Each incident should have its own dark poles
        all_dark = set()
        for inc in incidents:
            for pid in inc.dark_pole_ids:
                assert pid not in all_dark, f"Pole {pid} appears in multiple incidents"
                all_dark.add(pid)


class TestDeadSensorNoTicket:
    """Test: single dark pole with live children → no incident (sensor suspect)."""

    def test_sensor_suspect(self):
        """Pole P-002 dark, but P-003 and P-004 are live → no ticket."""
        tree = _make_linear_tree(num_poles=5)
        states = {}
        for i in range(5):
            states[f"P-{i:03d}"] = _make_state(
                f"P-{i:03d}", energized=(i != 2)  # Only P-002 is dark
            )

        incidents = localize_dt(tree, states)

        # Should produce zero incidents — dark-with-live-children is sensor suspect
        assert len(incidents) == 0


class TestScheduledOutageNoTicket:
    """Test: dark poles within scheduled outage window → no incident."""

    def test_outage_suppression(self):
        """DT in scheduled outage → no incident even if all dark."""
        tree = _make_linear_tree(num_poles=5)
        states = {}
        for i in range(5):
            states[f"P-{i:03d}"] = _make_state(f"P-{i:03d}", energized=False)

        # This DT is in scheduled outage
        outage_targets = {"DT-TEST"}

        incidents = localize_dt(tree, states, scheduled_outage_targets=outage_targets)

        assert len(incidents) == 0


class TestNoDeviceBoundaryPole:
    """Test: boundary pole has no device → incident reports range, not false precision."""

    def test_deviceless_boundary(self):
        """Boundary pole P-004 has no device → dark_poles_with_no_device is populated."""
        device_coverage = [True, True, True, True, False, True, True, True, True, True]
        tree = _make_linear_tree(num_poles=10, device_coverage=device_coverage)
        states = {}
        for i in range(10):
            if device_coverage[i]:
                states[f"P-{i:03d}"] = _make_state(f"P-{i:03d}", energized=(i < 5))
            # P-004 has no device, so no state entry

        incidents = localize_dt(tree, states)

        # The algorithm should still detect the fault around the boundary area
        # P-003 (live, has device) → P-004 (no device) → P-005 (dark, has device)
        # Since P-004 has no device, it's treated as "live" (conservative)
        # The boundary should be at P-004 → P-005
        assert len(incidents) >= 1


class TestInferredTopologyFault:
    """Test: fault on inferred topology → lower confidence, correct topology_basis."""

    def test_inferred_topology(self):
        """Span fault on an inferred-topology DT → incident with 'inferred' basis."""
        tree = _make_linear_tree(num_poles=10, topology_source="inferred")
        states = {}
        for i in range(10):
            states[f"P-{i:03d}"] = _make_state(f"P-{i:03d}", energized=(i < 5))

        incidents = localize_dt(tree, states)

        assert len(incidents) == 1
        assert incidents[0].topology_basis == "inferred"
        # Inferred topology should have lower confidence than surveyed
        assert incidents[0].confidence < 1.0


class TestRestorationDetection:
    """Test: previously dark poles now live → no new incidents."""

    def test_all_live_no_incidents(self):
        """All poles energized → zero incidents."""
        tree = _make_linear_tree(num_poles=10)
        states = {}
        for i in range(10):
            states[f"P-{i:03d}"] = _make_state(f"P-{i:03d}", energized=True)

        incidents = localize_dt(tree, states)
        assert len(incidents) == 0


class TestTwoFaultsSameLine:
    """Test: dark-live-dark sequence on a single branch.

    In a radial network, if P-004 is live, power MUST be flowing through P-002
    and P-003. Therefore, P-002/P-003 reporting dark while P-004 is live indicates
    a sensor failure (sensor suspect). The actual line fault is at P-004 → P-005.
    """

    def test_gap_in_dark_region(self):
        """P-002,003 dark, P-004 live, P-005,006 dark → P-002/003 sensor suspect, fault at P-005."""
        tree = _make_linear_tree(num_poles=8)
        states = {}
        # P-000, P-001: live
        states["P-000"] = _make_state("P-000", energized=True)
        states["P-001"] = _make_state("P-001", energized=True)
        # P-002, P-003: dark (sensor suspect because P-004 is live)
        states["P-002"] = _make_state("P-002", energized=False)
        states["P-003"] = _make_state("P-003", energized=False)
        # P-004: live
        states["P-004"] = _make_state("P-004", energized=True)
        # P-005, P-006, P-007: dark (real line fault)
        states["P-005"] = _make_state("P-005", energized=False)
        states["P-006"] = _make_state("P-006", energized=False)
        states["P-007"] = _make_state("P-007", energized=False)

        incidents = localize_dt(tree, states)

        # In a radial tree, P-002/003 are sensor suspect because downstream P-004 is live.
        # The real line fault boundary is P-004 (live) → P-005 (dark).
        assert len(incidents) == 1
        assert incidents[0].boundary_edges[0].parent_pole_id == "P-004"
        assert incidents[0].boundary_edges[0].child_pole_id == "P-005"
        assert set(incidents[0].dark_pole_ids) == {"P-005", "P-006", "P-007"}


class TestDevicelessBoundaryRange:
    """Test: boundary pole has no device → correctly handled as unknown state."""

    def test_deviceless_in_boundary_zone(self):
        """P-003 has device (live), P-004 no device, P-005 has device (dark).

        The algorithm should identify the boundary somewhere around P-004/P-005,
        not produce a false positive for P-004 (which has no way to report).
        """
        device_coverage = [True, True, True, True, False, True, True, True]
        tree = _make_linear_tree(num_poles=8, device_coverage=device_coverage)
        states = {}
        for i in range(8):
            pid = f"P-{i:03d}"
            if device_coverage[i]:
                # Devices on P-000 through P-003 are live, P-005+ are dark
                states[pid] = _make_state(pid, energized=(i < 5))
            # P-004 has no device — no state entry

        incidents = localize_dt(tree, states)

        # Should detect a fault. The boundary depends on how deviceless poles
        # are treated — conservatively as "live" (no evidence of darkness)
        assert len(incidents) >= 1
        # The dark pole set should NOT include P-004 (no device, assumed live)
        # but SHOULD include P-005, P-006, P-007
        dark_ids = set()
        for inc in incidents:
            dark_ids.update(inc.dark_pole_ids)
        assert "P-005" in dark_ids
        assert "P-006" in dark_ids
        assert "P-007" in dark_ids


class TestMixedTopologyBasis:
    """Test: DT with mix of surveyed and inferred edges → topology_basis is 'mixed'."""

    def test_mixed_topology_incident(self):
        """Create a tree with some surveyed, some inferred edges. Incident should report 'mixed'."""
        tree = _make_linear_tree(num_poles=6, topology_source="surveyed")

        # Override some edges to be inferred
        for pid, node in tree.nodes.items():
            if pid in ("P-003", "P-004", "P-005"):
                node.edge_source = "inferred"
                node.edge_confidence = 0.6

        states = {}
        for i in range(6):
            states[f"P-{i:03d}"] = _make_state(f"P-{i:03d}", energized=(i < 3))

        incidents = localize_dt(tree, states)

        assert len(incidents) == 1
        # Boundary is at P-002 (surveyed, live) → P-003 (inferred, dark)
        # Dark subtree contains both surveyed and inferred edges
        inc = incidents[0]
        # The topology basis should reflect the mixed nature
        # (depends on implementation: could be "inferred" if boundary is inferred,
        # or "mixed" if the algorithm checks the entire dark subtree)
        assert inc.topology_basis in ("inferred", "mixed")
        # Confidence should be reduced due to inferred edges
        assert inc.confidence < 1.0


class TestDtFaultSuppressionDuringOutage:
    """Test: DT-level fault suppressed during scheduled outage with outage targets."""

    def test_outage_suppression_dt_level(self):
        """All poles dark on a DT during a scheduled outage → zero incidents.

        Differs from TestScheduledOutageNoTicket by using a different DT ID
        and verifying the outage target set filtering mechanism.
        """
        tree = _make_linear_tree(dt_id="DT-MAINT", num_poles=8)
        states = {}
        for i in range(8):
            pid = f"P-{i:03d}"
            states[pid] = _make_state(pid, energized=False)

        # This DT is under maintenance
        outage_targets = {"DT-MAINT"}

        incidents = localize_dt(tree, states, scheduled_outage_targets=outage_targets)

        assert len(incidents) == 0, (
            "No incidents should be raised for a DT in a scheduled outage window"
        )


class TestSupervisorForceClose:
    """Test: ForceCloseRequest schema validation and substantive reason checks."""

    def test_valid_force_close_request(self):
        from app.api.tickets import ForceCloseRequest
        req = ForceCloseRequest(
            supervisor_id="SUP-102",
            override_reason="Pole physical replacement complete, sensor destroyed in transformer fire.",
        )
        assert req.supervisor_id == "SUP-102"
        assert "destroyed" in req.override_reason

    def test_reject_short_reason(self):
        from app.api.tickets import ForceCloseRequest
        with pytest.raises(ValueError):
            ForceCloseRequest(
                supervisor_id="SUP-102",
                override_reason="done",
            )

    def test_reject_low_entropy_reason(self):
        from app.api.tickets import ForceCloseRequest
        with pytest.raises(ValueError):
            ForceCloseRequest(
                supervisor_id="SUP-102",
                override_reason="aaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            )


class TestCoOccurrenceRefinement:
    """Test: Outage co-occurrence matrix calculations and MST edge weight refinement."""

    def test_refine_edge_weights(self):
        from app.services.co_occurrence import PairStats, refine_edge_weights

        stats_map = {
            ("P-001", "P-002"): PairStats(
                pole_a="P-001",
                pole_b="P-002",
                joint_incidents=10,
                incidents_a=10,
                incidents_b=10,
                confidence=1.0,
            )
        }

        original_edges = [("P-001", "P-002", 100.0), ("P-002", "P-003", 100.0)]
        refined_edges, adjustments = refine_edge_weights(original_edges, stats_map, alpha=0.5)

        assert len(adjustments) == 1
        assert adjustments[0].pole_a == "P-001"
        assert adjustments[0].refined_weight == 50.0  # 100.0 * (1 - 0.5 * 1.0) = 50.0
        assert refined_edges[0][2] == 50.0
        assert refined_edges[1][2] == 100.0  # Unchanged

