"""Dedicated Floor-Plan Routing and Pathfinding Module.

Constructs a navigable floor-plan graph respecting building geometry,
walls, doorways, blocked passages, and hazard zones.
Uses A* with an admissible Euclidean heuristic and line-of-sight raycasting.
"""
from __future__ import annotations

import heapq
import math
from typing import Any


# ---------------------------------------------------------------------------
# 2D Geometric Primitives & Intersection Helpers
# ---------------------------------------------------------------------------

def dist_2d(p1: tuple[float, float] | list[float], p2: tuple[float, float] | list[float]) -> float:
    return math.hypot(p2[0] - p1[0], p2[1] - p1[1])


def _ccw(A: tuple[float, float], B: tuple[float, float], C: tuple[float, float]) -> float:
    return (C[1] - A[1]) * (B[0] - A[0]) - (B[1] - A[1]) * (C[0] - A[0])


def segments_intersect(
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
    p4: tuple[float, float],
    eps: float = 1e-7,
) -> bool:
    """Check if segment p1-p2 strictly intersects segment p3-p4."""
    d1 = _ccw(p3, p4, p1)
    d2 = _ccw(p3, p4, p2)
    d3 = _ccw(p1, p2, p3)
    d4 = _ccw(p1, p2, p4)

    if ((d1 > eps and d2 < -eps) or (d1 < -eps and d2 > eps)) and \
       ((d3 > eps and d4 < -eps) or (d3 < -eps and d4 > eps)):
        return True

    def on_segment(p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> bool:
        return (
            min(a[0], b[0]) - eps <= p[0] <= max(a[0], b[0]) + eps and
            min(a[1], b[1]) - eps <= p[1] <= max(a[1], b[1]) + eps and
            abs(_ccw(a, b, p)) <= eps
        )

    return (
        on_segment(p1, p3, p4) or on_segment(p2, p3, p4) or
        on_segment(p3, p1, p2) or on_segment(p4, p1, p2)
    )


def point_to_segment_distance(
    px: float, py: float,
    ax: float, ay: float,
    bx: float, by: float,
) -> float:
    """Compute minimum distance from point P to segment AB."""
    abx = bx - ax
    aby = by - ay
    seg_len_sq = abx * abx + aby * aby
    if seg_len_sq < 1e-12:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * abx + (py - ay) * aby) / seg_len_sq
    t = max(0.0, min(1.0, t))
    proj_x = ax + t * abx
    proj_y = ay + t * aby
    return math.hypot(px - proj_x, py - proj_y)


# ---------------------------------------------------------------------------
# Feature Extraction from Semantic GeoJSON
# ---------------------------------------------------------------------------

def _extract_segments_from_coords(coords: list[Any], is_polygon: bool = False) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    segments = []
    if is_polygon:
        for ring in coords:
            for i in range(len(ring) - 1):
                segments.append(((float(ring[i][0]), float(ring[i][1])), (float(ring[i + 1][0]), float(ring[i + 1][1]))))
    else:
        for i in range(len(coords) - 1):
            segments.append(((float(coords[i][0]), float(coords[i][1])), (float(coords[i + 1][0]), float(coords[i + 1][1]))))
    return segments


