"""Automated tests for tactical route planning, obstacle avoidance, and hazard awareness."""
from __future__ import annotations

from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.converter import parse_dxf, reconstruct, validate
from app.main import app
from app.routing import (
    dist_2d,
    plan_route,
    segments_intersect,
)

FIXTURES = Path(__file__).parent.parent / "fixtures"
DEMO_PATH = FIXTURES / "tactical_demo.dxf"


@pytest.fixture(scope="module")
def demo_collection():
    """Load and parse the synthetic tactical demo DXF."""
    assert DEMO_PATH.exists(), f"Demo fixture not found at {DEMO_PATH}"
    return parse_dxf(DEMO_PATH.read_bytes())


# ---------------------------------------------------------------------------
# 1. Valid route through a connected corridor
# ---------------------------------------------------------------------------
def test_valid_route_through_connected_corridor(demo_collection):
    # Open corridor from (2000, 5000) to Exit A (0, 5000)
    res = plan_route(
        collection=demo_collection,
        start=[2000, 5000],
        destination=[0, 5000],
    )
    assert res["status"] == "success"
    assert len(res["path"]) >= 2
    assert res["distance"] > 0
    assert pytest.approx(res["path"][0][0], abs=100) == 2000
    assert pytest.approx(res["path"][-1][0], abs=100) == 0


# ---------------------------------------------------------------------------
# 2. Route through a valid doorway
# ---------------------------------------------------------------------------
def test_route_through_valid_doorway(demo_collection):
    # Start inside Room 1 at (3000, 2500); destination in corridor at (3000, 5000)
    # The only exit is Door 1 at (3000, 4000)
    res = plan_route(
        collection=demo_collection,
        start=[3000, 2500],
        destination=[3000, 5000],
    )
    assert res["status"] == "success"
    path = res["path"]
    # Path must traverse near Door 1 at (3000, 4000)
    door_passed = any(dist_2d(pt, (3000, 4000)) <= 800 for pt in path)
    assert door_passed, f"Path did not traverse doorway at (3000, 4000): {path}"
    # Verify instruction mentions doorway
    assert any("doorway" in instr.lower() for instr in res["instructions"])


# ---------------------------------------------------------------------------
# 3. Wall that blocks a potential route
# ---------------------------------------------------------------------------
def test_wall_blocks_potential_route(demo_collection):
    # From Room 1 (3000, 2500) to point west of solid wall (500, 2500)
    # Solid wall runs from (1000, 1000) to (1000, 4000)
    res = plan_route(
        collection=demo_collection,
        start=[3000, 2500],
        destination=[500, 2500],
    )
    assert res["status"] == "success"
    path = res["path"]
    # Verify no segment of path intersects the solid west wall ((1000, 1000), (1000, 4000))
    wall_p1 = (1000.0, 1000.0)
    wall_p2 = (1000.0, 4000.0)
    for i in range(len(path) - 1):
        seg_a = tuple(path[i])
        seg_b = tuple(path[i + 1])
        assert not segments_intersect(seg_a, seg_b, wall_p1, wall_p2), \
            f"Path segment {seg_a} -> {seg_b} crossed solid wall {wall_p1} -> {wall_p2}"


# ---------------------------------------------------------------------------
# 4. Confirmed blocked corridor
# ---------------------------------------------------------------------------
def test_confirmed_blocked_corridor(demo_collection):
    # Central corridor has blocked debris at X in [7000, 8000], Y in [4000, 6000]
    # Routing across the block from (6000, 5000) to (9000, 5000)
    res = plan_route(
        collection=demo_collection,
        start=[6000, 5000],
        destination=[9000, 5000],
        hazard_mode="ignore",
    )
    assert res["status"] == "success"
    path = res["path"]
    # Path cannot enter blocked rectangle [7000..8000] x [4000..6000]
    for pt in path:
        in_blocked_core = (7200 < pt[0] < 7800) and (4200 < pt[1] < 5800)
        assert not in_blocked_core, f"Point {pt} passed through blocked corridor debris!"


