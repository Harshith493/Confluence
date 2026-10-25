"""DXF <-> semantic GeoJSON conversion with explicit support accounting."""
from __future__ import annotations

import io
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

import ezdxf
from ezdxf import recover

_CLASSIFICATION = json.loads((Path(__file__).parent / "classification.json").read_text(encoding="utf-8"))
CATEGORIES = {key: tuple(value) for key, value in _CLASSIFICATION["categories"].items()}
TACTICAL = set(_CLASSIFICATION["tactical_categories"])
SUPPORTED = {"LINE", "LWPOLYLINE", "POLYLINE", "CIRCLE", "ARC", "POINT", "TEXT", "MTEXT"}
MAX_DXF_SIZE = 25 * 1024 * 1024  # 25 MB limit for safety


def classify(layer: str, entity: str, rules: dict[str, tuple[str, ...]] | None = None) -> str:
    layer_str = str(layer or "0")
    entity_str = str(entity or "")
    text = f"{layer_str} {entity_str}".upper().replace(" ", "_").replace("-", "_")
    for category, aliases in (rules or CATEGORIES).items():
        if any(alias.replace("-", "_") in text for alias in aliases):
            return category
    return "other"


def _xy(p: Any) -> list[float]:
    return [float(p[0]), float(p[1])]


def _feature(entity: Any) -> dict[str, Any]:
    kind = entity.dxftype()
    layer = str(entity.dxf.get("layer", "0") or "0")
    cat = classify(layer, kind)
    props: dict[str, Any] = {
        "category": cat,
        "source_layer": layer,
        "source_entity": kind,
        "source_handle": entity.dxf.get("handle"),
        "tactical": cat in TACTICAL,
        "display_name": cat.replace("_", " ").title(),
        "classification_source": "layer_rule" if cat != "other" else "unclassified",
        "confidence": "high" if cat != "other" else "uncertain"
    }
    geom = None
    if kind == "LINE":
        geom = {"type": "LineString", "coordinates": [_xy(entity.dxf.start), _xy(entity.dxf.end)]}
    elif kind in ("LWPOLYLINE", "POLYLINE"):
        if kind == "LWPOLYLINE":
            verts = list(entity.get_points("xyb"))
        else:
            verts = [(*_xy(v.dxf.location), float(v.dxf.get("bulge", 0))) for v in entity.vertices]
        coords = [_xy(v) for v in verts]
        props["closed"] = bool(entity.closed if kind == "LWPOLYLINE" else entity.is_closed)
        props["bulges"] = [float(v[2]) for v in verts]
        if any(abs(float(v[2])) > 1e-12 for v in verts):
            props["has_bulges"] = True
        geom = (
            {"type": "Polygon", "coordinates": [coords + ([coords[0]] if props["closed"] and coords and coords[-1] != coords[0] else [])]}
            if props["closed"] and len(coords) >= 3
            else {"type": "LineString", "coordinates": coords}
        )
    elif kind == "CIRCLE":
        geom = {"type": "Point", "coordinates": _xy(entity.dxf.center)}
        props["cad_geometry"] = "Circle"
        props["radius"] = float(entity.dxf.radius)
    elif kind == "ARC":
        geom = {"type": "Point", "coordinates": _xy(entity.dxf.center)}
        props["cad_geometry"] = "Arc"
        props["radius"] = float(entity.dxf.radius)
        props["start_angle"] = float(entity.dxf.start_angle)
        props["end_angle"] = float(entity.dxf.end_angle)
    elif kind == "POINT":
        geom = {"type": "Point", "coordinates": _xy(entity.dxf.location)}
    elif kind == "TEXT":
        geom = {"type": "Point", "coordinates": _xy(entity.dxf.insert)}
        props.update(text=str(entity.dxf.get("text", "")), height=float(entity.dxf.get("height", 2.5)), rotation=float(entity.dxf.get("rotation", 0)), cad_geometry="Text")
    elif kind == "MTEXT":
        geom = {"type": "Point", "coordinates": _xy(entity.dxf.insert)}
        props.update(text=str(entity.text if hasattr(entity, "text") else ""), height=float(entity.dxf.get("char_height", 2.5)), cad_geometry="MText")
    elif kind == "INSERT":
        geom = {"type": "Point", "coordinates": _xy(entity.dxf.insert)}
        props.update(block_name=str(entity.dxf.get("name", "")), xscale=float(entity.dxf.get("xscale", 1)), yscale=float(entity.dxf.get("yscale", 1)), rotation=float(entity.dxf.get("rotation", 0)), cad_geometry="Insert")
    return {"type": "Feature", "geometry": geom, "properties": props}


