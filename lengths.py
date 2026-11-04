import csv
import json
import math
from collections import defaultdict
from pathlib import Path

EARTH_RADIUS_KM = 6371.0088


def distance_km(a, b):
    """Distance between two points on the Earth's surface (haversine formula)."""
    lat1, lon1 = math.radians(a["lat"]), math.radians(a["lon"])
    lat2, lon2 = math.radians(b["lat"]), math.radians(b["lon"])
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


def way_length_km(way):
    """Length of one piece: the sum of the distances between its points."""
    points = way.get("geometry", [])
    return sum(distance_km(p, q) for p, q in zip(points, points[1:]))


def main():
    raw = Path("data/waterways_raw.json").read_text(encoding="utf-8")
    ways = json.loads(raw)["elements"]

    rows = []
    for way in ways:
        tags = way["tags"]
        rows.append({
            "id": way["id"],
            "waterway": tags["waterway"],
            "name": tags.get("name", ""),
            "name_en": tags.get("name:en", ""),
            "length_km": way_length_km(way),
        })

    # 1. Total length
    print("TOTAL LENGTH")
    for kind in ("river", "stream"):
        group = [r for r in rows if r["waterway"] == kind]
        total = sum(r["length_km"] for r in group)
        named = sum(r["length_km"] for r in group if r["name"])
        print(f"  {kind:7} {total:8.0f} km  ({named / total:.0%} of it named)")
    print(f"  {'all':7} {sum(r['length_km'] for r in rows):8.0f} km")

    # 2. Longest named waterways (pieces with the same name added together)
    by_name = defaultdict(lambda: {"km": 0.0, "pieces": 0, "en": ""})
    for r in rows:
        if r["name"]:
            entry = by_name[r["name"]]
            entry["km"] += r["length_km"]
            entry["pieces"] += 1
            entry["en"] = entry["en"] or r["name_en"]

    print("\nLONGEST NAMED WATERWAYS (same-name pieces added together)")
    top = sorted(by_name.items(), key=lambda item: item[1]["km"], reverse=True)[:15]
    for name, e in top:
        label = f"{name} ({e['en']})" if e["en"] else name
        print(f"  {e['km']:6.1f} km  {e['pieces']:4} pieces  {label}")

    # 3. Save every piece with its length to a spreadsheet file
    out = Path("data/piece_lengths.csv")
    with out.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        for r in rows:
            writer.writerow({**r, "length_km": round(r["length_km"], 3)})
    print(f"\nSaved {len(rows)} pieces to {out}")


if __name__ == "__main__":
    main()