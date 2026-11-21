"""Find where every river and stream ends: in the sea, a lake, another waterway, or nowhere.

In OpenStreetMap a waterway is drawn in the direction the water flows, so the
LAST node of a way is its downstream end. Pieces that touch share the same node.

For each river/stream piece, its last node is classified as:
- sea         the node is on the coastline (the river reaches the sea)
- connected   the node is shared with another waterway (it flows into it)
- lake        the node is inside a lake or reservoir, or within NEAR_M metres of its shore
- near_sea    not connected, but within NEAR_M metres of the coastline
- near_water  not connected, but within NEAR_M metres of another waterway
              (often a culvert or a small gap, like the Straikka or Emporiou street)
- nowhere     not connected and nothing close: the waterway just stops

Writes data/end_check.csv (one row per piece that does not connect) and prints a summary.
"""
import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

NEAR_M = 50          # "almost connects" threshold in metres
CELL = 0.005         # grid cell size in degrees (~500 m) for fast nearest-point search
EARTH_RADIUS_M = 6_371_008.8


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))["elements"]


def distance_m(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    h = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))


class PointGrid:
    """Points bucketed into a grid, so we only compare a point with its neighbours."""

    def __init__(self):
        self.cells = defaultdict(list)

    def add(self, lat, lon, key):
        self.cells[(int(lat / CELL), int(lon / CELL))].append((lat, lon, key))

    def nearest(self, lat, lon, ignore=()):
        best = (math.inf, None)
        ci, cj = int(lat / CELL), int(lon / CELL)
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for plat, plon, key in self.cells.get((ci + di, cj + dj), ()):
                    if key in ignore:
                        continue
                    d = distance_m(lat, lon, plat, plon)
                    if d < best[0]:
                        best = (d, key)
        return best


def join_rings(parts):
    """Join open lines (lists of (lat, lon)) end to end into closed rings."""
    parts = [list(p) for p in parts if len(p) >= 2]
    rings = []
    while parts:
        ring = parts.pop()
        changed = True
        while ring[0] != ring[-1] and changed:
            changed = False
            for i, part in enumerate(parts):
                if part[0] == ring[-1]:
                    ring += part[1:]
                elif part[-1] == ring[-1]:
                    ring += part[::-1][1:]
                elif part[-1] == ring[0]:
                    ring = part + ring[1:]
                elif part[0] == ring[0]:
                    ring = part[::-1] + ring[1:]
                else:
                    continue
                parts.pop(i)
                changed = True
                break
        if ring[0] == ring[-1] and len(ring) >= 4:
            rings.append(ring)
    return rings


def water_rings(water_bodies):
    """Outer rings of every lake/reservoir, as lists of (lat, lon)."""
    rings = []
    for element in water_bodies:
        # River and canal areas are the banks of a waterway, not a lake: a line
        # that stops inside them is still a gap in the river.
        if element.get("tags", {}).get("water") in ("river", "canal"):
            continue
        if element["type"] == "way":
            ring = [(p["lat"], p["lon"]) for p in element.get("geometry", [])]
            if len(ring) >= 4 and ring[0] == ring[-1]:
                rings.append(ring)
        elif element["type"] == "relation":
            outers = [[(p["lat"], p["lon"]) for p in m.get("geometry", [])]
                      for m in element.get("members", [])
                      if m["type"] == "way" and m.get("role") in ("outer", "")]
            rings += join_rings(outers)
    return rings


def inside(lat, lon, ring):
    """Ray casting: is the point inside the closed ring?"""
    result = False
    for (lat1, lon1), (lat2, lon2) in zip(ring, ring[1:]):
        if (lat1 > lat) != (lat2 > lat):
            if lon < lon1 + (lat - lat1) * (lon2 - lon1) / (lat2 - lat1):
                result = not result
    return result


