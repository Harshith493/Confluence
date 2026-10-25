# PlanOps — Firefighter Tactical Floor-Plan & Route Planning System

PlanOps translates architectural CAD (DXF) floor plans into a semantic, response-ready tactical interface for emergency responders. It extracts walls, doorways, blocked passages, hazards, and emergency exits, classifies features using configurable rules, renders an interactive tactical canvas, and calculates geometrically valid, obstacle-aware evacuation and entry paths.

> **Disclaimer:** This is a buildathon prototype and is not a certified life-safety or emergency-response system. It must not be used as the sole source of information during real emergency operations.

---

## 1. System Architecture

```text
               ┌───────────────┐
               │  DXF Upload   │
               └───────┬───────┘
                       │
          ┌────────────▼───────────┐
          │     ezdxf Parser       │
          │ (Entities, BBox, Units)│
          └────────────┬───────────┘
                       │
          ┌────────────▼───────────┐
          │ Semantic Classification│ ◄── app/classification.json
          │  (Walls, Doors, Exits, │
          │   Hazards, Blocked)    │
          └────────────┬───────────┘
                       │
         ┌─────────────┴─────────────┐
         │                           │
┌────────▼────────┐         ┌────────▼────────┐
│  Full View /    │         │ Tactical Route  │
│  Tactical View  │         │ Planning Module │ ◄── A* + Raycast
│ (HTML5 Canvas)  │         │ (app/routing.py)│
└────────┬────────┘         └────────┬────────┘
         │                           │
         │             ┌─────────────┴─────────────┐
         ▼             ▼                           ▼
┌───────────────────────────────┐        ┌───────────────────┐
│ Interactive Frontend Desk     │        │ Round-Trip CAD    │
│ - Pan/Zoom & Canvas Picking   │        │ Fidelity Report   │
│ - Glowing Route Overlay       │        │ (Reconstruction & │
│ - Turn-by-Turn Instructions   │        │  Validation)      │
└───────────────────────────────┘        └───────────────────┘
```

The application runs on Python 3.10+, FastAPI, and `ezdxf`, paired with a responsive browser dashboard built with standard HTML5 Canvas, CSS, and modern JavaScript. No external AI APIs, heavy frontend frameworks, or separate databases are required.

---

## 2. Dedicated Tactical Route Planning Engine (`app/routing.py`)

PlanOps does not calculate routes as straight lines. It constructs a verified navigable graph that strictly respects architectural barriers.

### A. Graph Construction & Walkable Space Extraction
1. **Wall Obstacles**: Structural wall segments (`LINE`, `LWPOLYLINE`, `POLYLINE`, `Polygon`) are extracted and rasterized as impassable barriers on an adaptive 2D traversability grid.
2. **Verified Doorway Openings**: Door entities (`category == "door"` or layer matching `DOOR`) define verified openings through walls. The traversability grid carves out walkable doorway cells within the opening radius ($R_d \ge 500$ mm). Closed walls without doors remain impenetrable.
3. **Impassable Blocked Passages**: Corridors obstructed by debris, barricades, or structural collapse (`category == "blocked"`) are marked as strictly impassable. Blocked areas override doorways and corridors.
4. **Hazard Zones**: Identified hazard entities (`category == "hazard"` or `HAZMAT`) establish caution zones with configurable traversal penalties.

### B. Pathfinding Algorithm (A*)
- **Algorithm**: A* search on an 8-connected grid with diagonal corner-cutting prevention around wall corners.
- **Cost Model**: Normal corridor movement cost equals Euclidean distance. Diagonal step distance is $\sqrt{2} \times \text{cell\_size}$.
- **Admissible Heuristic**: Strict Euclidean distance to destination $h(u) = \sqrt{(x_u - x_{\text{goal}})^2 + (y_u - y_{\text{goal}})^2}$. Since all edge traversal costs are $\ge$ Euclidean distance, $h(u) \le c^*(u, \text{goal})$, guaranteeing admissibility, consistency, and optimal paths.
- **Multiple Candidate Exits**: When routing to `nearest_exit`, the algorithm evaluates all candidate emergency exits and entrances, selecting the reachable exit with the lowest total routing cost.
- **Unreachable Detection**: If a destination is enclosed by solid walls with no door (e.g., an isolated vault) or cut off by blocked corridors, the open set empties and the system returns a clear `status: "unreachable"` response explaining the architectural blockage.

### C. Hazard-Aware Routing Policy
The hazard navigation policy is configurable:
- **`avoid` (default)**: Traversal through hazard zones incurs an increased cost multiplier (configurable, default 5.0x to 10.0x). If a clean alternative bypass exists, the planner automatically chooses the safer longer route. If no alternative exists, it traverses the hazard with an explicit safety warning.
- **`block`**: Hazard zones are treated as strictly impassable obstacles. Any path attempting to cross a hazard is rejected.
- **`ignore`**: Movement cost through hazards is normal (1.0x), choosing the shortest geometric corridor.

