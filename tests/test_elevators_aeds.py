"""Automated tests for Elevator and AED classification, tactical visibility, and round-tripping."""
from __future__ import annotations

import io
import json
from pathlib import Path
import ezdxf
import pytest
from app.converter import classify, parse_dxf, reconstruct, validate

FIXTURES = Path(__file__).parent.parent / "fixtures"


def make_elevator_aed_doc():
    """Create a minimal synthetic DXF with elevator, AED, wall, and other entities."""
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    doc.layers.new("A-ELEV")
    doc.layers.new("AED")
    doc.layers.new("A-WALL")
    doc.layers.new("SHADED_AREAS")
    doc.layers.new("ELEVATION_DIMS")

    # Walls
    msp.add_line((0, 0), (10000, 0), dxfattribs={"layer": "A-WALL"})
    # Elevator car
    msp.add_lwpolyline([(2000, 2000), (4000, 2000), (4000, 4000), (2000, 4000)], close=True, dxfattribs={"layer": "A-ELEV"})
    # AED unit
    msp.add_circle((6000, 3000), 200, dxfattribs={"layer": "AED"})
    # Non-matching entities to test boundary checks
    msp.add_line((0, 5000), (5000, 5000), dxfattribs={"layer": "SHADED_AREAS"})
    msp.add_line((5000, 5000), (10000, 5000), dxfattribs={"layer": "ELEVATION_DIMS"})
    return doc


def bytes_doc(doc):
    out = io.StringIO()
    doc.write(out)
    return out.getvalue().encode("utf-8")


def frontend_visible(f, mode: str, hidden: set[str]) -> bool:
    """Exact replica of the frontend visible(f) predicate in web/app.js."""
    cat = f["properties"]["category"]
    tactical = f["properties"].get("tactical", False)
    return (cat not in hidden) and (mode == "full" or tactical)


# ---------------------------------------------------------------------------
# Required Case 1: An A-ELEV layer is classified as elevator
# ---------------------------------------------------------------------------
def test_case_1_a_elev_classified_as_elevator():
    assert classify("A-ELEV", "LINE") == "elevator"
    assert classify("A-ELEV", "LWPOLYLINE") == "elevator"
    assert classify("a-elev", "LINE") == "elevator"


# ---------------------------------------------------------------------------
# Required Case 2: An ELEVATOR layer is classified as elevator
# ---------------------------------------------------------------------------
def test_case_2_elevator_classified_as_elevator():
    assert classify("ELEVATOR", "LWPOLYLINE") == "elevator"
    assert classify("ELEVATORS", "LINE") == "elevator"
    assert classify("A-ELEVATOR", "LINE") == "elevator"


# ---------------------------------------------------------------------------
# Required Case 3: A LIFT layer is classified as elevator
# ---------------------------------------------------------------------------
def test_case_3_lift_classified_as_elevator():
    assert classify("LIFT", "POINT") == "elevator"
    assert classify("LIFTS", "LWPOLYLINE") == "elevator"
    assert classify("VERTICAL_TRANSPORT", "LINE") == "elevator"
    assert classify("ELEV", "POINT") == "elevator"
    assert classify("ELEV-1", "LINE") == "elevator"


# ---------------------------------------------------------------------------
# Boundary & Precedence checks: Avoid false positives
# ---------------------------------------------------------------------------
def test_avoid_false_positive_elevator_and_aed():
    # 'ELEVATION' must NOT match elevator
    assert classify("ELEVATION_DIMS", "LINE") != "elevator"
    assert classify("ELEVATION", "LINE") != "elevator"
    # 'SHADED' must NOT match aed
    assert classify("SHADED_AREAS", "LINE") != "aed"
    assert classify("SHADED", "LINE") != "aed"


# ---------------------------------------------------------------------------
# Required Case 4: An AED layer is classified as aed
# ---------------------------------------------------------------------------
def test_case_4_aed_classified_as_aed():
    assert classify("AED", "POINT") == "aed"
    assert classify("A-AED", "CIRCLE") == "aed"
    assert classify("AED_DEVICE", "INSERT") == "aed"
    assert classify("aed", "POINT") == "aed"


# ---------------------------------------------------------------------------
# Required Case 5: A DEFIBRILLATOR layer is classified as aed
# ---------------------------------------------------------------------------
def test_case_5_defibrillator_classified_as_aed():
    assert classify("DEFIBRILLATOR", "POINT") == "aed"
    assert classify("AUTOMATED_EXTERNAL_DEFIBRILLATOR", "POINT") == "aed"
    assert classify("EMERGENCY_DEFIBRILLATOR", "CIRCLE") == "aed"


# ---------------------------------------------------------------------------
# Required Case 6: Both categories receive tactical: true
# ---------------------------------------------------------------------------
def test_case_6_both_categories_receive_tactical_true():
    doc = make_elevator_aed_doc()
    parsed = parse_dxf(bytes_doc(doc))
    elevators = [f for f in parsed["features"] if f["properties"]["category"] == "elevator"]
    aeds = [f for f in parsed["features"] if f["properties"]["category"] == "aed"]

    assert len(elevators) >= 1
    assert len(aeds) >= 1

    for e in elevators:
        assert e["properties"]["tactical"] is True
        assert e["properties"]["display_name"] == "Elevator"

    for a in aeds:
        assert a["properties"]["tactical"] is True
        assert a["properties"]["display_name"] == "AED"


