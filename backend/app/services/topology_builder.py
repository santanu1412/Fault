"""Topology builder — constructs tree structures per DT.

For DTs with known topology (40%): uses parent_pole_id directly.
For DTs with unknown topology (60%): infers tree via Prim's MST over haversine distances.
"""

import heapq
import logging
import math
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pole import Pole
from app.models.topology import TopologyEdge
from app.models.transformer import Transformer

logger = logging.getLogger("fault_system.topology")


@dataclass
class TreeNode:
    """A node in the DT pole tree."""
    pole_id: str
    lat: float
    lon: float
    device_id: str | None
    children: list["TreeNode"] = field(default_factory=list)
    parent: "TreeNode | None" = None
    edge_source: str = "unknown"  # surveyed or inferred
    edge_confidence: float = 0.0


@dataclass
class DtTree:
    """Complete tree structure for a single DT."""
    dt_id: str
    feeder_id: str
    dt_lat: float
    dt_lon: float
    root: TreeNode | None = None
    nodes: dict[str, TreeNode] = field(default_factory=dict)
    topology_source: str = "unknown"  # surveyed, inferred, or mixed
    households_served: int = 0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate haversine distance in km between two points."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def build_tree_from_edges(
    dt_id: str,
    dt_lat: float,
    dt_lon: float,
    feeder_id: str,
    households: int,
    poles: list[dict],
    edges: list[dict],
) -> DtTree:
    """Build a DT tree from surveyed parent-child edges."""
    tree = DtTree(
        dt_id=dt_id,
        feeder_id=feeder_id,
        dt_lat=dt_lat,
        dt_lon=dt_lon,
        topology_source="surveyed",
        households_served=households,
    )

    # Create tree nodes for all poles
    for p in poles:
        node = TreeNode(
            pole_id=p["pole_id"],
            lat=p["lat"],
            lon=p["lon"],
            device_id=p.get("device_id"),
            edge_source="surveyed",
            edge_confidence=1.0,
        )
        tree.nodes[p["pole_id"]] = node

    # Create virtual root node for the DT
    root = TreeNode(
        pole_id=f"ROOT-{dt_id}",
        lat=dt_lat,
        lon=dt_lon,
        device_id=None,  # DT itself doesn't have a pole device
        edge_source="surveyed",
        edge_confidence=1.0,
    )
    tree.root = root
    tree.nodes[root.pole_id] = root

    # Build parent-child relationships from edges
    for edge in edges:
        child_id = edge["child_pole_id"]
        parent_id = edge["parent_pole_id"]

        child = tree.nodes.get(child_id)
        parent = tree.nodes.get(parent_id)

        if child and parent:
            child.parent = parent
            parent.children.append(child)

    # Attach orphan poles (those with parent_pole_id = ROOT-*) to root
    for node in tree.nodes.values():
        if node.parent is None and node is not root:
            node.parent = root
            root.children.append(node)

    return tree