def main():
    waterways = load("data/waterways_raw.json")
    others = load("data/other_waterways_raw.json")
    coast = load("data/coastline_raw.json")
    rings = water_rings(load("data/water_bodies_raw.json"))

    # Which ways use each node (rivers, streams, canals, drains, ditches)
    ways_at_node = defaultdict(set)
    water_grid = PointGrid()
    for way in waterways + others:
        for node_id, point in zip(way["nodes"], way["geometry"]):
            ways_at_node[node_id].add(way["id"])
            water_grid.add(point["lat"], point["lon"], node_id)

    coast_nodes = set()
    coast_grid = PointGrid()
    for way in coast:
        for node_id, point in zip(way["nodes"], way["geometry"]):
            coast_nodes.add(node_id)
            coast_grid.add(point["lat"], point["lon"], node_id)

    # Lakes: their shore points (for "within NEAR_M") and bounding boxes (to test "inside")
    lake_grid = PointGrid()
    lake_boxes = []
    for index, ring in enumerate(rings):
        for lat, lon in ring:
            lake_grid.add(lat, lon, index)
        lats, lons = [p[0] for p in ring], [p[1] for p in ring]
        lake_boxes.append((min(lats), max(lats), min(lons), max(lons)))

    def in_lake(lat, lon):
        if lake_grid.nearest(lat, lon)[0] <= NEAR_M:
            return True
        return any(box[0] <= lat <= box[1] and box[2] <= lon <= box[3] and inside(lat, lon, rings[i])
                   for i, box in enumerate(lake_boxes))

    rows = []
    counts = {"river": Counter(), "stream": Counter()}
    for way in waterways:
        kind = way["tags"]["waterway"]
        end = way["nodes"][-1]
        lat, lon = way["geometry"][-1]["lat"], way["geometry"][-1]["lon"]

        if end in coast_nodes:
            category = "sea"
        elif len(ways_at_node[end]) > 1:
            category = "connected"
        elif in_lake(lat, lon):
            category = "lake"
        else:
            own_nodes = set(way["nodes"])
            d_sea, _ = coast_grid.nearest(lat, lon)
            d_water, _ = water_grid.nearest(lat, lon, ignore=own_nodes)
            if d_sea <= NEAR_M:
                category = "near_sea"
            elif d_water <= NEAR_M:
                category = "near_water"
            else:
                category = "nowhere"
            rows.append({
                "way_id": way["id"],
                "waterway": kind,
                "name": way["tags"].get("name", ""),
                "end_node": end,
                "category": category,
                "nearest_water_m": round(d_water) if d_water < math.inf else "",
                "nearest_coast_m": round(d_sea) if d_sea < math.inf else "",
                "lat": round(lat, 6),
                "lon": round(lon, 6),
                "osm_node": f"https://www.openstreetmap.org/node/{end}",
            })
        counts[kind][category] += 1

    order = ["sea", "connected", "lake", "near_sea", "near_water", "nowhere"]
    labels = {
        "sea": "reach the sea",
        "connected": "flow into another waterway",
        "lake": "end in a lake or reservoir",
        "near_sea": f"stop within {NEAR_M} m of the coast",
        "near_water": f"stop within {NEAR_M} m of another waterway",
        "nowhere": "stop with nothing nearby",
    }
    print(f"Lakes and reservoirs loaded: {len(rings)} shapes\n")
    print("WHERE DO THE PIECES END? (last node of each way)")
    for kind in ("river", "stream"):
        total = sum(counts[kind].values())
        print(f"\n  {kind}s ({total} pieces)")
        for category in order:
            n = counts[kind][category]
            print(f"    {n:6}  {labels[category]} ({n / total:.1%})")

    named_dead = Counter(r["category"] for r in rows if r["name"])
    print(f"\nNamed pieces that do not connect: {sum(named_dead.values())}")
    for category in order[3:]:
        print(f"    {named_dead[category]:6}  {labels[category]}")

    rows.sort(key=lambda r: (order.index(r["category"]), r["waterway"] != "river", r["name"] == ""))
    with open("data/end_check.csv", "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nSaved {len(rows)} pieces that do not connect to data/end_check.csv")


if __name__ == "__main__":
    main()