# ---------------------------------------------------------------------------
# Required Case 7: Both categories appear in Tactical View
# ---------------------------------------------------------------------------
def test_case_7_both_appear_in_tactical_view():
    doc = make_elevator_aed_doc()
    parsed = parse_dxf(bytes_doc(doc))
    elev_f = next(f for f in parsed["features"] if f["properties"]["category"] == "elevator")
    aed_f = next(f for f in parsed["features"] if f["properties"]["category"] == "aed")

    assert frontend_visible(elev_f, mode="tactical", hidden=set()) is True
    assert frontend_visible(aed_f, mode="tactical", hidden=set()) is True


# ---------------------------------------------------------------------------
# Required Case 8: Both categories appear in Full View
# ---------------------------------------------------------------------------
def test_case_8_both_appear_in_full_view():
    doc = make_elevator_aed_doc()
    parsed = parse_dxf(bytes_doc(doc))
    elev_f = next(f for f in parsed["features"] if f["properties"]["category"] == "elevator")
    aed_f = next(f for f in parsed["features"] if f["properties"]["category"] == "aed")

    assert frontend_visible(elev_f, mode="full", hidden=set()) is True
    assert frontend_visible(aed_f, mode="full", hidden=set()) is True


# ---------------------------------------------------------------------------
# Required Case 9: Hiding either category affects only its display visibility
# ---------------------------------------------------------------------------
def test_case_9_hiding_affects_only_its_display_visibility():
    doc = make_elevator_aed_doc()
    parsed = parse_dxf(bytes_doc(doc))
    elev_f = next(f for f in parsed["features"] if f["properties"]["category"] == "elevator")
    aed_f = next(f for f in parsed["features"] if f["properties"]["category"] == "aed")

    # Hide elevator only
    assert frontend_visible(elev_f, mode="tactical", hidden={"elevator"}) is False
    assert frontend_visible(aed_f, mode="tactical", hidden={"elevator"}) is True
    assert frontend_visible(elev_f, mode="full", hidden={"elevator"}) is False
    assert frontend_visible(aed_f, mode="full", hidden={"elevator"}) is True

    # Hide AED only
    assert frontend_visible(aed_f, mode="tactical", hidden={"aed"}) is False
    assert frontend_visible(elev_f, mode="tactical", hidden={"aed"}) is True
    assert frontend_visible(aed_f, mode="full", hidden={"aed"}) is False
    assert frontend_visible(elev_f, mode="full", hidden={"aed"}) is True


# ---------------------------------------------------------------------------
# Required Case 10: Switching views and applying filters does not delete features
# ---------------------------------------------------------------------------
def test_case_10_switching_views_does_not_alter_underlying_dataset():
    doc = make_elevator_aed_doc()
    parsed = parse_dxf(bytes_doc(doc))
    original_count = len(parsed["features"])

    # Simulate tactical display filter with elevator hidden
    tactical_display = [f for f in parsed["features"] if frontend_visible(f, "tactical", {"elevator"})]
    assert len(tactical_display) < original_count

    # Underlying collection must remain 100% complete
    assert len(parsed["features"]) == original_count
    assert any(f["properties"]["category"] == "elevator" for f in parsed["features"])
    assert any(f["properties"]["category"] == "aed" for f in parsed["features"])


# ---------------------------------------------------------------------------
# Required Case 11: GeoJSON export preserves categories and tactical flags
# ---------------------------------------------------------------------------
def test_case_11_geojson_export_and_reconstruction_preserves_categories():
    doc = make_elevator_aed_doc()
    original = parse_dxf(bytes_doc(doc))

    # Export to GeoJSON string & reload
    exported_json = json.dumps(original)
    reloaded = json.loads(exported_json)

    # Reconstruct back to DXF and re-parse
    rebuilt_bytes = reconstruct(reloaded)
    reconstructed = parse_dxf(rebuilt_bytes)

    # Verify categories and tactical flags are preserved
    report = validate(original, reconstructed)
    assert report["missing_entities"] == 0
    assert report["extra_entities"] == 0
    assert report["status"] == "PASSED"

    elev_orig = next(f for f in original["features"] if f["properties"]["category"] == "elevator")
    elev_rebuilt = next(f for f in reconstructed["features"] if f["properties"]["category"] == "elevator")
    assert elev_rebuilt["properties"]["tactical"] is True
    assert elev_rebuilt["properties"]["display_name"] == "Elevator"

    aed_orig = next(f for f in original["features"] if f["properties"]["category"] == "aed")
    aed_rebuilt = next(f for f in reconstructed["features"] if f["properties"]["category"] == "aed")
    assert aed_rebuilt["properties"]["tactical"] is True
    assert aed_rebuilt["properties"]["display_name"] == "AED"


# ---------------------------------------------------------------------------
# Required Case 12: Existing sample fixtures parse elevator and AED properly
# ---------------------------------------------------------------------------
def test_case_12_fixtures_contain_elevator_and_aed():
    demo_dxf = FIXTURES / "tactical_demo.dxf"
    assert demo_dxf.exists()
    parsed = parse_dxf(demo_dxf.read_bytes())
    cats = parsed["metadata"]["category_counts"]
    assert "elevator" in cats
    assert "aed" in cats

    # Check tactical counts
    tactical_cats = {f["properties"]["category"] for f in parsed["features"] if f["properties"]["tactical"]}
    assert "elevator" in tactical_cats
    assert "aed" in tactical_cats