# ---------------------------------------------------------------------------
# 5. Hazard penalty that changes the preferred route when alternative exists
# ---------------------------------------------------------------------------
def test_hazard_penalty_changes_preferred_route(demo_collection):
    # Path from (5000, 5000) to (11000, 5000) across the blocked corridor
    # North bypass has hazard at (8000, 8250) spanning the corridor
    # South bypass is clear of hazards
    res_ignore = plan_route(
        collection=demo_collection,
        start=[5000, 5000],
        destination=[11000, 5000],
        hazard_mode="ignore",
    )
    res_avoid = plan_route(
        collection=demo_collection,
        start=[5000, 5000],
        destination=[11000, 5000],
        hazard_mode="avoid",
        hazard_penalty=10.0,
    )
    res_block = plan_route(
        collection=demo_collection,
        start=[5000, 5000],
        destination=[11000, 5000],
        hazard_mode="block",
    )

    assert res_ignore["status"] == "success"
    assert res_avoid["status"] == "success"
    assert res_block["status"] == "success"

    # 'ignore' traverses North (Y > 6000)
    max_y_ignore = max(pt[1] for pt in res_ignore["path"])
    assert max_y_ignore > 7000, "Ignore hazard did not take North bypass"

    # 'block' traverses South (Y < 4000)
    min_y_block = min(pt[1] for pt in res_block["path"])
    assert min_y_block < 3000, "Block hazard did not take South bypass"

    # 'avoid' takes the South bypass to avoid hazard penalty
    min_y_avoid = min(pt[1] for pt in res_avoid["path"])
    assert min_y_avoid < 3000, "Avoid hazard did not prefer clean South bypass"


# ---------------------------------------------------------------------------
# 6. Destination that is unreachable
# ---------------------------------------------------------------------------
def test_destination_that_is_unreachable(demo_collection):
    # Target is inside Vault (X: 1000..4000, Y: 7000..9500) with 4 solid walls and NO door
    res = plan_route(
        collection=demo_collection,
        start=[3000, 2500],
        destination=[2500, 8250],
    )
    assert res["status"] in ("unreachable", "invalid_input")
    assert len(res["path"]) == 0
    assert res["error"] is not None


# ---------------------------------------------------------------------------
# 7. Invalid start and destination inputs
# ---------------------------------------------------------------------------
def test_invalid_start_and_destination_inputs(demo_collection):
    # Missing coordinate in start
    res1 = plan_route(collection=demo_collection, start=[100], destination=[0, 5000])
    assert res1["status"] == "invalid_input"

    # Destination unknown keyword
    res2 = plan_route(collection=demo_collection, start=[3000, 2500], destination="space_shuttle")
    assert res2["status"] == "invalid_input"

    # Start outside building bounds
    res3 = plan_route(collection=demo_collection, start=[-99999, -99999], destination=[0, 5000])
    assert res3["status"] == "invalid_input"


# ---------------------------------------------------------------------------
# 8. Floor plan with missing or insufficient geometry
# ---------------------------------------------------------------------------
def test_missing_or_insufficient_geometry():
    # Empty feature collection
    empty_col = {"type": "FeatureCollection", "features": [], "metadata": {}}
    res1 = plan_route(collection=empty_col, start=[0, 0], destination=[10, 10])
    assert res1["status"] == "insufficient_geometry"

    # Collection with no walls (only annotations)
    anno_col = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [10, 10]},
                "properties": {"category": "annotation", "source_layer": "ANNO", "source_entity": "TEXT"},
            }
        ],
        "metadata": {"bbox": [0, 0, 100, 100]},
    }
    res2 = plan_route(collection=anno_col, start=[10, 10], destination=[50, 50])
    assert res2["status"] == "insufficient_geometry"


# ---------------------------------------------------------------------------
# 9. Multiple candidate exits (selects best reachable exit)
# ---------------------------------------------------------------------------
def test_multiple_candidate_exits(demo_collection):
    # From Room 1 (3000, 2500):
    # Exit A is at West (0, 5000) - distance ~4.6m
    # Exit B is at East (16000, 5000) - distance ~17m and blocked corridor in between
    res = plan_route(
        collection=demo_collection,
        start=[3000, 2500],
        destination="nearest_exit",
    )
    assert res["status"] == "success"
    chosen = res["destination_info"]
    assert "Exit A" in chosen.get("label", "") or "0" in str(chosen.get("center", []))
    assert res["distance"] < 8000