def parse_dxf(data: bytes) -> dict[str, Any]:
    if not data:
        raise ValueError("DXF file is empty.")
    if len(data) > MAX_DXF_SIZE:
        raise ValueError(f"DXF file exceeds maximum allowed size of {MAX_DXF_SIZE // (1024*1024)} MB.")
    
    source_text = data[:8192].decode("utf-8", errors="replace")
    if "SECTION" not in source_text.upper():
        raise ValueError("Input is not a readable ASCII DXF file (SECTION marker not found in header).")
    try:
        doc, auditor = recover.read(io.BytesIO(data))
    except Exception as exc:
        raise ValueError(f"Unable to read DXF: {exc}") from exc
    entities = list(doc.modelspace())
    features = [_feature(e) for e in entities]
    unsupported = Counter(e.dxftype() for e in entities if e.dxftype() not in SUPPORTED)
    coords = [c for f in features if f["geometry"] for c in _coordinates(f["geometry"]) if len(c) >= 2]
    bbox = [min(c[0] for c in coords), min(c[1] for c in coords), max(c[0] for c in coords), max(c[1] for c in coords)] if coords else None
    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "coordinate_system": "Local DXF coordinates; no geographic transform applied",
            "units_code": int(doc.header.get("$INSUNITS", 0)),
            "entity_count": len(entities),
            "category_counts": dict(Counter(f["properties"]["category"] for f in features)),
            "layer_counts": dict(Counter(str(e.dxf.get("layer", "0") or "0") for e in entities)),
            "entity_counts": dict(Counter(e.dxftype() for e in entities)),
            "bbox": bbox,
            "unsupported": dict(unsupported),
            "unsupported_count": sum(unsupported.values()),
            "recovery_errors": len(auditor.errors) if auditor else 0,
        },
    }


def _coordinates(geometry: dict[str, Any]) -> list[list[float]]:
    c = geometry.get("coordinates")
    if not c:
        return []
    if geometry["type"] == "Point":
        return [c]
    if geometry["type"] == "LineString":
        return c
    if geometry["type"] == "Polygon":
        return [p for ring in c for p in ring]
    return []


def reconstruct(collection: dict[str, Any]) -> bytes:
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    for feature in collection.get("features", []):
        g, p = feature.get("geometry"), feature.get("properties", {})
        if not g:
            continue
        layer = str(p.get("source_layer", "0") or "0")
        if layer not in doc.layers:
            doc.layers.new(layer)
        typ, c = g["type"], g["coordinates"]
        src = p.get("source_entity")
        if src == "CIRCLE" or p.get("cad_geometry") == "Circle":
            msp.add_circle(c, float(p.get("radius", 0)), dxfattribs={"layer": layer})
        elif src == "ARC" or p.get("cad_geometry") == "Arc":
            msp.add_arc(c, float(p.get("radius", 0)), float(p.get("start_angle", 0)), float(p.get("end_angle", 0)), dxfattribs={"layer": layer})
        elif src == "INSERT" or p.get("cad_geometry") == "Insert":
            name = str(p.get("block_name", ""))
            if name and name in doc.blocks:
                msp.add_blockref(name, c, dxfattribs={"layer": layer, "xscale": p.get("xscale", 1), "yscale": p.get("yscale", 1), "rotation": p.get("rotation", 0)})
            else:
                msp.add_point(c, dxfattribs={"layer": layer})
        elif src in ("TEXT", "MTEXT") or p.get("cad_geometry") in ("Text", "MText"):
            if p.get("cad_geometry") == "MText" or src == "MTEXT":
                msp.add_mtext(str(p.get("text", "")), dxfattribs={"layer": layer, "insert": c, "char_height": p.get("height", 2.5)})
            else:
                msp.add_text(str(p.get("text", "")), dxfattribs={"layer": layer, "insert": c, "height": p.get("height", 2.5), "rotation": p.get("rotation", 0)})
        elif src == "POINT":
            msp.add_point(c, dxfattribs={"layer": layer})
        elif typ == "LineString":
            pts = c
            if src == "LINE" and len(pts) == 2:
                msp.add_line(pts[0], pts[1], dxfattribs={"layer": layer})
            else:
                bulges = p.get("bulges", [])
                msp.add_lwpolyline([(pt[0], pt[1], 0, 0, bulges[i] if i < len(bulges) else 0) for i, pt in enumerate(pts)], dxfattribs={"layer": layer}, format="xyseb")
        elif typ == "Polygon":
            ring = c[0]
            if len(ring) > 1 and ring[0] == ring[-1]:
                ring = ring[:-1]
            bulges = p.get("bulges", [])
            msp.add_lwpolyline([(pt[0], pt[1], 0, 0, bulges[i] if i < len(bulges) else 0) for i, pt in enumerate(ring)], close=True, dxfattribs={"layer": layer}, format="xyseb")
        elif typ == "Point":
            msp.add_point(c, dxfattribs={"layer": layer})
    out = io.StringIO()
    doc.write(out)
    return out.getvalue().encode("utf-8")


