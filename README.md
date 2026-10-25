# PlanOps — CAD-to-Tactical Translator

PlanOps turns a DXF floor plan into a semantic GeoJSON feature collection, presents the complete drawing and a filtered firefighter view, reconstructs DXF from the complete collection, and reports measured round-trip differences.

> This is a buildathon prototype and is not a certified life-safety or emergency-response system. It must not be used as the sole source of information during real emergency operations.

## Architecture

```text
DXF upload → ezdxf parser → classified complete GeoJSON → Full / Tactical display
                                          ↓
                         complete GeoJSON → DXF reconstruction → parse → fidelity report
```

FastAPI serves the conversion API and static dashboard. DXF parsing and reconstruction use `ezdxf`. The browser draws the plan on a canvas; category visibility and Tactical View are display predicates only. They do not edit, remove, or replace features in the complete FeatureCollection. Both GeoJSON export and DXF reconstruction consume the complete in-memory collection. Classification aliases and tactical categories are kept in `app/classification.json` so they can be extended without changing parser logic.

Project layout:

```text
app/            API, DXF/GeoJSON conversion, classification rules
web/            static dashboard, canvas renderer, styles
tests/          conversion, filtering, fixture, and API tests
fixtures/       five synthetic DXFs
scripts/        fixture generator and build/archive command
outputs/        packaged ZIP produced by the build command
```

## Conversion and classification

Each GeoJSON Feature carries its geometry and source semantics (`category`, `source_layer`, `source_entity`, handle, display name, and tactical flag). CAD coordinates remain local X/Y values; the parser records `$INSUNITS` and does not interpret them as longitude/latitude. No georeferencing is inferred.

Example feature:

```json
{
  "type": "Feature",
  "geometry": { "type": "LineString", "coordinates": [[0, 0], [100, 0]] },
  "properties": {
    "category": "wall",
    "source_layer": "A-WALL",
    "source_entity": "LINE",
    "source_handle": "2A",
    "tactical": true,
    "display_name": "Wall"
  }
}
```

The full document is a GeoJSON `FeatureCollection` with project metadata alongside `features`. A feature with a recognized but unsupported entity type remains in the collection with source metadata and a null geometry, while the metadata reports unsupported counts by entity type.

Layer and entity names are classified case-insensitively using aliases for walls, doors, stairs, exits, entrances, hydrants, extinguishers, sprinklers, fire alarms, fire-safety features, hazards, furniture, electrical, plumbing, dimensions, and annotations. Unknown entities become `other`; the application does not infer meaning from geometry alone.

## Views

- **Full View** draws every extracted model-space feature.
- **Firefighter Tactical View** draws features marked tactical: structural walls/barriers, doors, emergency exits, stairs, entrances, hydrants, extinguishers, sprinklers, alarms, other fire-safety equipment, and hazards.
- Category visibility controls only affect the display. The dashboard states that underlying data is preserved.

## Supported conversion model

Supported source entities include `LINE`, `LWPOLYLINE`, `POLYLINE`, `CIRCLE`, `ARC`, `POINT`, `TEXT`, and `MTEXT`. Lines, polylines, closed polygon rings, circles, arcs, points and text have reconstruction mappings. Polyline bulges are retained as bulge metadata and written back on reconstructed polylines. INSERT references are represented by their insertion point and block name, but block definitions are not carried in this prototype; INSERT entities are counted as unsupported and cannot receive a passing fidelity result. The parser includes model-space entities; paperspace, nested block contents, XDATA, dimensions, hatches, splines, proxies, and many advanced CAD features are not fully represented.

The application counts unsupported model-space entity types and includes them in the fidelity report. Reconstruction cannot recreate unsupported source entities; that is reported as missing data and prevents a `PASSED` outcome. A `PASSED` report means the supported comparison criteria matched for this conversion model. It does not mean arbitrary DXF is lossless.

## Fidelity report

The validator reparses source DXF and reconstructed DXF and reports source/reconstructed entity counts, missing/extra signatures, max and average coordinate deviation, bounding-box delta, category and layer mismatch counts and distributions, entity type changes, DXF recovery errors, and unsupported entity count/type breakdown. The status is derived from these measurements: `PASSED` for matching supported data with no unsupported entities, `WARNING` for limited deviation without missing features, and `FAILED` for larger differences. It ignores textual DXF formatting differences.

## Sample fixtures

`fixtures/` contains five synthetic DXF drawings: office, hospital, school, apartment, and commercial. They were generated specifically for this repository by `scripts/make_fixtures.py`; they are not copied from external building plans and have no third-party source/license. Fixture generation includes architectural geometry, classified elements, text, and a hatch case for unsupported reporting.

## Setup

Requires Python 3.10 or newer. From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python scripts/make_fixtures.py
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000`. Upload a DXF, inspect features by selecting them on the canvas, toggle Full/Tactical modes and categories, export complete GeoJSON or reconstructed DXF, then run round-trip validation.

## Tests

Run with `python -m pytest`. The suite covers API upload/validation/reconstruction, invalid input, aliases, local coordinate preservation, synthetic fixture parsing, reconstruction and reparsing, unsupported entity reporting, bulges, and the critical non-destructive filter case (25 displayed from 100 complete features, then 100 reconstructed).

Create or refresh the five original synthetic samples with `python scripts/make_fixtures.py`. Run `python scripts/build.py` to compile the backend, check required files and fixtures, and package a project ZIP in `outputs/`.
