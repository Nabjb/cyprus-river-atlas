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


def build_query(kind):
    return f"""
[out:json][timeout:180];
way["waterway"="{kind}"]({BBOX});
out tags geom;
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
    elements = []
    for kind in ("river", "stream"):
        print(f"Downloading waterway={kind} ...")
        data, url = fetch(build_query(kind))
        ways = data["elements"]
        named = sum(1 for w in ways if "name" in w["tags"])
        date = data["osm3s"]["timestamp_osm_base"]
        print(f"  {len(ways)} pieces, {named} named")
        print(f"  server: {url}")
        print(f"  data as of: {date}")
        elements.extend(ways)

    Path("data").mkdir(exist_ok=True)
    out = Path("data/waterways_raw.json")
    out.write_text(json.dumps({"elements": elements}), encoding="utf-8")

    size_mb = out.stat().st_size / 1_000_000
    print(f"Saved {len(elements)} pieces to {out} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()