"""Download the waterway data for the whole island of Cyprus from OpenStreetMap.

Writes three files:
- data/waterways_raw.json        rivers and streams (used by every other script)
- data/other_waterways_raw.json  canals, drains and ditches (rivers can flow into them)
- data/coastline_raw.json        the coastline (to know which waterways reach the sea)
- data/water_bodies_raw.json     lakes and reservoirs (streams can end in them)

Every way is saved with its tags, the IDs of its nodes (points) and their
coordinates, so later scripts can tell which pieces touch each other.
"""
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

SERVERS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

# A box around the whole island: south, north and the British bases.
# Order: south, west, north, east. Everything else inside it is sea.
BBOX = "34.4,32.2,35.75,34.65"

# Reject servers whose copy of OpenStreetMap is older than this.
MAX_AGE = timedelta(days=7)

# Output file -> list of (label, Overpass filter). Each filter is one request,
# so no single request is too big for the server.
DATASETS = {
    "data/waterways_raw.json": [
        ("rivers", 'way["waterway"="river"]'),
        ("streams", 'way["waterway"="stream"]'),
    ],
    "data/other_waterways_raw.json": [
        ("canals, drains and ditches", 'way["waterway"~"^(canal|drain|ditch)$"]'),
    ],
    "data/coastline_raw.json": [
        ("coastline", 'way["natural"="coastline"]'),
    ],
    "data/water_bodies_raw.json": [
        ("lakes and reservoirs (simple shapes)", 'way["natural"="water"]'),
        ("lakes and reservoirs (old reservoir tag)", 'way["landuse"="reservoir"]'),
        ("lakes and reservoirs (multi-part shapes)", 'relation["natural"="water"]'),
    ],
}


def build_query(selector):
    # "out body geom" returns the tags, the node IDs and the coordinates of every way
    return f"""
[out:json][timeout:180];
{selector}({BBOX});
out body geom;
"""


def fetch(query):
    for attempt in range(3):
        for url in SERVERS:
            print(f"  trying {url} ...")
            try:
                response = requests.post(
                    url,
                    data={"data": query},
                    headers={"User-Agent": "cyprus-river-atlas (university project)"},
                    timeout=300,
                )
                response.raise_for_status()
                data = response.json()
            except requests.RequestException as error:
                print(f"    failed: {error}")
                continue

            stamp = data["osm3s"]["timestamp_osm_base"].replace("Z", "+00:00")
            age = datetime.now(timezone.utc) - datetime.fromisoformat(stamp)
            if age > MAX_AGE:
                print(f"    data is {age.days} days old, skipping this server")
                continue
            return data, url
        print("  no server gave fresh data, waiting 30 seconds...")
        time.sleep(30)
    raise SystemExit("Could not download fresh data. Try again in a few minutes.")


def main():
    Path("data").mkdir(exist_ok=True)

    for path, parts in DATASETS.items():
        elements, dates = [], []
        for label, selector in parts:
            print(f"Downloading {label} ...")
            data, url = fetch(build_query(selector))
            ways = data["elements"]
            named = sum(1 for w in ways if "name" in w.get("tags", {}))
            date = data["osm3s"]["timestamp_osm_base"]
            print(f"  {len(ways)} pieces, {named} named")
            print(f"  server: {url}")
            print(f"  data as of: {date}")
            elements.extend(ways)
            dates.append(date)

        out = Path(path)
        out.write_text(json.dumps({"osm_date": min(dates), "elements": elements}), encoding="utf-8")
        size_mb = out.stat().st_size / 1_000_000
        print(f"Saved {len(elements)} pieces to {out} ({size_mb:.1f} MB)\n")


if __name__ == "__main__":
    main()
