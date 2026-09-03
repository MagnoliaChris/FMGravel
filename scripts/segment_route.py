#!/usr/bin/env python3
"""
segment_route.py — turn a race GPX into surface segments.

Reads a GPX file, asks OpenStreetMap (via Overpass) what surface each road
along the route is tagged with, snaps every track point to the nearest road,
and writes out:

  <name>.segments.geojson   coloured line segments, one per surface run
  <name>.summary.json       surface percentages + segment list

This produces a DRAFT. Rural Texas OSM surface coverage is patchy and
sometimes wrong. Everything tagged "unknown" and every segment boundary
needs a human who has ridden the road. That verification pass is the point —
it is much faster to correct 20 segments than to build them from nothing.

Usage:
    python3 segment_route.py castell-62.gpx --name "Castell Grind 62"
    python3 segment_route.py route.gpx --offline mock_overpass.json
"""

import argparse, json, math, sys, time
import xml.etree.ElementTree as ET
from collections import Counter

import numpy as np

OVERPASS = "https://overpass-api.de/api/interpreter"

# OSM surface tag -> our category. Anything unlisted falls through to unknown.
SURFACE_MAP = {
    "asphalt": "pavement", "paved": "pavement", "concrete": "pavement",
    "concrete:plates": "pavement", "concrete:lanes": "pavement",
    "chipseal": "chip_seal", "sett": "chip_seal", "tar": "chip_seal",
    "gravel": "caliche", "fine_gravel": "caliche", "compacted": "caliche",
    "limestone": "caliche", "caliche": "caliche", "pebblestone": "caliche",
    "crushed_limestone": "caliche",
    "dirt": "two_track", "ground": "two_track", "earth": "two_track",
    "unpaved": "two_track", "sand": "two_track", "grass": "two_track",
    "mud": "two_track", "woodchips": "two_track",
}

# tracktype is the fallback when surface is absent — grade1 is firm, grade5 is soft.
TRACKTYPE_MAP = {
    "grade1": "caliche", "grade2": "caliche",
    "grade3": "two_track", "grade4": "two_track", "grade5": "two_track",
}

# highway tag fallback when neither surface nor tracktype is present.
HIGHWAY_MAP = {
    "motorway": "pavement", "trunk": "pavement", "primary": "pavement",
    "secondary": "pavement", "tertiary": "pavement",
    "track": "two_track", "path": "two_track", "bridleway": "two_track",
}

LABEL = {"caliche": "Caliche / gravel", "chip_seal": "Chip seal",
         "two_track": "Ranch two-track", "pavement": "Pavement",
         "unknown": "Unverified"}

COLOR = {"caliche": "#C98A24", "chip_seal": "#A8481F",
         "two_track": "#6B5A45", "pavement": "#4A5568",
         "sand": "#E0C88A", "unknown": "#9A9389"}

R_EARTH_MI = 3958.8


def read_gpx(path):
    """Return an (N,2) array of lat/lon and an (N,) array of elevation in feet."""
    tree = ET.parse(path)
    ns = {"g": "http://www.topografix.com/GPX/1/1"}
    pts = tree.findall(".//g:trkpt", ns)
    if not pts:  # GPX 1.0, or no namespace at all
        pts = [e for e in tree.iter() if e.tag.split("}")[-1] == "trkpt"]
    if not pts:
        sys.exit(f"No track points found in {path}")
    coords, elev = [], []
    for p in pts:
        coords.append((float(p.get("lat")), float(p.get("lon"))))
        ele = next((c for c in p if c.tag.split("}")[-1] == "ele"), None)
        elev.append(float(ele.text) * 3.28084 if ele is not None else 0.0)
    return np.array(coords), np.array(elev)


def bbox(coords, pad=0.01):
    lat, lon = coords[:, 0], coords[:, 1]
    return (lat.min() - pad, lon.min() - pad, lat.max() + pad, lon.max() + pad)