def extract_routing_features(collection: dict[str, Any]) -> dict[str, Any]:
    """Extract and categorize geometric routing features from a GeoJSON FeatureCollection."""
    features = collection.get("features", [])
    walls: list[dict[str, Any]] = []
    doors: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    hazards: list[dict[str, Any]] = []
    exits: list[dict[str, Any]] = []
    entrances: list[dict[str, Any]] = []
    stairs: list[dict[str, Any]] = []
    elevators: list[dict[str, Any]] = []
    aeds: list[dict[str, Any]] = []

    texts: list[tuple[tuple[float, float], str]] = []
    for f in features:
        geom = f.get("geometry")
        if not geom:
            continue
        p = f.get("properties", {})
        cat = p.get("category", "other").lower()
        layer = str(p.get("source_layer", "")).upper()
        gtype = geom.get("type")
        coords = geom.get("coordinates")

        # Collect text labels for contextual naming
        if cat == "annotation" or p.get("cad_geometry") in ("Text", "MText") or "ANNO" in layer or "TEXT" in layer:
            txt = str(p.get("text", "")).strip()
            if txt and gtype == "Point" and coords:
                texts.append(((float(coords[0]), float(coords[1])), txt))

        # 1. Walls
        if cat == "wall" or "WALL" in layer or "BARRIER" in layer:
            if gtype == "LineString":
                segs = _extract_segments_from_coords(coords, False)
                walls.append({"segments": segs, "properties": p})
            elif gtype == "Polygon":
                segs = _extract_segments_from_coords(coords, True)
                walls.append({"segments": segs, "properties": p})

        # 2. Doors
        elif cat == "door" or "DOOR" in layer:
            radius = float(p.get("radius", 0))
            if gtype == "Point":
                doors.append({
                    "center": (float(coords[0]), float(coords[1])),
                    "radius": radius if radius > 0 else 500.0,
                    "properties": p,
                })
            elif gtype in ("LineString", "Polygon"):
                pts = coords if gtype == "LineString" else coords[0]
                if pts:
                    cx = sum(pt[0] for pt in pts) / len(pts)
                    cy = sum(pt[1] for pt in pts) / len(pts)
                    r = max(dist_2d((cx, cy), (pt[0], pt[1])) for pt in pts)
                    doors.append({
                        "center": (cx, cy),
                        "radius": max(r, 500.0),
                        "properties": p,
                    })

        # 3. Blocked Areas
        elif cat == "blocked" or any(k in layer for k in ("BLOCK", "OBSTRUCT", "BARRICADE")):
            if gtype == "Point":
                radius = float(p.get("radius", 600.0))
                blocked.append({
                    "type": "point",
                    "center": (float(coords[0]), float(coords[1])),
                    "radius": radius,
                    "properties": p,
                })
            else:
                segs = _extract_segments_from_coords(coords, gtype == "Polygon")
                pts = coords if gtype == "LineString" else [pt for ring in coords for pt in ring]
                blocked.append({
                    "type": "geometry",
                    "segments": segs,
                    "points": [(float(x), float(y)) for x, y in pts],
                    "properties": p,
                })

        # 4. Hazards
        elif cat == "hazard" or any(k in layer for k in ("HAZMAT", "HAZARD", "DANGER")):
            radius = float(p.get("radius", 1000.0))
            if gtype == "Point":
                hazards.append({
                    "type": "point",
                    "center": (float(coords[0]), float(coords[1])),
                    "radius": radius if radius > 0 else 1000.0,
                    "properties": p,
                })
            else:
                pts = coords if gtype == "LineString" else [pt for ring in coords for pt in ring]
                cx = sum(pt[0] for pt in pts) / len(pts) if pts else 0.0
                cy = sum(pt[1] for pt in pts) / len(pts) if pts else 0.0
                r = max(dist_2d((cx, cy), (pt[0], pt[1])) for pt in pts) if pts else radius
                hazards.append({
                    "type": "geometry",
                    "center": (cx, cy),
                    "radius": max(r, 1000.0),
                    "points": [(float(x), float(y)) for x, y in pts],
                    "properties": p,
                })

        # 5. Emergency Exits
        elif cat == "emergency_exit" or any(k in layer for k in ("EXIT", "FIRE_EXIT", "EGRESS")):
            if gtype == "Point":
                pt = (float(coords[0]), float(coords[1]))
            else:
                pts = coords if gtype == "LineString" else coords[0]
                pt = (sum(x[0] for x in pts) / len(pts), sum(x[1] for x in pts) / len(pts))
            exits.append({
                "center": pt,
                "label": p.get("display_name", "Emergency Exit"),
                "handle": p.get("source_handle", "EXIT"),
                "layer": layer,
                "properties": p,
            })

        # 6. Entrances
        elif cat == "entrance" or any(k in layer for k in ("ENTRY", "ENTRANCE")):
            if gtype == "Point":
                pt = (float(coords[0]), float(coords[1]))
            else:
                pts = coords if gtype == "LineString" else coords[0]
                pt = (sum(x[0] for x in pts) / len(pts), sum(x[1] for x in pts) / len(pts))
            entrances.append({
                "center": pt,
                "label": p.get("display_name", "Building Entrance"),
                "handle": p.get("source_handle", "ENTRANCE"),
                "layer": layer,
                "properties": p,
            })

        # 7. Stairs
        elif cat == "stair" or "STAIR" in layer:
            if gtype == "Point":
                pt = (float(coords[0]), float(coords[1]))
            else:
                pts = coords if gtype == "LineString" else coords[0]
                pt = (sum(x[0] for x in pts) / len(pts), sum(x[1] for x in pts) / len(pts))
            stairs.append({
                "center": pt,
                "label": p.get("display_name", "Stairs"),
                "handle": p.get("source_handle", "STAIR"),
                "layer": layer,
                "properties": p,
            })

        # 8. Elevators
        elif cat == "elevator" or "ELEV" in layer or "LIFT" in layer:
            if gtype == "Point":
                pt = (float(coords[0]), float(coords[1]))
            else:
                pts = coords if gtype == "LineString" else coords[0]
                pt = (sum(x[0] for x in pts) / len(pts), sum(x[1] for x in pts) / len(pts))
            elevators.append({
                "center": pt,
                "label": p.get("display_name", "Elevator"),
                "handle": p.get("source_handle", "ELEV"),
                "layer": layer,
                "properties": p,
            })

        # 9. AEDs
        elif cat == "aed" or "AED" in layer or "DEFIB" in layer:
            if gtype == "Point":
                pt = (float(coords[0]), float(coords[1]))
            else:
                pts = coords if gtype == "LineString" else coords[0]
                pt = (sum(x[0] for x in pts) / len(pts), sum(x[1] for x in pts) / len(pts))
            aeds.append({
                "center": pt,
                "label": p.get("display_name", "AED"),
                "handle": p.get("source_handle", "AED"),
                "layer": layer,
                "properties": p,
            })

    # Associate nearby text annotations with exits for meaningful labels
    for ex in exits:
        for tpos, tstr in texts:
            if dist_2d(ex["center"], tpos) <= 1500.0:
                ex["label"] = f"{tstr} ({ex['label']})"
                break

    meta = collection.get("metadata", {})
    bbox = meta.get("bbox")
    units_code = meta.get("units_code", 0)

    return {
        "walls": walls,
        "doors": doors,
        "blocked": blocked,
        "hazards": hazards,
        "exits": exits,
        "entrances": entrances,
        "stairs": stairs,
        "elevators": elevators,
        "aeds": aeds,
        "bbox": bbox,
        "units_code": units_code,
    }