# ---------------------------------------------------------------------------
# 10. Start and destination locations in the same walkable area
# ---------------------------------------------------------------------------
def test_start_and_destination_in_same_walkable_area(demo_collection):
    res = plan_route(
        collection=demo_collection,
        start=[2000, 5000],
        destination=[2800, 5000],
    )
    assert res["status"] == "success"
    assert pytest.approx(res["distance"], abs=50) == 800


# ---------------------------------------------------------------------------
# 11. Route that would cross a wall if obstacles were ignored
# ---------------------------------------------------------------------------
def test_route_avoids_straight_line_wall_crossing(demo_collection):
    # Start: Room 1 at (3000, 2500)
    # Dest: Exit A at (0, 5000)
    # Direct straight line connects (3000, 2500) -> (0, 5000), crossing Room 1 West wall
    res = plan_route(
        collection=demo_collection,
        start=[3000, 2500],
        destination=[0, 5000],
    )
    assert res["status"] == "success"
    straight_dist = dist_2d((3000, 2500), (0, 5000))
    # Must exit via doorway at (3000, 4000) into corridor, making distance > straight line
    assert res["distance"] > straight_dist + 400, \
        f"Route appears to be straight line! dist={res['distance']}, straight={straight_dist}"


# ---------------------------------------------------------------------------
# 12. Correct API responses for success and failure
# ---------------------------------------------------------------------------
def test_api_responses_for_route_endpoint(demo_collection):
    client = TestClient(app)

    # Success case
    req_success = {
        "collection": demo_collection,
        "start": [3000, 2500],
        "destination": "nearest_exit",
        "hazard_mode": "avoid",
        "hazard_penalty": 5.0,
    }
    r = client.post("/api/route", json=req_success)
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "success"
    assert "path" in data and len(data["path"]) > 0
    assert "instructions" in data
    assert "warnings" in data

    # Failure case: Unreachable destination
    req_unreachable = {
        "collection": demo_collection,
        "start": [3000, 2500],
        "destination": [2500, 8250],  # Vault with no doors
        "hazard_mode": "avoid",
    }
    r2 = client.post("/api/route", json=req_unreachable)
    assert r2.status_code == 200
    assert r2.json()["status"] in ("unreachable", "invalid_input")

    # Failure case: Invalid payload (missing start)
    r3 = client.post("/api/route", json={"collection": demo_collection})
    assert r3.status_code == 422


# ---------------------------------------------------------------------------
# 13. Route telemetry and clearing properties
# ---------------------------------------------------------------------------
def test_route_telemetry_properties(demo_collection):
    res = plan_route(
        collection=demo_collection,
        start=[3000, 2500],
        destination=[16000, 5000],
        hazard_mode="avoid",
    )
    assert res["status"] == "success"
    assert "distance" in res and res["distance"] > 0
    assert "cost" in res and res["cost"] >= res["distance"]
    assert "multi_floor" in res
    assert not res["multi_floor"]["supported"]
    assert "single-floor" in res["multi_floor"]["message"].lower()


# ---------------------------------------------------------------------------
# 14. Regression test for existing conversion and reconstruction features
# ---------------------------------------------------------------------------
def test_regression_existing_fixtures_and_roundtrip():
    dxf_files = list(FIXTURES.glob("*.dxf"))
    assert len(dxf_files) >= 6

    for dxf_file in dxf_files:
        content = dxf_file.read_bytes()
        parsed = parse_dxf(content)
        assert parsed["metadata"]["entity_count"] > 0
        assert "units_code" in parsed["metadata"]
        # Roundtrip check
        reconstructed = parse_dxf(reconstruct(parsed))
        report = validate(parsed, reconstructed)
        if dxf_file.stem == "commercial":
            # Commercial has an unsupported hatch fixture test
            assert report["unsupported_entity_count"] == 1
            assert report["status"] != "PASSED"
        else:
            assert report["missing_entities"] == 0
            assert report["extra_entities"] == 0
            assert report["status"] == "PASSED"