def overpass_query(bb):
    s, w, n, e = bb
    return f"""[out:json][timeout:180];
way["highway"]({s},{w},{n},{e});
out geom tags;"""


def fetch_ways(bb, offline=None):
    """Return list of dicts: {surface, points:(M,2)}."""
    if offline:
        data = json.load(open(offline))
    else:
        import requests
        q = overpass_query(bb)
        for attempt in range(3):
            r = requests.post(OVERPASS, data={"data": q}, timeout=200)
            if r.status_code == 200:
                data = r.json()
                break
            print(f"  Overpass returned {r.status_code}, retrying in 20s")
            time.sleep(20)
        else:
            sys.exit("Overpass failed three times. Try again later, or use --offline.")

    ways = []
    for el in data.get("elements", []):
        if el.get("type") != "way" or "geometry" not in el:
            continue
        t = el.get("tags", {})
        surf = SURFACE_MAP.get(t.get("surface", "").lower())
        if surf is None:
            surf = TRACKTYPE_MAP.get(t.get("tracktype", "").lower())
        if surf is None:
            surf = HIGHWAY_MAP.get(t.get("highway", "").lower())
        pts = np.array([[g["lat"], g["lon"]] for g in el["geometry"]])
        ways.append({"surface": surf or "unknown", "points": pts,
                     "name": t.get("name", ""), "ref": t.get("ref", "")})
    return ways


