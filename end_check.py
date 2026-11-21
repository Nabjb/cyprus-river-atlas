"""Find where every river and stream ends: in the sea, in another waterway, or nowhere.

In OpenStreetMap a waterway is drawn in the direction the water flows, so the
LAST node of a way is its downstream end. Pieces that touch share the same node.

For each river/stream piece, its last node is classified as:
- sea         the node is on the coastline (the river reaches the sea)
- connected   the node is shared with another waterway (it flows into it)
- near_sea    not connected, but within NEAR_M metres of the coastline
- near_water  not connected, but within NEAR_M metres of another waterway
              (often a culvert or a small gap, like the Straikka or Emporiou street)
- nowhere     not connected and nothing close: the waterway just stops

Writes data/end_check.csv (one row per piece that does not connect) and prints a summary.
Limitation: lakes and reservoirs are not loaded yet, so a stream that ends in a
reservoir is counted as "near_water"/"nowhere" here.
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

    def add(self, lat, lon, node_id):
        self.cells[(int(lat / CELL), int(lon / CELL))].append((lat, lon, node_id))

    def nearest(self, lat, lon, ignore=()):
        best = (math.inf, None)
        ci, cj = int(lat / CELL), int(lon / CELL)
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for plat, plon, node_id in self.cells.get((ci + di, cj + dj), ()):
                    if node_id in ignore:
                        continue
                    d = distance_m(lat, lon, plat, plon)
                    if d < best[0]:
                        best = (d, node_id)
        return best


def main():
    waterways = load("data/waterways_raw.json")
    others = load("data/other_waterways_raw.json")
    coast = load("data/coastline_raw.json")

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

    order = ["sea", "connected", "near_sea", "near_water", "nowhere"]
    labels = {
        "sea": "reach the sea",
        "connected": "flow into another waterway",
        "near_sea": f"stop within {NEAR_M} m of the coast",
        "near_water": f"stop within {NEAR_M} m of another waterway",
        "nowhere": "stop with nothing nearby",
    }
    print("WHERE DO THE PIECES END? (last node of each way)")
    for kind in ("river", "stream"):
        total = sum(counts[kind].values())
        print(f"\n  {kind}s ({total} pieces)")
        for category in order:
            n = counts[kind][category]
            print(f"    {n:6}  {labels[category]} ({n / total:.1%})")

    named_dead = Counter(r["category"] for r in rows if r["name"])
    print(f"\nNamed pieces that do not connect: {sum(named_dead.values())}")
    for category in order[2:]:
        print(f"    {named_dead[category]:6}  {labels[category]}")

    rows.sort(key=lambda r: (order.index(r["category"]), r["waterway"] != "river", r["name"] == ""))
    with open("data/end_check.csv", "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nSaved {len(rows)} pieces that do not connect to data/end_check.csv")


if __name__ == "__main__":
    main()
