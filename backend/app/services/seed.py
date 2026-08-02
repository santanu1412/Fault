"""Synthetic network data generator.

Generates a realistic radial LT power distribution network for the demo:
- Substations → Feeders → DTs → Poles in a geographic cluster
- 40% of DTs have known topology (parent_pole_id populated)
- 60% of DTs have unknown topology (must be inferred via MST)
- ~9% of poles have no IoT device
- ~3% of poles have no pincode
- Uses Bangalore/Karnataka-area coordinates for realism
"""

import logging
import math
import random

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.outage import ScheduledOutage
from app.models.pole import Pole
from app.models.pole_state import PoleState
from app.models.topology import TopologyEdge
from app.models.transformer import Transformer

logger = logging.getLogger("fault_system.seed")

# Bangalore area center coordinates
BASE_LAT = 12.9716
BASE_LON = 77.5946

# PIN codes for the synthetic subdivision
PINCODES = [
    "560001", "560002", "560003", "560004", "560005",
    "560006", "560007", "560008", "560009", "560010",
    "560011", "560012", "560017", "560018", "560020",
]

WARDS = [
    "Rajajinagar", "Malleshwaram", "Basavanagudi", "Jayanagar",
    "Koramangala", "Indiranagar", "Whitefield", "Yelahanka",
    "Hebbal", "Vijayanagar", "Banashankari", "BTM Layout",
]

POLE_TYPES = ["wooden", "steel", "concrete", "rcc"]
POLE_TYPE_WEIGHTS = [0.15, 0.25, 0.45, 0.15]

FW_VERSIONS = ["1.0", "1.1", "1.2", "2.0", "2.1"]


def _offset_coords(base_lat: float, base_lon: float, radius_km: float) -> tuple[float, float]:
    """Generate a random point within radius_km of the base coordinates."""
    # Random angle and distance
    angle = random.uniform(0, 2 * math.pi)
    # Use sqrt for uniform distribution over area
    dist = radius_km * math.sqrt(random.uniform(0, 1))

    # Approximate degree offsets (1 degree lat ≈ 111 km, 1 degree lon ≈ 111 * cos(lat) km)
    dlat = (dist * math.cos(angle)) / 111.0
    dlon = (dist * math.sin(angle)) / (111.0 * math.cos(math.radians(base_lat)))

    return (base_lat + dlat, base_lon + dlon)


def _generate_branch_poles(
    dt_id: str,
    feeder_id: str,
    branch_idx: int,
    num_poles: int,
    start_lat: float,
    start_lon: float,
    heading: float,
    pole_spacing_km: float = 0.04,
    known_topology: bool = True,
    parent_pole_id_for_first: str | None = None,
    ward: str = "Unknown",
    pincode: str = "560001",
    start_seq: int = 0,
    device_coverage: float = 0.91,
    missing_pincode_pct: float = 0.03,
) -> list[dict]:
    """Generate poles along a branch line with slight random curvature."""
    poles = []
    prev_pole_id = parent_pole_id_for_first
    current_lat = start_lat
    current_lon = start_lon

    for i in range(num_poles):
        pole_id = f"{dt_id}-B{branch_idx}-P{i:03d}"

        # Add slight random curvature to the heading
        heading += random.gauss(0, 5)  # ±5 degree jitter

        # Advance along the heading
        dlat = (pole_spacing_km * math.cos(math.radians(heading))) / 111.0
        dlon = (pole_spacing_km * math.sin(math.radians(heading))) / (
            111.0 * math.cos(math.radians(current_lat))
        )
        current_lat += dlat
        current_lon += dlon

        # Determine if this pole has a device
        has_device = random.random() < device_coverage
        device_id = f"DEV-{pole_id}" if has_device else None

        # Determine pincode (3% missing)
        pole_pincode = None if random.random() < missing_pincode_pct else pincode

        pole = {
            "pole_id": pole_id,
            "lat": round(current_lat, 6),
            "lon": round(current_lon, 6),
            "feeder_id": feeder_id,
            "dt_id": dt_id,
            "seq_on_line": float(start_seq + i) if known_topology else None,
            "parent_pole_id": prev_pole_id if known_topology else None,
            "pole_type": random.choices(POLE_TYPES, weights=POLE_TYPE_WEIGHTS, k=1)[0],
            "ward": ward,
            "pincode": pole_pincode,
            "device_id": device_id,
        }
        poles.append(pole)
        prev_pole_id = pole_id

    return poles


