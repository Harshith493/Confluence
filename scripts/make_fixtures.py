"""Generate synthetic DXF floor plans including the comprehensive buildathon tactical demo."""
from pathlib import Path
import ezdxf

ROOT = Path(__file__).parent.parent / "fixtures"

BUILDINGS = {
    "office": [("A-WALL", "wall"), ("DOORS", "door"), ("STAIRS", "stair"), ("A-ELEV", "elevator"), ("AED", "aed"), ("FIRE_EXT", "fire_extinguisher"), ("FURNITURE", "furniture"), ("ANNO", "annotation")],
    "hospital": [("WALL", "wall"), ("DOOR", "door"), ("EMERGENCY_EXIT", "emergency_exit"), ("SPRINKLER", "sprinkler"), ("HYDRANT", "hydrant"), ("ELEVATOR", "elevator"), ("DEFIBRILLATOR", "aed"), ("MEDICAL_EQUIP", "other")],
    "school": [("WALL", "wall"), ("ENTRY", "entrance"), ("STAIRWELL", "stair"), ("A-ELEV", "elevator"), ("AED_DEVICE", "aed"), ("FIRE_ALARM", "fire_alarm"), ("HAZMAT", "hazard"), ("FURNITURE", "furniture")],
    "apartment": [("A-WALL", "wall"), ("DOORS", "door"), ("EXIT", "emergency_exit"), ("LIFT", "elevator"), ("PLUMB", "plumbing"), ("ELEC", "electrical"), ("DIM", "dimension")],
    "commercial": [("WALL", "wall"), ("ENTRANCE", "entrance"), ("VERTICAL_TRANSPORT", "elevator"), ("FIRE-HYDRANT", "hydrant"), ("FIRE_EXT", "fire_extinguisher"), ("SPRINKLER", "sprinkler"), ("FURNITURE", "furniture")],
}


