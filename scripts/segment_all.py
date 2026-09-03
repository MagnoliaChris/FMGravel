#!/usr/bin/env python3
"""Segment every GPX in a folder, one race at a time.

Put GPX files in data/gpx/ named after the race id. Add a distance
suffix when a race has several routes:
    data/gpx/castell-grind.gpx
    data/gpx/doss-gravel-34.gpx
    data/gpx/doss-gravel-60.gpx
    data/gpx/doss-gravel-105.gpx

Then:
    python3 scripts/segment_all.py

Skips races already segmented, waits between Overpass calls, and keeps
going when one fails. Safe to re-run — it picks up where it stopped.

    --force     re-segment races that already have output
    --only X    just this race id
    --wait N    seconds between races (default 45)
"""
import argparse, json, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GPX, ROUTES, RACES = ROOT / "data" / "gpx", ROOT / "data" / "routes", ROOT / "data" / "races"

ap = argparse.ArgumentParser()
ap.add_argument("--force", action="store_true")
ap.add_argument("--only", default="")
ap.add_argument("--wait", type=int, default=45)
a = ap.parse_args()

if not GPX.exists():
    GPX.mkdir(parents=True)
    sys.exit(f"Created {GPX}. Put GPX files there named after race ids, then re-run.")

known = {f.stem for f in RACES.glob("*.json")}


def split_id(stem):
    """castell-grind -> (castell-grind, None);  doss-gravel-105 -> (doss-gravel, 105)"""
    if stem in known:
        return stem, None
    parts = stem.rsplit("-", 1)
    if len(parts) == 2 and parts[1].isdigit() and parts[0] in known:
        return parts[0], int(parts[1])
    return None, None
files = sorted(GPX.glob("*.gpx"))
if a.only:
    files = [f for f in files if f.stem == a.only or f.stem.startswith(a.only + "-")]
if not files:
    sys.exit(f"No GPX files in {GPX}")

todo, skip, unknown = [], [], []
for f in files:
    rid, dist = split_id(f.stem)
    if not rid:
        unknown.append(f.stem)
    elif not a.force and (ROUTES / f"{f.stem}.segments.geojson").exists():
        skip.append(f.stem)
    else:
        todo.append((f, rid, dist))

if unknown:
    print(f"No matching race for: {', '.join(unknown)}")
    print(f"  (race ids are the filenames in {RACES.relative_to(ROOT)})\n")
if skip:
    print(f"Already segmented, skipping {len(skip)}: {', '.join(skip)}\n")
if not todo:
    sys.exit("Nothing to do.")

print(f"Segmenting {len(todo)} route(s), {a.wait}s between each.\n")
done, failed = [], []
for i, (f, rid, dist) in enumerate(todo, 1):
    rf = RACES / f"{rid}.json"
    name = json.loads(rf.read_text()).get("name", rid) if rf.exists() else rid
    if dist:
        name = f"{name} {dist}"
    print(f"[{i}/{len(todo)}] {name}")
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "segment_route.py"),
                        str(f), "--name", name, "--out", str(ROUTES / f.stem)],
                       capture_output=True, text=True)
    for line in (r.stdout or "").splitlines():
        if line.strip():
            print("   " + line.strip())
    if r.returncode != 0:
        failed.append(f.stem)
        print("   FAILED — " + (r.stderr or "").strip().splitlines()[-1:][0] if r.stderr else "   FAILED")
    else:
        done.append(f.stem)
    if i < len(todo):
        time.sleep(a.wait)

print(f"\nSegmented {len(done)}, failed {len(failed)}")
if failed:
    print("Re-run to retry: " + ", ".join(failed))

unv = []
for rid in done:
    sp = ROUTES / f"{rid}.summary.json"
    if sp.exists():
        u = json.loads(sp.read_text()).get("unverified_pct", 0)
        if u >= 40:
            unv.append((rid, u))
if unv:
    print("\nHeavily unverified — these need rider input most:")
    for rid, u in sorted(unv, key=lambda x: -x[1]):
        print(f"  {u:>5}%  {rid}")