### D. Line-of-Sight Raycasting & Doorway Anchoring
Raw grid paths contain step-like 45°/90° movements. PlanOps uses raycasting string-pulling to produce clean, natural human paths:
- Traversed doorways are identified as critical topological route anchors.
- Path legs between anchors are smoothed using strict line-of-sight checks against all wall segments and blocked polygons.
- Every segment is double-checked against wall intersections: any segment intersecting a solid wall outside of a doorway is immediately reverted to fine corridor waypoints. No route ever crosses a wall.

### E. Multi-Floor Routing Limitation
The engine inspects elevation (Z coordinates), floor identifiers, and vertical connectors (`STAIRS`, elevators). In single-floor CAD drawings, PlanOps operates in verified single-floor mode and reports multi-floor routing as a documented limitation without fabricating imaginary floor connections.

---

## 3. Frontend Dashboard Features

The dashboard provides an operational workspace:
- **Interactive Canvas**: Pan (drag), zoom (wheel / buttons), and fit-to-screen (`⌗`).
- **Tactical View Filter**: Highlights structural walls, doors, stairs, hydrants, hazards, and blocked corridors with enhanced contrast and glow.
- **Canvas Coordinate Picking**:
  - Click **"📍 Pick on Canvas"** next to Start or Destination.
  - Click anywhere on the floor plan to set coordinates directly in CAD space.
  - Or choose from the detected Emergency Exits dropdown.
- **Glowing Tactical Route Overlay**:
  - High-visibility glowing route polyline (`#00e5ff`) with waypoint indicators.
  - Green circular badge at `START`.
  - Red circular badge at `EXIT` / `DESTINATION`.
  - Stays precisely anchored during zooming, panning, and window resizing.
- **Route Telemetry & Directions**:
  - Distance displayed in meters and millimeters (e.g., `12.5 m (12,500 mm)`).
  - Tactical cost and reached destination name.
  - Turn-by-turn instructions (e.g., *"Proceed North through doorway [A-DOOR] for 4.2 m"*).
  - Hazard warnings when a route traverses a caution area.
- **Non-Destructive Filtering**: Toggling category visibility in the sidebar adjusts visual layers only; underlying GeoJSON features and the routing graph are never altered.
- **Clear Route**: Instant route reset button.

---

## 4. API Reference

### `POST /api/convert`
Uploads and parses a DXF file into semantic GeoJSON with metadata.
- **Content-Type**: `multipart/form-data`
- **Request**: `file: UploadFile` (max 25 MB)
- **Response**: GeoJSON `FeatureCollection` with metadata (`entity_count`, `category_counts`, `bbox`, `units_code`, `unsupported`).

### `POST /api/route`
Calculates an obstacle-aware route respecting walls, doors, blocked areas, and hazards.
- **Content-Type**: `application/json`
- **Request Schema**:
  ```json
  {
    "collection": { ... },
    "start": [3000.0, 2500.0],
    "destination": "nearest_exit",
    "hazard_mode": "avoid",
    "hazard_penalty": 5.0,
    "floor": null
  }
  ```
  *(Note: `destination` can be `"nearest_exit"` or a 2D coordinate `[X, Y]`)*
- **Response Schema**:
  ```json
  {
    "status": "success",
    "path": [[3000.0, 2500.0], [3000.0, 4000.0], [0.0, 5000.0]],
    "nodes": [
      { "id": "start", "type": "start", "coordinates": [3000.0, 2500.0], "label": "Start Location" },
      { "id": "dest", "type": "exit", "coordinates": [0.0, 5000.0], "label": "EXIT A (Emergency Exit)" }
    ],
    "distance": 4662.28,
    "cost": 4662.28,
    "instructions": [
      "Start at coordinates (3000.0, 2500.0).",
      "Proceed North through doorway [A-DOOR] for 1.5 m (1500 mm).",
      "Turn left (North-West) for 3.2 m (3162 mm).",
      "Arrive at EXIT A (Emergency Exit) at (0.0, 5000.0)."
    ],
    "destination_info": { "center": [0.0, 5000.0], "label": "EXIT A (Emergency Exit)" },
    "hazard_mode": "avoid",
    "hazards_traversed": [],
    "multi_floor": { "supported": false, "message": "Single-floor routing active..." },
    "warnings": [ "Calculated from available floor-plan geometry..." ],
    "error": null
  }
  ```

### `POST /api/validate`
Uploads source DXF, converts to GeoJSON, reconstructs to DXF, parses again, and measures geometric fidelity.
- **Response**: `{"report": { "status": "PASSED" | "WARNING" | "FAILED", ... }, "reconstructed": { ... }}`

### `POST /api/reconstruct`
Reconstructs complete DXF binary from in-memory GeoJSON collection.
- **Response**: Binary `application/dxf` file download.

