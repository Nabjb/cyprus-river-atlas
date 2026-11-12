"""Check every named waterway against the Cyprus naming guideline.

Guideline: https://wiki.openstreetmap.org/wiki/Cyprus#Disputed_place_names_&_Naming_Guidelines
- name     = the name used locally: Greek in the Republic, Turkish in the north,
             English in the UN buffer zone and the British bases
- name:el  = Greek name, name:tr = Turkish name, name:en = English name
- int_name = optional Latin transliteration (ISO 843)

Writes two to-do lists:
- data/name_check_ways.csv   one row per way, with its problems and an OSM link
- data/name_check_rivers.csv one row per name, longest first (what to fix first)
"""
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

from lengths import way_length_km

TURKISH_LETTERS = set("çğıöşüÇĞİÖŞÜ")


def script_of(text):
    """Which alphabet a name is written in: greek, turkish, latin or mixed."""
    greek = any("Ͱ" <= ch <= "Ͽ" or "ἀ" <= ch <= "῿" for ch in text)
    latin = any(ch.isascii() and ch.isalpha() for ch in text) or any(ch in TURKISH_LETTERS for ch in text)
    if greek and latin:
        return "mixed"
    if greek:
        return "greek"
    if any(ch in TURKISH_LETTERS for ch in text) or "dere" in text.lower():
        return "turkish"
    return "latin"


def problems_of(tags):
    """List the ways a set of tags breaks the guideline."""
    problems = []
    name = tags["name"]
    el, tr, en = tags.get("name:el"), tags.get("name:tr"), tags.get("name:en")
    kind = script_of(name)

    if kind == "latin":
        problems.append("name in Latin letters (only correct in buffer zone or British bases)")
    elif kind == "mixed":
        problems.append("name mixes Greek and Latin letters")

    if not el:
        problems.append("no name:el")
    elif script_of(el) != "greek":
        problems.append("name:el not in Greek letters")
    if not tr:
        problems.append("no name:tr")
    elif script_of(tr) in ("greek", "mixed"):
        problems.append("name:tr has Greek letters")
    if not en:
        problems.append("no name:en")

    if name not in {el, tr, en} - {None}:
        problems.append("name does not match name:el, name:tr or name:en")
    return problems


def midpoint(way):
    points = way.get("geometry", [])
    if not points:
        return "", ""
    p = points[len(points) // 2]
    return round(p["lat"], 5), round(p["lon"], 5)


def main():
    raw = Path("data/waterways_raw.json").read_text(encoding="utf-8")
    ways = [w for w in json.loads(raw)["elements"] if "name" in w["tags"]]

    rows = []
    for way in ways:
        tags = way["tags"]
        lat, lon = midpoint(way)
        problems = problems_of(tags)
        rows.append({
            "id": way["id"],
            "waterway": tags["waterway"],
            "name": tags["name"],
            "name_script": script_of(tags["name"]),
            "name:el": tags.get("name:el", ""),
            "name:tr": tags.get("name:tr", ""),
            "name:en": tags.get("name:en", ""),
            "int_name": tags.get("int_name", ""),
            "length_km": round(way_length_km(way), 3),
            "problems": "; ".join(problems),
            "lat": lat,
            "lon": lon,
            "osm": f"https://www.openstreetmap.org/way/{way['id']}",
        })

    # Summary
    total = len(rows)
    ok = sum(1 for r in rows if not r["problems"])
    print(f"NAMED WAYS: {total}")
    print(f"  fully following the guideline: {ok} ({ok / total:.0%})")
    print("\nWHAT ALPHABET IS 'name' WRITTEN IN?")
    for kind, count in Counter(r["name_script"] for r in rows).most_common():
        print(f"  {kind:8} {count:5} ways ({count / total:.0%})")
    print("\nPROBLEMS (a way can have several)")
    counts = Counter(p for r in rows for p in r["problems"].split("; ") if p)
    for problem, count in counts.most_common():
        print(f"  {count:5}  {problem}")

    # One row per name, longest first: the order in which to fix things
    by_name = defaultdict(lambda: {"ways": 0, "km": 0.0, "with_problems": 0, "problems": Counter(), "example": ""})
    for r in rows:
        g = by_name[r["name"]]
        g["ways"] += 1
        g["km"] += r["length_km"]
        if r["problems"]:
            g["with_problems"] += 1
            g["problems"].update(p for p in r["problems"].split("; "))
            g["example"] = g["example"] or r["osm"]
    rivers = sorted(by_name.items(), key=lambda item: item[1]["km"], reverse=True)

    print("\nLONGEST NAMES WITH PROBLEMS (fix these first)")
    shown = 0
    for name, g in rivers:
        if g["with_problems"] and shown < 15:
            print(f"  {g['km']:5.1f} km  {g['with_problems']:3}/{g['ways']:<3} ways  {name}")
            shown += 1

    Path("data").mkdir(exist_ok=True)
    with open("data/name_check_ways.csv", "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda r: (r["name"], r["id"])))

    with open("data/name_check_rivers.csv", "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["name", "km", "ways", "ways_with_problems", "problems", "example_osm_link"])
        for name, g in rivers:
            problems = "; ".join(f"{p} ({n})" for p, n in g["problems"].most_common())
            writer.writerow([name, round(g["km"], 1), g["ways"], g["with_problems"], problems, g["example"]])

    print(f"\nSaved data/name_check_ways.csv ({total} ways) and data/name_check_rivers.csv ({len(rivers)} names)")


if __name__ == "__main__":
    main()