# ---------------------------------------------------------------------------
# NavGrid Traversability Grid
# ---------------------------------------------------------------------------

class NavGrid:
    """Traversability grid constructed from CAD floor plan geometry."""

    EMPTY = 0
    WALL = 1
    DOORWAY = 2
    BLOCKED = 3

    def __init__(
        self,
        routing_data: dict[str, Any],
        target_resolution: int = 120,
        hazard_mode: str = "avoid",
        hazard_penalty: float = 5.0,
    ):
        self.routing_data = routing_data
        self.hazard_mode = hazard_mode.lower()
        self.hazard_penalty = max(1.0, float(hazard_penalty))
        bbox = routing_data.get("bbox")

        if not bbox or len(bbox) != 4 or bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
            raise ValueError("Floor plan has invalid or zero-area bounding box.")

        self.min_x, self.min_y, self.max_x, self.max_y = [float(v) for v in bbox]
        self.width = self.max_x - self.min_x
        self.height = self.max_y - self.min_y

        # Adaptive cell size
        max_dim = max(self.width, self.height)
        self.cell_size = max_dim / float(target_resolution)

        self.cols = int(math.ceil(self.width / self.cell_size)) + 4
        self.rows = int(math.ceil(self.height / self.cell_size)) + 4

        self.grid = [bytearray(self.cols) for _ in range(self.rows)]
        self.hazard_grid = [bytearray(self.cols) for _ in range(self.rows)]

        self.wall_segments: list[tuple[tuple[float, float], tuple[float, float]]] = []
        for w in routing_data.get("walls", []):
            self.wall_segments.extend(w.get("segments", []))

        self.door_openings = routing_data.get("doors", [])
        self.blocked_items = routing_data.get("blocked", [])
        self.hazard_items = routing_data.get("hazards", [])

        self._rasterize_features()

    def world_to_grid(self, x: float, y: float) -> tuple[int, int]:
        c = int((x - self.min_x) / self.cell_size) + 2
        r = int((y - self.min_y) / self.cell_size) + 2
        c = max(0, min(self.cols - 1, c))
        r = max(0, min(self.rows - 1, r))
        return r, c

    def grid_to_world(self, r: int, c: int) -> tuple[float, float]:
        x = self.min_x + (c - 2 + 0.5) * self.cell_size
        y = self.min_y + (r - 2 + 0.5) * self.cell_size
        return x, y

    def _rasterize_line(self, p1: tuple[float, float], p2: tuple[float, float], value: int, thickness: int = 1):
        r1, c1 = self.world_to_grid(p1[0], p1[1])
        r2, c2 = self.world_to_grid(p2[0], p2[1])

        dr = abs(r2 - r1)
        dc = abs(c2 - c1)
        sr = 1 if r1 < r2 else -1
        sc = 1 if c1 < c2 else -1
        err = dc - dr

        curr_r, curr_c = r1, c1
        while True:
            for tr in range(max(0, curr_r - thickness), min(self.rows, curr_r + thickness + 1)):
                for tc in range(max(0, curr_c - thickness), min(self.cols, curr_c + thickness + 1)):
                    self.grid[tr][tc] = value

            if curr_r == r2 and curr_c == c2:
                break
            e2 = 2 * err
            if e2 > -dr:
                err -= dr
                curr_c += sc
            if e2 < dc:
                err += dc
                curr_r += sr

    def _rasterize_features(self):
        # 1. Rasterize walls
        for p1, p2 in self.wall_segments:
            self._rasterize_line(p1, p2, self.WALL, thickness=0)

        # 2. Clear doorways through walls (verified openings)
        for door in self.door_openings:
            cx, cy = door["center"]
            r_world = max(door["radius"], self.cell_size * 1.5)
            r_cells = int(math.ceil(r_world / self.cell_size))
            dr_center, dc_center = self.world_to_grid(cx, cy)

            for rr in range(max(0, dr_center - r_cells), min(self.rows, dr_center + r_cells + 1)):
                for cc in range(max(0, dc_center - r_cells), min(self.cols, dc_center + r_cells + 1)):
                    wx, wy = self.grid_to_world(rr, cc)
                    if dist_2d((wx, wy), (cx, cy)) <= r_world:
                        self.grid[rr][cc] = self.DOORWAY

        # 3. Rasterize blocked areas (impassable obstacles)
        for b in self.blocked_items:
            if b.get("type") == "point":
                cx, cy = b["center"]
                r_world = b["radius"]
                r_cells = int(math.ceil(r_world / self.cell_size))
                br, bc = self.world_to_grid(cx, cy)
                for rr in range(max(0, br - r_cells), min(self.rows, br + r_cells + 1)):
                    for cc in range(max(0, bc - r_cells), min(self.cols, bc + r_cells + 1)):
                        wx, wy = self.grid_to_world(rr, cc)
                        if dist_2d((wx, wy), (cx, cy)) <= r_world:
                            self.grid[rr][cc] = self.BLOCKED
            else:
                for seg1, seg2 in b.get("segments", []):
                    self._rasterize_line(seg1, seg2, self.BLOCKED, thickness=1)
                pts = b.get("points", [])
                if pts and len(pts) >= 3:
                    min_bx, max_bx = min(p[0] for p in pts), max(p[0] for p in pts)
                    min_by, max_by = min(p[1] for p in pts), max(p[1] for p in pts)
                    r_start, c_start = self.world_to_grid(min_bx, min_by)
                    r_end, c_end = self.world_to_grid(max_bx, max_by)
                    for rr in range(min(r_start, r_end), max(r_start, r_end) + 1):
                        for cc in range(min(c_start, c_end), max(c_start, c_end) + 1):
                            self.grid[rr][cc] = self.BLOCKED

        # 4. Rasterize hazard zones
        for hz in self.hazard_items:
            cx, cy = hz["center"]
            r_world = max(hz["radius"], self.cell_size * 2)
            r_cells = int(math.ceil(r_world / self.cell_size))
            hr, hc = self.world_to_grid(cx, cy)
            for rr in range(max(0, hr - r_cells), min(self.rows, hr + r_cells + 1)):
                for cc in range(max(0, hc - r_cells), min(self.cols, hc + r_cells + 1)):
                    wx, wy = self.grid_to_world(rr, cc)
                    if dist_2d((wx, wy), (cx, cy)) <= r_world:
                        self.hazard_grid[rr][cc] = 1

    def is_traversable(self, r: int, c: int) -> bool:
        if not (0 <= r < self.rows and 0 <= c < self.cols):
            return False
        val = self.grid[r][c]
        if val == self.WALL or val == self.BLOCKED:
            return False
        if self.hazard_mode == "block" and self.hazard_grid[r][c]:
            return False
        return True

    def find_nearest_traversable(self, x: float, y: float, max_radius_cells: int = 25) -> tuple[int, int] | None:
        r, c = self.world_to_grid(x, y)
        if self.is_traversable(r, c):
            return r, c
        for radius in range(1, max_radius_cells + 1):
            candidates = []
            for dr in range(-radius, radius + 1):
                for dc in (-radius, radius):
                    nr, nc = r + dr, c + dc
                    if self.is_traversable(nr, nc):
                        candidates.append((nr, nc))
            for dc in range(-radius + 1, radius):
                for dr in (-radius, radius):
                    nr, nc = r + dr, c + dc
                    if self.is_traversable(nr, nc):
                        candidates.append((nr, nc))
            if candidates:
                candidates.sort(key=lambda cell: dist_2d(self.grid_to_world(cell[0], cell[1]), (x, y)))
                return candidates[0]
        return None

    def line_of_sight_clear(
        self,
        p1: tuple[float, float],
        p2: tuple[float, float],
        ignore_doorways: bool = False,
    ) -> bool:
        """Check if straight-line sight between p1 and p2 is unobstructed."""
        # 1. Check against wall segments
        for w1, w2 in self.wall_segments:
            if segments_intersect(p1, p2, w1, w2):
                if ignore_doorways:
                    int_near_door = False
                    for door in self.door_openings:
                        dc = door["center"]
                        r = door["radius"] + self.cell_size
                        if point_to_segment_distance(dc[0], dc[1], p1[0], p1[1], p2[0], p2[1]) <= r:
                            int_near_door = True
                            break
                    if not int_near_door:
                        return False
                else:
                    return False

        # 2. Check against blocked items
        for b in self.blocked_items:
            if b.get("type") == "point":
                bc = b["center"]
                if point_to_segment_distance(bc[0], bc[1], p1[0], p1[1], p2[0], p2[1]) <= b["radius"]:
                    return False
            else:
                for s1, s2 in b.get("segments", []):
                    if segments_intersect(p1, p2, s1, s2):
                        return False

        # 3. Check hazard crossing policy under block
        if self.hazard_mode == "block":
            for hz in self.hazard_items:
                hc = hz["center"]
                if point_to_segment_distance(hc[0], hc[1], p1[0], p1[1], p2[0], p2[1]) <= hz["radius"]:
                    return False

        return True