def validate(original: dict[str, Any], reconstructed: dict[str, Any]) -> dict[str, Any]:
    def sig(f):
        p, g = f["properties"], f["geometry"]
        return (
            p.get("category"),
            p.get("source_layer"),
            json.dumps(g, sort_keys=True),
            tuple(p.get("bulges", [])),
            p.get("closed"),
            p.get("radius"),
            p.get("start_angle"),
            p.get("end_angle"),
            p.get("text"),
            p.get("height"),
            p.get("rotation"),
            p.get("block_name"),
        )

    a, b = Counter(map(sig, original["features"])), Counter(map(sig, reconstructed["features"]))
    missing, extra = sum((a - b).values()), sum((b - a).values())
    category_a = Counter(f["properties"].get("category", "other") for f in original["features"])
    category_b = Counter(f["properties"].get("category", "other") for f in reconstructed["features"])
    catmis = sum((category_a - category_b).values()) + sum((category_b - category_a).values())
    layer_a = Counter(str(f["properties"].get("source_layer", "0") or "0") for f in original["features"])
    layer_b = Counter(str(f["properties"].get("source_layer", "0") or "0") for f in reconstructed["features"])
    layermis = sum((layer_a - layer_b).values()) + sum((layer_b - layer_a).values())
    coords_a = [pt for f in original["features"] if f["geometry"] for pt in _coordinates(f["geometry"])]
    coords_b = [pt for f in reconstructed["features"] if f["geometry"] for pt in _coordinates(f["geometry"])]
    deviations = [math.dist(x, y) for x, y in zip(coords_a, coords_b)]
    max_dev = max(deviations, default=0.0)
    bbox_a, bbox_b = original["metadata"].get("bbox"), reconstructed["metadata"].get("bbox")
    bbox_diff = max((abs(x - y) for x, y in zip(bbox_a, bbox_b)), default=0.0) if bbox_a and bbox_b else (0.0 if bbox_a == bbox_b else None)
    unsupported = original["metadata"].get("unsupported_count", 0)
    entity_type_mismatches = sum(
        1 for x, y in zip(original["features"], reconstructed["features"])
        if x["properties"].get("source_entity") != y["properties"].get("source_entity")
    )
    recovery_errors = original["metadata"].get("recovery_errors", 0)
    passed = missing == 0 and extra == 0 and max_dev <= 1e-8 and unsupported == 0 and recovery_errors == 0 and bbox_diff is not None and bbox_diff <= 1e-8
    status = "PASSED" if passed else "WARNING" if missing == 0 and max_dev <= 1e-6 else "FAILED"
    return {
        "status": status,
        "original_entity_count": original["metadata"]["entity_count"],
        "reconstructed_entity_count": reconstructed["metadata"]["entity_count"],
        "missing_entities": missing,
        "extra_entities": extra,
        "maximum_coordinate_deviation": max_dev,
        "average_coordinate_deviation": sum(deviations) / len(deviations) if deviations else 0.0,
        "bbox_max_difference": bbox_diff,
        "category_mismatches": catmis,
        "layer_mismatches": layermis,
        "entity_type_mismatches": entity_type_mismatches,
        "original_category_counts": original["metadata"].get("category_counts", {}),
        "reconstructed_category_counts": reconstructed["metadata"].get("category_counts", {}),
        "original_layer_counts": original["metadata"].get("layer_counts", {}),
        "reconstructed_layer_counts": reconstructed["metadata"].get("layer_counts", {}),
        "unsupported_entity_count": unsupported,
        "recovery_error_count": recovery_errors,
        "unsupported_entities": original["metadata"].get("unsupported", {}),
        "message": "Measured against supported entity geometry and semantics; compatible CAD entity substitutions are counted, and unsupported source entities or DXF recovery errors prevent PASSED.",
    }
