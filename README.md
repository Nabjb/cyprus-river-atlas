# Cyprus River Atlas

Senior project at European University Cyprus: improving the knowledge of rivers and streams in Cyprus using OpenStreetMap, studying flood risk, and presenting it all as a public website.

Supervisor: Daniel Risquez (Cerides, EUC)

## Setup

    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt

## Scripts

- `download.py`: downloads every river and stream on the whole island from OpenStreetMap (via the Overpass API) into `data/waterways_raw.json`. Servers with data older than 7 days are skipped.

Data © OpenStreetMap contributors, available under the ODbL.