# ---------------------------------------------------------------------------
# Pathfinding Algorithm (A*)
# ---------------------------------------------------------------------------

def find_astar_path(
    nav: NavGrid,
    start_cell: tuple[int, int],
    dest_cell: tuple[int, int],
) -> tuple[list[tuple[int, int]], float, float] | None:
    sr, sc = start_cell
    dr, dc = dest_cell

    if (sr, sc) == (dr, dc):
        return [(sr, sc)], 0.0, 0.0

    SQRT2 = math.sqrt(2.0)
    NEIGHBORS = [
        (-1, 0, 1.0), (1, 0, 1.0), (0, -1, 1.0), (0, 1, 1.0),
        (-1, -1, SQRT2), (-1, 1, SQRT2), (1, -1, SQRT2), (1, 1, SQRT2),
    ]

    dest_world = nav.grid_to_world(dr, dc)

    def heuristic(r: int, c: int) -> float:
        wx, wy = nav.grid_to_world(r, c)
        return dist_2d((wx, wy), dest_world)

    start_h = heuristic(sr, sc)
    open_heap: list[tuple[float, float, float, int, int]] = [(start_h, 0.0, 0.0, sr, sc)]
    g_cost: dict[tuple[int, int], float] = {(sr, sc): 0.0}
    g_dist: dict[tuple[int, int], float] = {(sr, sc): 0.0}
    came_from: dict[tuple[int, int], tuple[int, int]] = {}
    closed_set: set[tuple[int, int]] = set()

    found = False
    while open_heap:
        f, current_cost, current_dist, r, c = heapq.heappop(open_heap)
        current = (r, c)

        if current == (dr, dc):
            found = True
            break

        if current in closed_set:
            continue
        closed_set.add(current)

        for d_r, d_c, step_mult in NEIGHBORS:
            nr, nc = r + d_r, c + d_c
            neighbor = (nr, nc)

            if neighbor in closed_set or not nav.is_traversable(nr, nc):
                continue

            # Prevent diagonal corner-cutting through walls
            if d_r != 0 and d_c != 0:
                if not nav.is_traversable(r + d_r, c) or not nav.is_traversable(r, c + d_c):
                    continue

            step_dist = step_mult * nav.cell_size
            step_cost = step_dist

            if nav.hazard_grid[nr][nc]:
                if nav.hazard_mode == "avoid":
                    step_cost *= nav.hazard_penalty
                elif nav.hazard_mode == "block":
                    continue

            tentative_cost = current_cost + step_cost
            tentative_dist = current_dist + step_dist

            if neighbor not in g_cost or tentative_cost < g_cost[neighbor]:
                g_cost[neighbor] = tentative_cost
                g_dist[neighbor] = tentative_dist
                came_from[neighbor] = current
                h = heuristic(nr, nc)
                heapq.heappush(open_heap, (tentative_cost + h, tentative_cost, tentative_dist, nr, nc))

    if not found:
        return None

    curr: tuple[int, int] | None = (dr, dc)
    path_cells = []
    while curr is not None:
        path_cells.append(curr)
        curr = came_from.get(curr)
    path_cells.reverse()

    return path_cells, g_dist[(dr, dc)], g_cost[(dr, dc)]


