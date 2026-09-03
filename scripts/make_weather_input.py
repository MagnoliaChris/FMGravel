#!/usr/bin/env python3
import json, re
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
out, skipped = [], []
for f in sorted((ROOT / "data" / "races").glob("*.json")):
    r = json.loads(f.read_text())
    m = re.search(r"\b(\d{1,2})\b", r.get("date", ""))
    if not m or not r.get("m") or r["m"] > 12 or not r.get("lat"):
        skipped.append(f"{r['name']} ({r.get('date','no date')})"); continue
    out.append({"id": r["id"], "name": r["name"], "lat": r["lat"], "lon": r["lon"],
                "month_num": r["m"], "day": int(m.group(1))})
(ROOT / "races.json").write_text(json.dumps(out, indent=2))
print(f"Wrote races.json with {len(out)} races")
for s in skipped: print("  skipped: " + s)