def make_tactical_demo(root: Path):
    """Generate reproducible tactical building floor plan with known geometry.

    Building: 16m x 10m (16000 x 10000 mm).
    Contains:
    - Several rooms and connecting corridors.
    - Solid walls with openings at designated doorways.
    - Two emergency exits (Exit A at West (0, 5000), Exit B at East (16000, 5000)).
    - Central corridor blocked passage (BLOCKED at X=7000-8000, Y=4000-6000).
    - North bypass containing a chemical hazard (HAZMAT at (8000, 8250), radius 1000, blocking North passage).
    - Clear South bypass service hallway (X=5500..10500, Y=500..1500).
    - Isolated Vault room (X=1000-4000, Y=7000-9500) with no doors (unreachable test).
    - Elevator (A-ELEV) in East wing at (14000, 2500).
    - AED device (AED) in Central Corridor at (4500, 5200).
    - Start location in Room 1 at (3000, 2500).
    - Annex at (500, 2500) accessible only via Central Corridor (X=1000 wall blocks direct passage from Room 1).
    """
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()

    layers = [
        "A-WALL", "A-DOOR", "EMERGENCY_EXIT", "ENTRANCE", "HAZMAT",
        "BLOCKED", "STAIRS", "HYDRANT", "A-ELEV", "AED", "ANNO"
    ]
    for l in layers:
        if l not in doc.layers:
            doc.layers.new(l)

    # 1. Outer Boundary (16m x 10m)
    # Bottom wall
    msp.add_line((0, 0), (16000, 0), dxfattribs={"layer": "A-WALL"})
    # Top wall
    msp.add_line((0, 10000), (16000, 10000), dxfattribs={"layer": "A-WALL"})
    # Left wall (with Exit A opening at Y=4500-5500)
    msp.add_line((0, 0), (0, 4500), dxfattribs={"layer": "A-WALL"})
    msp.add_line((0, 5500), (0, 10000), dxfattribs={"layer": "A-WALL"})
    # Right wall (with Exit B opening at Y=4500-5500)
    msp.add_line((16000, 0), (16000, 4500), dxfattribs={"layer": "A-WALL"})
    msp.add_line((16000, 5500), (16000, 10000), dxfattribs={"layer": "A-WALL"})

    # 2. Central Corridor Walls (Y=4000 and Y=6000)
    # South Corridor Wall (Y=4000)
    # Opening at X=0..1000 connects to West Annex
    msp.add_line((1000, 4000), (2500, 4000), dxfattribs={"layer": "A-WALL"})
    # Opening at X=2500..3500 for Door 1
    msp.add_line((3500, 4000), (5500, 4000), dxfattribs={"layer": "A-WALL"})
    # Opening at X=5500..6500 for South Bypass entry
    msp.add_line((6500, 4000), (9500, 4000), dxfattribs={"layer": "A-WALL"})
    # Opening at X=9500..10500 for South Bypass exit
    msp.add_line((10500, 4000), (11500, 4000), dxfattribs={"layer": "A-WALL"})
    # Opening at X=11500..12500 for Door 2
    msp.add_line((12500, 4000), (16000, 4000), dxfattribs={"layer": "A-WALL"})

    # North Corridor Wall (Y=6000)
    msp.add_line((0, 6000), (4500, 6000), dxfattribs={"layer": "A-WALL"})
    # Opening at X=4500..5500 for North Bypass entry
    msp.add_line((5500, 6000), (10500, 6000), dxfattribs={"layer": "A-WALL"})
    # Opening at X=10500..11500 for North Bypass exit
    msp.add_line((11500, 6000), (16000, 6000), dxfattribs={"layer": "A-WALL"})

    # 3. Room 1 (Command Office - Start Location: (3000, 2500))
    # West wall at X=1000 blocks direct passage to West Annex (500, 2500)
    msp.add_line((1000, 1000), (1000, 4000), dxfattribs={"layer": "A-WALL"})
    msp.add_line((1000, 1000), (5000, 1000), dxfattribs={"layer": "A-WALL"})
    msp.add_line((5000, 1000), (5000, 4000), dxfattribs={"layer": "A-WALL"})
    # Door 1 at (3000, 4000)
    msp.add_arc((3000, 4000), 500, 0, 90, dxfattribs={"layer": "A-DOOR"})

    # 4. Room 2 (Operations - South East)
    msp.add_line((11000, 1000), (11000, 4000), dxfattribs={"layer": "A-WALL"})
    msp.add_line((11000, 1000), (15000, 1000), dxfattribs={"layer": "A-WALL"})
    msp.add_line((15000, 1000), (15000, 4000), dxfattribs={"layer": "A-WALL"})
    # Door 2 at (12000, 4000)
    msp.add_arc((12000, 4000), 500, 0, 90, dxfattribs={"layer": "A-DOOR"})

    # 5. North Bypass Corridor Walls
    # Inner wall
    msp.add_line((5500, 6000), (5500, 7500), dxfattribs={"layer": "A-WALL"})
    msp.add_line((5500, 7500), (10500, 7500), dxfattribs={"layer": "A-WALL"})
    msp.add_line((10500, 7500), (10500, 6000), dxfattribs={"layer": "A-WALL"})
    # Outer wall
    msp.add_line((4500, 6000), (4500, 9000), dxfattribs={"layer": "A-WALL"})
    msp.add_line((4500, 9000), (11500, 9000), dxfattribs={"layer": "A-WALL"})
    msp.add_line((11500, 9000), (11500, 6000), dxfattribs={"layer": "A-WALL"})

    # 6. South Bypass Service Corridor Walls (U-shaped passage around blocked area)
    # West channel
    msp.add_line((5500, 4000), (5500, 500), dxfattribs={"layer": "A-WALL"})
    msp.add_line((6500, 4000), (6500, 1500), dxfattribs={"layer": "A-WALL"})
    # South horizontal channel
    msp.add_line((5500, 500), (10500, 500), dxfattribs={"layer": "A-WALL"})
    msp.add_line((6500, 1500), (9500, 1500), dxfattribs={"layer": "A-WALL"})
    # East channel
    msp.add_line((9500, 1500), (9500, 4000), dxfattribs={"layer": "A-WALL"})
    msp.add_line((10500, 500), (10500, 4000), dxfattribs={"layer": "A-WALL"})

    # 7. Vault (Isolated Room - Unreachable test)
    # Four solid walls with NO doors
    msp.add_line((1000, 7000), (4000, 7000), dxfattribs={"layer": "A-WALL"})
    msp.add_line((4000, 7000), (4000, 9500), dxfattribs={"layer": "A-WALL"})
    msp.add_line((4000, 9500), (1000, 9500), dxfattribs={"layer": "A-WALL"})
    msp.add_line((1000, 9500), (1000, 7000), dxfattribs={"layer": "A-WALL"})

    # 8. Blocked Passage in Central Corridor (X=7000..8000, Y=4000..6000)
    msp.add_lwpolyline(
        [(7000, 4000), (8000, 4000), (8000, 6000), (7000, 6000)],
        close=True,
        dxfattribs={"layer": "BLOCKED"},
    )
    msp.add_line((7000, 4000), (8000, 6000), dxfattribs={"layer": "BLOCKED"})
    msp.add_line((7000, 6000), (8000, 4000), dxfattribs={"layer": "BLOCKED"})

    # 9. Hazard in North Bypass Corridor (X=8000, Y=8250, radius=1000)
    msp.add_circle((8000, 8250), 1000, dxfattribs={"layer": "HAZMAT"})

    # 10. Emergency Exits
    # Exit A (West) at (0, 5000)
    msp.add_circle((0, 5000), 250, dxfattribs={"layer": "EMERGENCY_EXIT"})
    msp.add_text("EXIT A", dxfattribs={"layer": "ANNO", "insert": (100, 5200), "height": 200})

    # Exit B (East) at (16000, 5000)
    msp.add_circle((16000, 5000), 250, dxfattribs={"layer": "EMERGENCY_EXIT"})
    msp.add_text("EXIT B", dxfattribs={"layer": "ANNO", "insert": (15300, 5200), "height": 200})

    # 11. Tactical Equipment: Hydrant, Stairs, Elevator, AED
    msp.add_circle((2000, 5000), 120, dxfattribs={"layer": "HYDRANT"})
    msp.add_lwpolyline([(500, 500), (1000, 500), (1000, 1000), (500, 1000)], close=True, dxfattribs={"layer": "STAIRS"})
    # Elevator at (13500..14500, 2000..3000) in Room 2 wing
    msp.add_lwpolyline([(13500, 2000), (14500, 2000), (14500, 3000), (13500, 3000)], close=True, dxfattribs={"layer": "A-ELEV"})
    msp.add_text("ELEVATOR 1", dxfattribs={"layer": "ANNO", "insert": (13600, 2500), "height": 160})
    # AED Station in central corridor at (4500, 5200)
    msp.add_circle((4500, 5200), 120, dxfattribs={"layer": "AED"})
    msp.add_text("AED STATION", dxfattribs={"layer": "ANNO", "insert": (4300, 5400), "height": 140})

    # 12. Annotations
    msp.add_text("ROOM 1 - COMMAND (START)", dxfattribs={"layer": "ANNO", "insert": (1500, 2500), "height": 180})
    msp.add_text("CORRIDOR (BLOCKED AHEAD)", dxfattribs={"layer": "ANNO", "insert": (6800, 5000), "height": 160})
    msp.add_text("VAULT (ISOLATED)", dxfattribs={"layer": "ANNO", "insert": (1500, 8000), "height": 180})

    doc.header["$INSUNITS"] = 4  # Millimeters
    demo_path = root / "tactical_demo.dxf"
    doc.saveas(demo_path)


