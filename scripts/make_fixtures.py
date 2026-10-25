"""Generate five original synthetic DXF floor plans for local testing."""
from pathlib import Path
import ezdxf

ROOT = Path(__file__).parent.parent / "fixtures"
BUILDINGS = {
    "office": [("A-WALL", "wall"), ("DOORS", "door"), ("STAIRS", "stair"), ("FIRE_EXT", "fire_extinguisher"), ("FURNITURE", "furniture"), ("ANNO", "annotation")],
    "hospital": [("WALL", "wall"), ("DOOR", "door"), ("EMERGENCY_EXIT", "emergency_exit"), ("SPRINKLER", "sprinkler"), ("HYDRANT", "hydrant"), ("MEDICAL_EQUIP", "other")],
    "school": [("WALL", "wall"), ("ENTRY", "entrance"), ("STAIRWELL", "stair"), ("FIRE_ALARM", "fire_alarm"), ("HAZMAT", "hazard"), ("FURNITURE", "furniture")],
    "apartment": [("A-WALL", "wall"), ("DOORS", "door"), ("EXIT", "emergency_exit"), ("PLUMB", "plumbing"), ("ELEC", "electrical"), ("DIM", "dimension")],
    "commercial": [("WALL", "wall"), ("ENTRANCE", "entrance"), ("FIRE-HYDRANT", "hydrant"), ("FIRE_EXT", "fire_extinguisher"), ("SPRINKLER", "sprinkler"), ("FURNITURE", "furniture")],
}

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
            elif category == "stair":
                msp.add_lwpolyline([(x, y), (x+900, y), (x+900, y+700), (x, y+700)], close=True, dxfattribs={"layer": layer})
            elif category in {"hydrant", "fire_extinguisher", "sprinkler", "fire_alarm", "entrance", "emergency_exit", "hazard"}:
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

if __name__ == "__main__":
    main()