async def seed_if_needed(session: AsyncSession) -> bool:
    """Seed the database with synthetic network data if no data exists.
    Returns True if seeding was performed, False if data already exists.
    """
    # Check if data already exists
    result = await session.execute(select(func.count()).select_from(Pole))
    pole_count = result.scalar()
    if pole_count and pole_count > 0:
        logger.info(f"Database already seeded with {pole_count} poles. Skipping.")
        return False

    logger.info("Seeding database with synthetic network data...")

    num_substations = settings.seed_substations
    num_feeders_per_sub = settings.seed_feeders_per_sub
    num_dts_per_feeder = settings.seed_dts_per_feeder
    poles_min = settings.seed_poles_per_dt_min
    poles_max = settings.seed_poles_per_dt_max
    known_topo_pct = settings.seed_known_topology_pct
    device_coverage = settings.seed_device_coverage_pct
    missing_pincode = settings.seed_missing_pincode_pct

    all_transformers = []
    all_poles = []
    all_edges = []
    all_states = []

    total_dts = 0
    total_poles_count = 0

    for sub_idx in range(num_substations):
        # Each substation gets its own area of the city
        sub_lat, sub_lon = _offset_coords(BASE_LAT, BASE_LON, radius_km=5.0)

        for fdr_idx in range(num_feeders_per_sub):
            feeder_id = f"FDR-{sub_idx:02d}-{fdr_idx:02d}"
            # Each feeder radiates from the substation
            fdr_lat, fdr_lon = _offset_coords(sub_lat, sub_lon, radius_km=2.0)

            for dt_idx in range(num_dts_per_feeder):
                dt_id = f"DT-{sub_idx:02d}-{fdr_idx:02d}-{dt_idx:02d}"
                total_dts += 1

                # DT location near feeder
                dt_lat, dt_lon = _offset_coords(fdr_lat, fdr_lon, radius_km=0.8)

                # Determine ward and pincode based on location
                ward = random.choice(WARDS)
                pincode = random.choice(PINCODES)

                # Whether this DT has known topology
                known_topology = random.random() < known_topo_pct

                # Number of branches and poles
                num_branches = random.randint(1, 5)
                total_poles_for_dt = random.randint(poles_min, poles_max)
                poles_per_branch = max(3, total_poles_for_dt // num_branches)

                capacity = random.choice([25, 63, 100, 160, 250])
                households = int(capacity * random.uniform(0.3, 0.6))

                all_transformers.append({
                    "dt_id": dt_id,
                    "feeder_id": feeder_id,
                    "lat": round(dt_lat, 6),
                    "lon": round(dt_lon, 6),
                    "capacity_kva": float(capacity),
                    "households_served": households,
                })

                # Generate poles along branches
                dt_poles = []
                seq_counter = 0
                for br_idx in range(num_branches):
                    # Each branch heads in a different direction from the DT
                    heading = (360.0 / num_branches) * br_idx + random.uniform(-15, 15)

                    branch_poles = _generate_branch_poles(
                        dt_id=dt_id,
                        feeder_id=feeder_id,
                        branch_idx=br_idx,
                        num_poles=poles_per_branch,
                        start_lat=dt_lat,
                        start_lon=dt_lon,
                        heading=heading,
                        known_topology=known_topology,
                        parent_pole_id_for_first=None,
                        ward=ward,
                        pincode=pincode,
                        start_seq=seq_counter,
                        device_coverage=device_coverage,
                        missing_pincode_pct=missing_pincode,
                    )

                    # Fix parent linkage: first pole of each branch connects to DT root
                    # (represented as dt_id in topology_edges)
                    if known_topology and branch_poles:
                        branch_poles[0]["parent_pole_id"] = f"ROOT-{dt_id}"

                    dt_poles.extend(branch_poles)
                    seq_counter += poles_per_branch

                all_poles.extend(dt_poles)
                total_poles_count += len(dt_poles)

                # Build topology edges for known-topology DTs
                if known_topology:
                    for pole_data in dt_poles:
                        if pole_data["parent_pole_id"] is not None:
                            all_edges.append({
                                "child_pole_id": pole_data["pole_id"],
                                "parent_pole_id": pole_data["parent_pole_id"],
                                "dt_id": dt_id,
                                "source": "surveyed",
                                "inferred_confidence": None,
                            })

    # Batch insert transformers
    if all_transformers:
        stmt = pg_insert(Transformer).values(all_transformers).on_conflict_do_nothing()
        await session.execute(stmt)

    logger.info(f"Inserted {len(all_transformers)} transformers.")

    # Batch insert poles in chunks of 1000
    chunk_size = 1000
    for i in range(0, len(all_poles), chunk_size):
        chunk = all_poles[i : i + chunk_size]
        stmt = pg_insert(Pole).values(chunk).on_conflict_do_nothing()
        await session.execute(stmt)

    logger.info(f"Inserted {total_poles_count} poles.")

    # Insert topology edges (only for surveyed DTs — edges referencing ROOT-* are virtual)
    valid_edges = [e for e in all_edges if not e["parent_pole_id"].startswith("ROOT-")]
    if valid_edges:
        for i in range(0, len(valid_edges), chunk_size):
            chunk = valid_edges[i : i + chunk_size]
            stmt = pg_insert(TopologyEdge).values(chunk).on_conflict_do_nothing()
            await session.execute(stmt)

    logger.info(f"Inserted {len(valid_edges)} topology edges.")

    # Batch initialize pole states (all energized at start)
    all_states = [
        {
            "pole_id": p["pole_id"],
            "energized": True,
            "confidence": 1.0,
            "last_event_type": "initial",
            "classification": "ok",
            "missed_heartbeats": 0,
        }
        for p in all_poles
    ]
    for i in range(0, len(all_states), chunk_size):
        chunk = all_states[i : i + chunk_size]
        stmt = pg_insert(PoleState).values(chunk).on_conflict_do_nothing()
        await session.execute(stmt)

    logger.info(f"Initialized {total_poles_count} pole states.")

    # Create a few scheduled outages (for false positive suppression testing)
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    outage_dts = random.sample(
        [t["dt_id"] for t in all_transformers],
        min(3, len(all_transformers)),
    )
    for dt_id in outage_dts:
        outage = {
            "scope": "dt",
            "target_id": dt_id,
            "start_at": now + timedelta(hours=random.randint(1, 12)),
            "end_at": now + timedelta(hours=random.randint(13, 24)),
            "reason": random.choice([
                "Scheduled load shedding",
                "Transformer maintenance",
                "Line upgrade work",
            ]),
        }
        stmt = pg_insert(ScheduledOutage).values(**outage).on_conflict_do_nothing()
        await session.execute(stmt)

    await session.commit()

    from app.services.ingest import invalidate_device_cache
    invalidate_device_cache()

    logger.info(
        f"Seeding complete: {num_substations} substations, "
        f"{num_substations * num_feeders_per_sub} feeders, "
        f"{total_dts} DTs, {total_poles_count} poles, "
        f"{int(total_dts * known_topo_pct)} DTs with known topology."
    )
    return True