def main():
    ROOT.mkdir(exist_ok=True)
    for name, layers in BUILDINGS.items():
        doc = ezdxf.new("R2010")
        msp = doc.modelspace()
        for layer, _ in layers:
            if layer not in doc.layers:
                doc.layers.new(layer)
        wall = next((layer for layer, _ in layers if "WALL" in layer), layers[0][0])
        for a, b in [((0, 0), (12000, 0)), ((12000, 0), (12000, 8000)),
                     ((12000, 8000), (0, 8000)), ((0, 8000), (0, 0)),
                     ((4000, 0), (4000, 8000)), ((8000, 0), (8000, 8000))]:
            msp.add_line(a, b, dxfattribs={"layer": wall})
        for i, (layer, category) in enumerate(layers[1:]):
            x, y = 900 + i * 1650, 700 + (i % 3) * 1850
            if category == "door":
                msp.add_arc((x, y), 350, 0, 90, dxfattribs={"layer": layer})
            elif category in {"stair", "elevator"}:
                msp.add_lwpolyline([(x, y), (x+900, y), (x+900, y+700), (x, y+700)], close=True, dxfattribs={"layer": layer})
            elif category in {"hydrant", "fire_extinguisher", "sprinkler", "fire_alarm", "entrance", "emergency_exit", "hazard", "aed"}:
                msp.add_circle((x, y), 110, dxfattribs={"layer": layer})
            elif category == "annotation":
                msp.add_text(f"{name.upper()} LEVEL 1", dxfattribs={"layer": layer, "insert": (x, y), "height": 160})
            else:
                msp.add_lwpolyline([(x, y), (x+420, y), (x+420, y+260), (x, y+260)], close=True, dxfattribs={"layer": layer})
        if name == "commercial":
            hatch = msp.add_hatch(color=8, dxfattribs={"layer": wall})
            hatch.paths.add_polyline_path([(1500, 1500), (2500, 1500), (2500, 2500), (1500, 2500)], is_closed=True)
        doc.header["$INSUNITS"] = 4
        doc.saveas(ROOT / f"{name}.dxf")

    make_tactical_demo(ROOT)


if __name__ == "__main__":
    main()