def densify(pts, step_m=12.0):
    """OSM way vertices can sit hundreds of metres apart on straight rural roads.
    Insert intermediate points so nearest-vertex snapping behaves like
    nearest-segment snapping."""
    if len(pts) < 2:
        return pts
    out = [pts[0]]
    for a, b in zip(pts[:-1], pts[1:]):
        d_m = haversine_mi(a, b) * 1609.34
        n = int(d_m // step_m)
        for k in range(1, n + 1):
            f = k / (n + 1)
            out.append(a + (b - a) * f)
        out.append(b)
    return np.array(out)


def snap(coords, ways, max_m=35.0):
    """Assign a surface to each track point by nearest way vertex."""
    if not ways:
        return ["unknown"] * len(coords), [""] * len(coords)
    dense = [densify(w["points"]) for w in ways]
    verts = np.vstack(dense)
    owner = np.concatenate([np.full(len(d), i) for i, d in enumerate(dense)])

    lat0 = math.radians(coords[:, 0].mean())
    # local equirectangular projection, metres
    def proj(a):
        return np.column_stack([np.radians(a[:, 1]) * math.cos(lat0) * 6371000,
                                np.radians(a[:, 0]) * 6371000])
    P, V = proj(coords), proj(verts)

    surfaces, names = [], []
    CH = 2000  # chunk track points to keep the distance matrix small
    for i in range(0, len(P), CH):
        blk = P[i:i + CH]
        d = np.sqrt(((blk[:, None, :] - V[None, :, :]) ** 2).sum(-1))
        idx = d.argmin(1)
        best = d[np.arange(len(blk)), idx]
        for j, k in enumerate(idx):
            if best[j] > max_m:
                surfaces.append("unknown"); names.append("")
            else:
                w = ways[owner[k]]
                surfaces.append(w["surface"])
                names.append(w["name"] or w["ref"])
    return surfaces, names


def smooth(labels, window=9):
    """Majority filter — stops the surface flapping between adjacent ways."""
    out, n, h = [], len(labels), window // 2
    for i in range(n):
        seg = labels[max(0, i - h):min(n, i + h + 1)]
        out.append(Counter(seg).most_common(1)[0][0])
    return out


def haversine_mi(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, [a[0], a[1], b[0], b[1]])
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 2 * R_EARTH_MI * math.asin(math.sqrt(h))


def build_segments(coords, elev, labels, names, min_mi=0.15):
    """Group consecutive same-surface points into runs, dropping slivers."""
    runs, start = [], 0
    for i in range(1, len(labels) + 1):
        if i == len(labels) or labels[i] != labels[start]:
            runs.append([start, i - 1, labels[start]])
            start = i

    # absorb any run shorter than min_mi into whichever neighbour is longer
    def run_mi(r):
        return sum(haversine_mi(coords[k], coords[k + 1]) for k in range(r[0], r[1]))

    changed = True
    while changed and len(runs) > 1:
        changed = False
        for i, r in enumerate(runs):
            if run_mi(r) < min_mi:
                prev_len = run_mi(runs[i - 1]) if i > 0 else -1
                next_len = run_mi(runs[i + 1]) if i < len(runs) - 1 else -1
                target = i - 1 if prev_len >= next_len else i + 1
                runs[target][0] = min(runs[target][0], r[0])
                runs[target][1] = max(runs[target][1], r[1])
                runs.pop(i)
                changed = True
                break

    segs, cum = [], 0.0
    for a, b, surf in runs:
        mi = run_mi([a, b, surf])
        road = Counter(n for n in names[a:b + 1] if n).most_common(1)
        segs.append({
            "surface": surf, "label": LABEL[surf], "color": COLOR[surf],
            "miles": round(mi, 2),
            "start_mi": round(cum, 2), "end_mi": round(cum + mi, 2),
            "road": road[0][0] if road else "",
            "coords": [[float(coords[k][1]), float(coords[k][0])] for k in range(a, b + 1)],
            "elev_ft": [round(float(elev[k])) for k in range(a, b + 1)],
        })
        cum += mi
    return segs, cum


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("gpx")
    ap.add_argument("--name", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--offline", default="", help="use a saved Overpass JSON instead of the network")
    ap.add_argument("--snap-m", type=float, default=35.0)
    args = ap.parse_args()

    stem = args.out or args.gpx.rsplit(".", 1)[0]
    coords, elev = read_gpx(args.gpx)
    print(f"Read {len(coords)} track points")

    ways = fetch_ways(bbox(coords), args.offline or None)
    print(f"Fetched {len(ways)} OSM ways")

    labels, names = snap(coords, ways, args.snap_m)
    labels = smooth(labels)
    segs, total = build_segments(coords, elev, labels, names)

    by_surface = {}
    for s in segs:
        by_surface[s["surface"]] = by_surface.get(s["surface"], 0) + s["miles"]
    summary = {
        "name": args.name or stem,
        "total_miles": round(total, 2),
        "segment_count": len(segs),
        "composition": [
            {"surface": k, "label": LABEL[k], "color": COLOR[k],
             "miles": round(v, 2), "pct": round(v / total * 100, 1)}
            for k, v in sorted(by_surface.items(), key=lambda x: -x[1])
        ],
        "unverified_pct": round(by_surface.get("unknown", 0) / total * 100, 1),
        "segments": [{k: s[k] for k in
                      ("surface", "label", "miles", "start_mi", "end_mi", "road")} for s in segs],
    }

    geo = {"type": "FeatureCollection", "features": [
        {"type": "Feature",
         "geometry": {"type": "LineString", "coordinates": s["coords"]},
         "properties": {**{k: s[k] for k in
                        ("surface", "label", "color", "miles", "start_mi", "end_mi", "road")},
                        "elev_ft": s["elev_ft"]}}
        for s in segs]}

    json.dump(geo, open(f"{stem}.segments.geojson", "w"))
    json.dump(summary, open(f"{stem}.summary.json", "w"), indent=2)

    print(f"\n{summary['name']} — {summary['total_miles']} mi, {len(segs)} segments")
    for c in summary["composition"]:
        print(f"  {c['label']:<20} {c['pct']:>5}%  ({c['miles']} mi)")
    if summary["unverified_pct"] > 0:
        print(f"\n  {summary['unverified_pct']}% unverified — ride it or check the plat before publishing.")
    print(f"\nWrote {stem}.segments.geojson and {stem}.summary.json")


if __name__ == "__main__":
    main()
