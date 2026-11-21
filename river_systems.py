"""Join the pieces into whole river systems: one system per river mouth.

Assumptions (the "characteristics A, B, C" of a river in this project):
A. A river system is every OpenStreetMap waterway (river, stream, canal, drain,
   ditch) whose water ends at one mouth on the coastline, following the pieces
   through the nodes they share.
B. Water flows in the direction each way is drawn (the OSM convention).
C. A river that ends in a lake or reservoir continues from the waterways that
   start in that lake (rivers pass through their dams).
D. The length of a river is its longest flow path from any source to the mouth.
   The network length is the sum of every piece in the system.
E. Gaps are NOT bridged, even small ones (OSM's "map reality" rule): a stream
   that stops 30 m short of a river is not part of that river's system.

Writes data/river_systems.csv and prints a summary.
"""
import csv
import json
import math
from collections import Counter, defaultdict, deque
from pathlib import Path

from end_check import NEAR_M, PointGrid, distance_m, inside, load, water_rings


def main():
    waterways = load("data/waterways_raw.json")
    others = load("data/other_waterways_raw.json")
    coast = load("data/coastline_raw.json")
    rings = water_rings(load("data/water_bodies_raw.json"))
    all_ways = waterways + others
    way_by_id = {w["id"]: w for w in all_ways}

    # Flow graph between nodes: preds[b] = [(a, metres, way_id)] for every segment a -> b
    preds = defaultdict(list)
    coords = {}
    ways_at_node = defaultdict(set)
    for way in all_ways:
        nodes, geometry = way["nodes"], way["geometry"]
        for node_id, point in zip(nodes, geometry):
            coords[node_id] = (point["lat"], point["lon"])
            ways_at_node[node_id].add(way["id"])
        for (a, pa), (b, pb) in zip(zip(nodes, geometry), zip(nodes[1:], geometry[1:])):
            preds[b].append((a, distance_m(pa["lat"], pa["lon"], pb["lat"], pb["lon"]), way["id"]))

    # Rule C: link waterways that end in a lake to waterways that start in the same lake
    lake_grid = PointGrid()
    for index, ring in enumerate(rings):
        for lat, lon in ring:
            lake_grid.add(lat, lon, index)
    box_cells = defaultdict(list)
    for index, ring in enumerate(rings):
        lats, lons = [p[0] for p in ring], [p[1] for p in ring]
        for i in range(int(min(lats) / 0.005), int(max(lats) / 0.005) + 1):
            for j in range(int(min(lons) / 0.005), int(max(lons) / 0.005) + 1):
                box_cells[(i, j)].append(index)

    def lake_of(node_id):
        lat, lon = coords[node_id]
        d, index = lake_grid.nearest(lat, lon)
        if d <= NEAR_M:
            return index
        for index in box_cells.get((int(lat / 0.005), int(lon / 0.005)), ()):
            if inside(lat, lon, rings[index]):
                return index
        return None

    lake_ends, lake_starts = defaultdict(set), defaultdict(set)
    for way in all_ways:
        first, last = way["nodes"][0], way["nodes"][-1]
        if len(ways_at_node[last]) == 1:
            lake = lake_of(last)
            if lake is not None:
                lake_ends[lake].add(last)
        if len(ways_at_node[first]) == 1:
            lake = lake_of(first)
            if lake is not None:
                lake_starts[lake].add(first)
    lake_links = 0
    for lake, ends in lake_ends.items():
        for start in lake_starts.get(lake, ()):
            for end in ends:
                if start != end:
                    preds[start].append((end, distance_m(*coords[end], *coords[start]), None))
                    lake_links += 1

    # Mouths: downstream ends that are on the coastline
    coast_nodes = {n for way in coast for n in way["nodes"]}
    mouths = sorted({w["nodes"][-1] for w in all_ways if w["nodes"][-1] in coast_nodes})

    # Walk upstream from every mouth; mouths whose areas overlap belong to one system
    owner = {}
    parent = {m: m for m in mouths}

    def find(m):
        while parent[m] != m:
            parent[m] = parent[parent[m]]
            m = parent[m]
        return m

    for mouth in mouths:
        queue = deque([mouth])
        owner.setdefault(mouth, mouth)
        while queue:
            node = queue.popleft()
            for a, _, _ in preds[node]:
                if a not in owner:
                    owner[a] = mouth
                    queue.append(a)
                elif find(owner[a]) != find(mouth):
                    parent[find(owner[a])] = find(mouth)

    members = defaultdict(set)
    for node, mouth in owner.items():
        members[find(mouth)].add(node)

    river_or_stream = {w["id"] for w in waterways}
    systems = []
    for root, nodes in members.items():
        # Longest flow path to any mouth of the system (topological order; loops are skipped)
        indegree = Counter()
        edges = []
        for b in nodes:
            for a, metres, way_id in preds[b]:
                if a in nodes:
                    edges.append((a, b, metres, way_id))
                    indegree[b] += 1
        succs = defaultdict(list)
        for a, b, metres, way_id in edges:
            succs[a].append((b, metres, way_id))
        best = {n: (0.0, None) for n in nodes}
        queue = deque(n for n in nodes if indegree[n] == 0)
        while queue:
            a = queue.popleft()
            for b, metres, way_id in succs[a]:
                if best[a][0] + metres > best[b][0]:
                    best[b] = (best[a][0] + metres, (a, way_id))
                indegree[b] -= 1
                if indegree[b] == 0:
                    queue.append(b)

        system_mouths = [m for m in mouths if m in nodes]
        main_mouth = max(system_mouths, key=lambda m: best[m][0])
        length_m = best[main_mouth][0]

        # Main stem: follow the best path back from the mouth, and name the system after it
        stem_names, stem_en, wikidata = Counter(), Counter(), Counter()
        node, guard = main_mouth, 0
        while best[node][1] is not None and guard < len(nodes):
            prev, way_id = best[node][1]
            if way_id is not None:
                tags = way_by_id[way_id].get("tags", {})
                metres = distance_m(*coords[prev], *coords[node])
                if tags.get("name"):
                    stem_names[tags["name"]] += metres
                if tags.get("name:en"):
                    stem_en[tags["name:en"]] += metres
                if tags.get("wikidata"):
                    wikidata[tags["wikidata"]] += metres
            node, guard = prev, guard + 1

        way_ids = {way_id for _, _, _, way_id in edges if way_id is not None}
        network_m = sum(metres for _, _, metres, way_id in edges if way_id is not None)
        if not way_ids & river_or_stream:
            continue  # only drains/canals, no river or stream
        lat, lon = coords[main_mouth]
        systems.append({
            "name": stem_names.most_common(1)[0][0] if stem_names else "",
            "name_en": stem_en.most_common(1)[0][0] if stem_en else "",
            "wikidata": wikidata.most_common(1)[0][0] if wikidata else "",
            "length_km": round(length_m / 1000, 2),
            "network_km": round(network_m / 1000, 2),
            "pieces": len(way_ids),
            "mouths": len(system_mouths),
            "mouth_lat": round(lat, 6),
            "mouth_lon": round(lon, 6),
            "mouth_osm": f"https://www.openstreetmap.org/node/{main_mouth}",
        })

    systems.sort(key=lambda s: s["length_km"], reverse=True)
    for rank, system in enumerate(systems, 1):
        system["rank"] = rank

    total_km = sum(way_length for way_length in
                   (sum(distance_m(p["lat"], p["lon"], q["lat"], q["lon"])
                        for p, q in zip(w["geometry"], w["geometry"][1:])) / 1000
                    for w in waterways))
    in_systems = {w for s in members.values() for n in s for w in ways_at_node[n]} & river_or_stream
    km_in_systems = sum(sum(distance_m(p["lat"], p["lon"], q["lat"], q["lon"])
                            for p, q in zip(way_by_id[w]["geometry"], way_by_id[w]["geometry"][1:])) / 1000
                        for w in in_systems)

    print(f"Lakes linked through: {lake_links} end-to-start links")
    print(f"River systems reaching the sea: {len(systems)} (from {len(mouths)} mouth nodes)")
    for limit in (5, 10, 20, 40):
        print(f"  longer than {limit:2} km: {sum(1 for s in systems if s['length_km'] > limit)}")
    print(f"Share of all river/stream length that drains to the sea: {km_in_systems / total_km:.0%}"
          f" ({km_in_systems:,.0f} of {total_km:,.0f} km)")

    print("\nLONGEST RIVER SYSTEMS (length = longest source-to-mouth path)")
    print("   #  length  network  pieces  name")
    for s in systems[:20]:
        label = s["name"] + (f" ({s['name_en']})" if s["name_en"] and s["name_en"] != s["name"] else "")
        print(f"  {s['rank']:2}  {s['length_km']:6.1f}  {s['network_km']:7.1f}  {s['pieces']:6}  {label or '(no name)'}")

    fields = ["rank", "name", "name_en", "wikidata", "length_km", "network_km", "pieces",
              "mouths", "mouth_lat", "mouth_lon", "mouth_osm"]
    with open("data/river_systems.csv", "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(systems)
    print(f"\nSaved {len(systems)} river systems to data/river_systems.csv")


if __name__ == "__main__":
    main()