# ---------------------------------------------------------------------------
# Path Smoothing with Doorway Anchors
# ---------------------------------------------------------------------------

def _smooth_segment(
    nav: NavGrid,
    coords: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    if len(coords) <= 2:
        return coords

    smoothed = [coords[0]]
    i = 0
    n = len(coords)

    while i < n - 1:
        best_j = i + 1
        for j in range(n - 1, i, -1):
            if nav.line_of_sight_clear(coords[i], coords[j], ignore_doorways=False):
                # Ensure no new hazard crossings are introduced when avoiding hazards
                if nav.hazard_mode == "avoid":
                    orig_haz = any(
                        nav.hazard_grid[nav.world_to_grid(coords[k][0], coords[k][1])[0]][
                            nav.world_to_grid(coords[k][0], coords[k][1])[1]
                        ]
                        for k in range(i, j + 1)
                    )
                    shortcut_haz = any(
                        nav.hazard_grid[nav.world_to_grid(
                            coords[i][0] + t * (coords[j][0] - coords[i][0]),
                            coords[i][1] + t * (coords[j][1] - coords[i][1]),
                        )[0]][nav.world_to_grid(
                            coords[i][0] + t * (coords[j][0] - coords[i][0]),
                            coords[i][1] + t * (coords[j][1] - coords[i][1]),
                        )[1]]
                        for t in (0.2, 0.4, 0.6, 0.8)
                    )
                    if shortcut_haz and not orig_haz:
                        continue
                best_j = j
                break
        smoothed.append(coords[best_j])
        i = best_j

    return smoothed


def smooth_path_with_doorways(
    nav: NavGrid,
    raw_coords: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    """Smooth path while strictly anchoring at traversed doorway centers."""
    if len(raw_coords) <= 2:
        return raw_coords

    # Find which doorways were traversed in the raw path
    traversed_door_indices: list[tuple[int, tuple[float, float]]] = []
    seen_doors: set[tuple[float, float]] = set()

    for idx, pt in enumerate(raw_coords):
        for door in nav.door_openings:
            dc = door["center"]
            if dc not in seen_doors and dist_2d(pt, dc) <= max(door["radius"], nav.cell_size * 1.5):
                seen_doors.add(dc)
                traversed_door_indices.append((idx, dc))
                break

    if not traversed_door_indices:
        return _smooth_segment(nav, raw_coords)

    # Partition raw path around doorway anchors
    traversed_door_indices.sort(key=lambda x: x[0])
    anchored_path: list[tuple[float, float]] = []
    last_idx = 0

    for door_idx, door_center in traversed_door_indices:
        sub_coords = raw_coords[last_idx:door_idx + 1] + [door_center]
        smoothed_sub = _smooth_segment(nav, sub_coords)
        if anchored_path:
            anchored_path.extend(smoothed_sub[1:])
        else:
            anchored_path.extend(smoothed_sub)
        last_idx = door_idx

    final_sub = [door_center] + raw_coords[last_idx + 1:]
    smoothed_final = _smooth_segment(nav, final_sub)
    anchored_path.extend(smoothed_final[1:])

    return anchored_path


# ---------------------------------------------------------------------------
# Route Instructions Generator
# ---------------------------------------------------------------------------

def _heading_name(angle_deg: float) -> str:
    dirs = ["East", "North-East", "North", "North-West", "West", "South-West", "South", "South-East"]
    idx = int(round(angle_deg / 45.0)) % 8
    return dirs[idx]


def generate_instructions(
    path: list[tuple[float, float]],
    doors: list[dict[str, Any]],
    hazards: list[dict[str, Any]],
    destination_info: dict[str, Any] | None,
    units_code: int = 0,
) -> list[str]:
    if len(path) < 2:
        return ["Start and destination are at the same location."]

    instructions: list[str] = []
    unit_str = "mm" if units_code == 4 else "m" if units_code == 6 else "units"

    def fmt_dist(d: float) -> str:
        if units_code == 4:
            return f"{d * 0.001:.1f} m ({int(d)} mm)"
        return f"{d:.1f} {unit_str}"

    instructions.append(f"Start at coordinates ({path[0][0]:.1f}, {path[0][1]:.1f}).")

    door_threshold = 800.0 if units_code == 4 else 1.5
    traversed_doors: set[str] = set()

    for i in range(len(path) - 1):
        p1, p2 = path[i], path[i + 1]
        leg_dist = dist_2d(p1, p2)
        if leg_dist < 1e-3:
            continue

        angle = math.degrees(math.atan2(p2[1] - p1[1], p2[0] - p1[0])) % 360
        direction = _heading_name(angle)

        if i == 0:
            turn_desc = f"Proceed {direction}"
        else:
            prev_angle = math.degrees(math.atan2(p1[1] - path[i - 1][1], p1[0] - path[i - 1][0])) % 360
            turn_diff = (angle - prev_angle + 180) % 360 - 180
            if abs(turn_diff) < 20:
                turn_desc = f"Continue straight {direction}"
            elif turn_diff > 0:
                turn_desc = f"Turn left ({direction})"
            else:
                turn_desc = f"Turn right ({direction})"

        door_note = ""
        for d in doors:
            dc = d["center"]
            if point_to_segment_distance(dc[0], dc[1], p1[0], p1[1], p2[0], p2[1]) <= max(d["radius"], door_threshold):
                handle = d.get("properties", {}).get("source_handle", "door")
                if handle not in traversed_doors:
                    traversed_doors.add(handle)
                    layer = d.get("properties", {}).get("source_layer", "DOORS")
                    door_note = f" through doorway [{layer}]"
                    break

        hazard_note = ""
        for hz in hazards:
            hc = hz["center"]
            if point_to_segment_distance(hc[0], hc[1], p1[0], p1[1], p2[0], p2[1]) <= hz["radius"]:
                hazard_note = " ⚠️ CAUTION: Passing through regulated hazard zone"
                break

        instructions.append(f"{turn_desc}{door_note} for {fmt_dist(leg_dist)}.{hazard_note}")

    dest_label = destination_info.get("label", "Destination") if destination_info else "Destination"
    instructions.append(f"Arrive at {dest_label} at ({path[-1][0]:.1f}, {path[-1][1]:.1f}).")
    return instructions


# ---------------------------------------------------------------------------
# High-Level Route Planning Engine
# ---------------------------------------------------------------------------

def plan_route(
    collection: dict[str, Any],
    start: list[float] | tuple[float, float],
    destination: list[float] | tuple[float, float] | str,
    hazard_mode: str = "avoid",
    hazard_penalty: float = 5.0,
    floor: str | None = None,
) -> dict[str, Any]:
    """Primary route-planning function with structural validation and hazard awareness."""
    if not collection or not collection.get("features"):
        return {
            "status": "insufficient_geometry",
            "error": "No floor plan features provided.",
            "path": [],
            "distance": 0.0,
            "cost": 0.0,
            "instructions": [],
            "warnings": ["Insufficient geometry to construct routing graph."],
        }

    routing_data = extract_routing_features(collection)
    walls = routing_data["walls"]

    if len(walls) == 0:
        return {
            "status": "insufficient_geometry",
            "error": "Floor plan contains no detected wall elements. Walkable corridors cannot be constructed.",
            "path": [],
            "distance": 0.0,
            "cost": 0.0,
            "instructions": [],
            "warnings": ["No wall elements found; unable to establish traversable corridor boundaries."],
        }

    if not isinstance(start, (list, tuple)) or len(start) < 2:
        return {
            "status": "invalid_input",
            "error": "Start location must be a valid 2D coordinate [X, Y].",
            "path": [],
            "distance": 0.0,
            "cost": 0.0,
            "instructions": [],
            "warnings": ["Invalid start coordinates provided."],
        }

    start_pt = (float(start[0]), float(start[1]))

    try:
        nav = NavGrid(
            routing_data,
            target_resolution=120,
            hazard_mode=hazard_mode,
            hazard_penalty=hazard_penalty,
        )
    except Exception as exc:
        return {
            "status": "insufficient_geometry",
            "error": f"Failed to construct navigation grid: {exc}",
            "path": [],
            "distance": 0.0,
            "cost": 0.0,
            "instructions": [],
            "warnings": [str(exc)],
        }

    # Strict bounds checking
    margin = nav.cell_size * 2
    if not (nav.min_x - margin <= start_pt[0] <= nav.max_x + margin and nav.min_y - margin <= start_pt[1] <= nav.max_y + margin):
        return {
            "status": "invalid_input",
            "error": f"Start location ({start_pt[0]}, {start_pt[1]}) is outside building bounds.",
            "path": [],
            "distance": 0.0,
            "cost": 0.0,
            "instructions": [],
            "warnings": ["Start point is outside building geometry."],
        }

    start_cell = nav.find_nearest_traversable(start_pt[0], start_pt[1], max_radius_cells=25)
    if not start_cell:
        return {
            "status": "invalid_input",
            "error": "Start location is inside an impassable obstacle or outside building bounds.",
            "path": [],
            "distance": 0.0,
            "cost": 0.0,
            "instructions": [],
            "warnings": ["Start point cannot be mapped to any navigable floor space."],
        }

    # Candidate destinations
    candidate_destinations: list[dict[str, Any]] = []

    if isinstance(destination, str):
        dest_keyword = destination.lower()
        if dest_keyword in ("nearest_exit", "exit", "emergency_exit"):
            for ex in routing_data["exits"]:
                candidate_destinations.append({"type": "exit", "center": ex["center"], "info": ex})
            if not candidate_destinations:
                for en in routing_data["entrances"]:
                    candidate_destinations.append({"type": "entrance", "center": en["center"], "info": en})
            if not candidate_destinations:
                return {
                    "status": "unreachable",
                    "error": "No emergency exits or entrances identified in floor plan.",
                    "path": [],
                    "distance": 0.0,
                    "cost": 0.0,
                    "instructions": [],
                    "warnings": ["Routing requested to nearest exit, but no exits or entrances were found."],
                }
        else:
            return {
                "status": "invalid_input",
                "error": f"Unknown destination keyword '{destination}'. Use coordinates [x, y] or 'nearest_exit'.",
                "path": [],
                "distance": 0.0,
                "cost": 0.0,
                "instructions": [],
                "warnings": [f"Unrecognized destination identifier: {destination}"],
            }
    elif isinstance(destination, (list, tuple)) and len(destination) >= 2:
        dest_pt = (float(destination[0]), float(destination[1]))
        if not (nav.min_x - margin <= dest_pt[0] <= nav.max_x + margin and nav.min_y - margin <= dest_pt[1] <= nav.max_y + margin):
            return {
                "status": "invalid_input",
                "error": f"Destination location ({dest_pt[0]}, {dest_pt[1]}) is outside building bounds.",
                "path": [],
                "distance": 0.0,
                "cost": 0.0,
                "instructions": [],
                "warnings": ["Destination point is outside building geometry."],
            }
        candidate_destinations.append({"type": "point", "center": dest_pt, "info": {"label": "Target Destination"}})
    else:
        return {
            "status": "invalid_input",
            "error": "Destination must be [X, Y] coordinates or 'nearest_exit'.",
            "path": [],
            "distance": 0.0,
            "cost": 0.0,
            "instructions": [],
            "warnings": ["Invalid destination format."],
        }

    # Evaluate candidates with A*
    best_result = None
    best_cost = float("inf")
    candidate_reports = []

    for cand in candidate_destinations:
        cx, cy = cand["center"]
        dest_cell = nav.find_nearest_traversable(cx, cy, max_radius_cells=25)
        if not dest_cell:
            candidate_reports.append({"candidate": cand["info"], "reachable": False, "reason": "No traversable space near target."})
            continue

        astar_res = find_astar_path(nav, start_cell, dest_cell)
        if not astar_res:
            candidate_reports.append({"candidate": cand["info"], "reachable": False, "reason": "No valid route found through corridors."})
            continue

        cell_path, total_dist, total_cost = astar_res
        candidate_reports.append({"candidate": cand["info"], "reachable": True, "distance": total_dist, "cost": total_cost})

        if total_cost < best_cost:
            best_cost = total_cost
            best_result = (cand, cell_path, total_dist, total_cost)

    if not best_result:
        return {
            "status": "unreachable",
            "error": "Destination is unreachable. Confirmed walls or blocked corridors prevent any passage.",
            "path": [],
            "distance": 0.0,
            "cost": 0.0,
            "instructions": [],
            "candidate_reports": candidate_reports,
            "warnings": ["All candidate paths are obstructed by walls, barricades, or configured hazard blocks."],
        }

    chosen_cand, cell_path, raw_dist, raw_cost = best_result

    raw_coords = [start_pt] + [nav.grid_to_world(r, c) for r, c in cell_path] + [chosen_cand["center"]]

    # Smooth path with doorway anchors
    smoothed_coords = smooth_path_with_doorways(nav, raw_coords)

    # Rigorous Wall Intersection Verification
    verified_coords = [smoothed_coords[0]]
    for i in range(len(smoothed_coords) - 1):
        p1, p2 = smoothed_coords[i], smoothed_coords[i + 1]
        if not nav.line_of_sight_clear(p1, p2, ignore_doorways=True):
            sub_cells = [pt for pt in raw_coords if dist_2d(pt, p1) < dist_2d(p2, p1)]
            verified_coords.extend(sub_cells)
        verified_coords.append(p2)

    clean_path: list[list[float]] = []
    for pt in verified_coords:
        if not clean_path or dist_2d(clean_path[-1], pt) > 1e-4:
            clean_path.append([round(pt[0], 2), round(pt[1], 2)])

    final_distance = sum(dist_2d(clean_path[i], clean_path[i + 1]) for i in range(len(clean_path) - 1))
    final_cost = raw_cost if raw_dist < 1e-6 else final_distance * (raw_cost / raw_dist)

    hazards_traversed = []
    for hz in routing_data["hazards"]:
        hc = hz["center"]
        r = hz["radius"]
        for i in range(len(clean_path) - 1):
            if point_to_segment_distance(hc[0], hc[1], clean_path[i][0], clean_path[i][1], clean_path[i + 1][0], clean_path[i + 1][1]) <= r:
                hazards_traversed.append(hz.get("properties", {}).get("source_handle", "hazard"))
                break

    warnings: list[str] = [
        "Calculated from available floor-plan geometry and configured constraints. Not certified for real emergency operations.",
    ]
    if hazards_traversed:
        warnings.append(f"Route traverses caution zone(s) near hazard handle(s): {', '.join(set(hazards_traversed))}.")

    instructions = generate_instructions(
        [tuple(p) for p in clean_path],
        routing_data["doors"],
        routing_data["hazards"],
        chosen_cand.get("info"),
        routing_data["units_code"],
    )

    multi_floor_info = {
        "supported": False,
        "current_floor": "Single-floor floor plan",
        "vertical_connectors": [
            *[{"type": "stair", "coordinates": s.get("center")} for s in routing_data["stairs"]],
            *[{"type": "elevator", "coordinates": e.get("center")} for e in routing_data.get("elevators", [])],
        ],
        "message": "Single-floor routing active. Multi-floor routing requires distinct elevation/floor layers with verified vertical connectors.",
    }

    return {
        "status": "success",
        "path": clean_path,
        "nodes": [
            {"id": "start", "type": "start", "coordinates": [start_pt[0], start_pt[1]], "label": "Start Location"},
            {"id": "dest", "type": chosen_cand["type"], "coordinates": list(chosen_cand["center"]), "label": chosen_cand.get("info", {}).get("label", "Destination")},
        ],
        "distance": round(final_distance, 2),
        "cost": round(final_cost, 2),
        "instructions": instructions,
        "destination_info": chosen_cand.get("info"),
        "hazard_mode": hazard_mode,
        "hazards_traversed": list(set(hazards_traversed)),
        "multi_floor": multi_floor_info,
        "candidate_reports": candidate_reports,
        "warnings": warnings,
        "error": None,
    }