def build_tree_from_mst(
    dt_id: str,
    dt_lat: float,
    dt_lon: float,
    feeder_id: str,
    households: int,
    poles: list[dict],
) -> tuple[DtTree, list[dict]]:
    """Build a DT tree using Prim's MST over haversine distances.

    Returns (tree, inferred_edges) where inferred_edges can be persisted.
    """
    tree = DtTree(
        dt_id=dt_id,
        feeder_id=feeder_id,
        dt_lat=dt_lat,
        dt_lon=dt_lon,
        topology_source="inferred",
        households_served=households,
    )

    if not poles:
        return tree, []

    # Create virtual root at DT location
    root = TreeNode(
        pole_id=f"ROOT-{dt_id}",
        lat=dt_lat,
        lon=dt_lon,
        device_id=None,
        edge_source="inferred",
        edge_confidence=1.0,
    )
    tree.root = root
    tree.nodes[root.pole_id] = root

    # Create nodes for all poles
    pole_nodes = {}
    for p in poles:
        node = TreeNode(
            pole_id=p["pole_id"],
            lat=p["lat"],
            lon=p["lon"],
            device_id=p.get("device_id"),
        )
        tree.nodes[p["pole_id"]] = node
        pole_nodes[p["pole_id"]] = node

    # Prim's MST: start from root, grow tree by always adding nearest unvisited pole
    in_tree = {root.pole_id}
    # Priority queue: (distance, parent_pole_id, child_pole_id)
    pq: list[tuple[float, str, str]] = []

    # Initialize: distances from root to all poles
    for pid, pnode in pole_nodes.items():
        dist = haversine_km(root.lat, root.lon, pnode.lat, pnode.lon)
        heapq.heappush(pq, (dist, root.pole_id, pid))

    inferred_edges = []
    max_edge_km = 0.5  # Maximum reasonable edge length for confidence scoring

    while pq:
        dist, parent_id, child_id = heapq.heappop(pq)

        if child_id in in_tree:
            continue

        in_tree.add(child_id)

        # Link child to parent
        child_node = tree.nodes[child_id]
        parent_node = tree.nodes[parent_id]

        # Confidence: inversely proportional to distance, capped at 0.9
        confidence = min(0.9, max(0.3, 1.0 - (dist / max_edge_km)))

        child_node.parent = parent_node
        child_node.edge_source = "inferred"
        child_node.edge_confidence = confidence
        parent_node.children.append(child_node)

        inferred_edges.append({
            "child_pole_id": child_id,
            "parent_pole_id": parent_id,
            "dt_id": dt_id,
            "source": "inferred",
            "inferred_confidence": round(confidence, 3),
        })

        # Add edges from this new node to all unvisited poles
        for pid, pnode in pole_nodes.items():
            if pid not in in_tree:
                d = haversine_km(child_node.lat, child_node.lon, pnode.lat, pnode.lon)
                heapq.heappush(pq, (d, child_id, pid))

    return tree, inferred_edges


async def build_all_trees(session: AsyncSession) -> dict[str, DtTree]:
    """Build topology trees for all DTs in the database.

    Uses surveyed edges where available, MST inference where not.
    Persists inferred edges to topology_edges table.
    """
    trees = {}

    # Load all transformers
    result = await session.execute(select(Transformer))
    transformers = result.scalars().all()

    for dt in transformers:
        # Load poles for this DT
        result = await session.execute(
            select(
                Pole.pole_id,
                Pole.lat,
                Pole.lon,
                Pole.device_id,
                Pole.parent_pole_id,
                Pole.seq_on_line,
            ).where(Pole.dt_id == dt.dt_id)
        )
        poles = [
            {
                "pole_id": r.pole_id,
                "lat": r.lat,
                "lon": r.lon,
                "device_id": r.device_id,
                "parent_pole_id": r.parent_pole_id,
                "seq_on_line": r.seq_on_line,
            }
            for r in result.all()
        ]

        if not poles:
            continue

        # Check if this DT has surveyed topology
        has_topology = any(p["parent_pole_id"] is not None for p in poles)

        if has_topology:
            # Load surveyed edges
            edge_result = await session.execute(
                select(TopologyEdge).where(TopologyEdge.dt_id == dt.dt_id)
            )
            edges = [
                {
                    "child_pole_id": e.child_pole_id,
                    "parent_pole_id": e.parent_pole_id,
                }
                for e in edge_result.scalars().all()
            ]

            tree = build_tree_from_edges(
                dt_id=str(dt.dt_id),
                dt_lat=float(dt.lat),
                dt_lon=float(dt.lon),
                feeder_id=str(dt.feeder_id),
                households=int(dt.households_served),
                poles=poles,
                edges=edges,
            )
        else:
            # Infer topology via MST
            tree, inferred_edges = build_tree_from_mst(
                dt_id=str(dt.dt_id),
                dt_lat=float(dt.lat),
                dt_lon=float(dt.lon),
                feeder_id=str(dt.feeder_id),
                households=int(dt.households_served),
                poles=poles,
            )

            # Persist inferred edges
            for edge in inferred_edges:
                stmt = (
                    pg_insert(TopologyEdge)
                    .values(**edge)
                    .on_conflict_do_nothing()
                )
                await session.execute(stmt)

        trees[str(dt.dt_id)] = tree

    await session.commit()
    logger.info(f"Built {len(trees)} DT trees.")
    return trees