---

## 5. Buildathon Demo Fixture: Known Geometry (`fixtures/tactical_demo.dxf`)

The test building is a 16 m × 10 m (16,000 × 10,000 mm) facility:
- **Room 1 (Command Office / Start)**: $X \in [1000, 5000], Y \in [1000, 4000]$. West wall at $X=1000$ has no door. Only opening is **Door 1** at $(3000, 4000)$. Start point is inside at $(3000, 2500)$.
- **Central Corridor**: Runs West-East at $Y \in [4000, 6000]$.
- **Blocked Passage**: Debris at $X \in [7000, 8000], Y \in [4000, 6000]$ completely blocks direct central corridor movement.
- **North Bypass**: Corridor at $Y \in [7500, 9000]$ connecting $X=5000$ to $X=11000$. Contains a chemical hazard on layer `HAZMAT` at $(8000, 8250)$ (radius 1000 mm) spanning the corridor.
- **South Bypass**: Clean corridor at $Y \in [500, 1500]$ connecting $X=5500$ to $X=10500$. Free of hazards.
- **Exit A (West Exit)**: Located at $(0, 5000)$ on layer `EMERGENCY_EXIT`.
- **Exit B (East Exit)**: Located at $(16000, 5000)$ on layer `EMERGENCY_EXIT`.
- **Vault (Isolated Room)**: $X \in [1000, 4000], Y \in [7000, 9500]$ with 4 solid walls and no door (proves unreachable handling).

---

## 6. Step-by-Step Buildathon Jury Demo Script

1. **Start the server**:
   ```powershell
   uvicorn app.main:app --reload
   ```
2. **Open the browser**: Navigate to `http://127.0.0.1:8000`.
3. **Upload the demo DXF**: Click **"Upload DXF"** (or drag & drop) and select `fixtures/tactical_demo.dxf`.
4. **Inspect features**: Toggle between **Full View** and **Tactical View**. Note that doors, hydrants, hazards (`HAZMAT`), and blocked areas (`BLOCKED`) are prominently highlighted. Click any wall or door to view its CAD metadata in the inspector.
5. **Switch to Route Planner**: Click **"⚡ Route Planner"** tab in the side panel (or the `⚡` icon on the left rail).
6. **Scenario A — Normal Route via Doorway**:
   - Start: Default preset is Room 1 `(3000, 2500)`.
   - Destination: `⭐ Nearest Reachable Exit (Auto-select)`.
   - Click **"⚡ Calculate Tactical Route"**.
   - **Verification**: The route exits through Door 1 at $(3000, 4000)$ and turns West down the corridor to Exit A $(0, 5000)$. It does *not* penetrate the solid West wall. Distance is ~4.6 m.
7. **Scenario B — Blocked Corridor & Hazard-Aware Rerouting**:
   - Change Destination dropdown to **Exit B** at $(16000, 5000)$.
   - Set Start to $(5000, 5000)$ (or pick on canvas).
   - Set Hazard Policy to **"Avoid Hazards"** (penalty 10x).
   - Click **"⚡ Calculate Tactical Route"**.
   - **Verification**: The central corridor is blocked at $X=7000..8000$. The North bypass has a hazard at $(8000, 8250)$. Because `avoid` is active, the route automatically takes the clean **South Bypass** ($Y < 3000$).
   - Switch Hazard Policy to **"Ignore Hazards"** and recalculate: the route now takes the shorter North bypass directly through the hazard zone, reporting a hazard caution alert.
8. **Scenario C — Unreachable Destination Error Handling**:
   - Click **"📍 Pick on Canvas"** next to Destination.
   - Click inside the isolated **Vault** in the upper left ($X \approx 2500, Y \approx 8250$).
   - Click **"⚡ Calculate Tactical Route"**.
   - **Verification**: Status turns orange/red with a clear error: *"Destination is unreachable. Confirmed walls or blocked corridors prevent any passage."* No invalid path is generated.
9. **Round-Trip Fidelity Check**: Switch back to **Overview** and click **"Run round-trip check"**: status reports `PASSED` with 0 missing entities.

---

## 7. Setup & Testing Commands

### Prerequisites
- Python 3.10+ (tested on Python 3.13)

### Installation
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Refresh Fixtures
```powershell
python scripts/make_fixtures.py
```

### Run Automated Tests
```powershell
pytest
```
*Executes all 23 test cases covering classification, conversion, reconstruction round-tripping, doorways, wall blocking, blocked corridors, hazard penalties, unreachable spaces, multiple exits, and API endpoints.*

### Run Production Build & Archive
```powershell
python scripts/build.py
```
*Compiles Python byte-code, validates required project files, and packages `outputs/planops-cad-to-tactical.zip`.*

### Start Local Server
```powershell
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```
Open `http://127.0.0.1:8000` in your web browser.
