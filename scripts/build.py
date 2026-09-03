#!/usr/bin/env python3
"""
build.py — generate fmgravel.com as static HTML.

Reads:
  data/races/*.json      one file per race (hand-edited, source of truth)
  data/weather.json      output of race_weather.py           (optional)
  data/routes/<id>.summary.json   output of segment_route.py (optional)
  data/reports.csv       rider submissions exported from your sheet (optional)

Writes to dist/:
  index.html                     the calendar
  races/<id>/index.html          one real page per race — this is the point
  sitemap.xml, robots.txt

Why static pages and not the single-page prototype: Google indexes URLs.
"Rattlesnake tire size" can only rank if /races/rattlesnake/ exists as its
own document with its own title, description and schema. The prototype was
one page pretending to be 25.

Usage:
    python3 scripts/build.py
    python3 scripts/build.py --base https://fmgravel.com
"""

import argparse, csv, html, json, os, shutil, sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA, DIST = ROOT / "data", ROOT / "dist"

LABEL_OF = {"caliche": "Caliche / gravel", "chip_seal": "Chip seal",
            "two_track": "Ranch two-track", "pavement": "Pavement",
            "sand": "Sand", "unknown": "Unverified"}

SURFACE_COLOR = {"caliche": "#C98A24", "chip_seal": "#A8481F",
                 "two_track": "#7A7266", "pavement": "#D6CDBB",
                 "sand": "#E0C88A", "unknown": "#B9B2A4"}

MONTHS = ["", "January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December"]


def e(s):
    return html.escape(str(s), quote=True)


def load():
    races = []
    for f in sorted((DATA / "races").glob("*.json")):
        races.append(json.loads(f.read_text()))
    races.sort(key=lambda r: (r.get("m", 99), r["name"]))

    weather = {}
    wf = DATA / "weather.json"
    if wf.exists():
        weather = json.loads(wf.read_text())

    routes = {}
    rdir = DATA / "routes"
    if rdir.exists():
        for f in rdir.glob("*.summary.json"):
            routes[f.name.split(".")[0]] = json.loads(f.read_text())

    rows = fetch_netlify_submissions()
    if not rows:
        cf = DATA / "reports.csv"
        if cf.exists():
            with cf.open() as fh:
                rows = [r for r in csv.DictReader(fh) if r.get("race_id")]

    rows = clean_reports(rows)

    # keep a copy in the repo so a failed API call never blanks the site
    if rows:
        cols = sorted({k for r in rows for k in r})
        with (DATA / "reports.csv").open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)

    reports = defaultdict(list)
    for r in rows:
        reports[r["race_id"]].append(r)

    return races, weather, routes, reports, load_verifications()



def fetch_netlify_submissions(form="race-report"):
    """Pull form submissions from the Netlify API at build time.

    Needs NETLIFY_AUTH_TOKEN set as an environment variable in Netlify
    (Project configuration -> Environment variables). SITE_ID is provided
    by Netlify automatically during builds.

    Returns [] and prints a note on any failure — a flaky API call should
    never break the build, it should just mean this deploy shows the last
    known data from data/reports.csv.
    """
    import os, urllib.request, urllib.error

    token = os.environ.get("NETLIFY_AUTH_TOKEN", "").strip()
    site = os.environ.get("SITE_ID", "").strip()
    if not token or not site:
        return []

    def get(url):
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())

    try:
        forms = get(f"https://api.netlify.com/api/v1/sites/{site}/forms")
        form = next((f for f in forms if f.get("name") == form), None)
        if not form:
            return []
            return []

        rows, page = [], 1
        while page <= 20:
            batch = get(f"https://api.netlify.com/api/v1/forms/{form['id']}"
                        f"/submissions?per_page=100&page={page}")
            if not batch:
                break
            rows.extend(batch)
            if len(batch) < 100:
                break
            page += 1

        out = []
        for sub in rows:
            d = dict(sub.get("data") or {})
            d["submitted_at"] = sub.get("created_at", "")
            if d.get("race_id"):
                out.append(d)
        print(f"  fetched {len(out)} submissions from Netlify")
        return out
    except Exception as ex:
        print(f"  Netlify submissions unavailable ({ex}) — falling back to reports.csv")
        return []


def clean_reports(rows):
    """Drop obvious junk. Keeps the site honest without a manual review step."""
    seen, out = set(), []
    for r in rows:
        rid = (r.get("race_id") or "").strip()
        if not rid:
            continue
        # one report per race+year+handle+weight; re-submits overwrite
        key = (rid, r.get("year", ""), (r.get("handle") or "").lower().strip(),
               r.get("rider_weight", ""), r.get("width", ""))
        if key in seen:
            continue
        seen.add(key)
        # a report with no flat answer tells the charts nothing
        if not (r.get("flats") or "").strip():
            continue
        # trim free text that arrives with links — the usual spam signature
        tip = (r.get("tip") or "")
        if "http://" in tip or "https://" in tip or "www." in tip:
            r["tip"] = ""
        out.append(r)
    return out


def shell(title, desc, canonical, body, base, extra_head=""):
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(desc)}">
<link rel="canonical" href="{base}{canonical}">
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(desc)}">
<meta property="og:type" content="website">
<meta property="og:url" content="{base}{canonical}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@400;500;600&family=Barlow:wght@400;500&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/style.css">
{extra_head}
</head>
<body>
<header class="masthead"><div class="mh">
  <a class="brand" href="/">
    <span class="shield"><b>FM</b><i></i><s>GRVL</s></span>
    <span><span class="wm">FARM TO MARKET</span><span class="tag">Texas gravel, measured</span></span>
  </a>
</div></header>
<main class="wrap">
{body}
</main>
<footer><div class="wrap">
Calendar compiled from organizer sites and BikeReg. Surface, tire and rating data comes from riders — no editorial scores.
Sample sizes shown on every figure. Route files belong to the organizers; we link rather than rehost.
</div></footer>
</body>
</html>
"""


def race_schema(r, base):
    """Event JSON-LD. Race pages that carry this get richer search results."""
    d = {
        "@context": "https://schema.org", "@type": "SportsEvent",
        "name": r["name"],
        "description": r.get("note", "")[:300],
        "url": f"{base}/races/{r['id']}/",
        "sport": "Gravel cycling",
        "location": {"@type": "Place", "name": f"{r['town']}, TX",
                     "address": {"@type": "PostalAddress",
                                 "addressLocality": r["town"],
                                 "addressRegion": "TX",
                                 "addressCountry": "US"}},
    }
    if r.get("lat"):
        d["location"]["geo"] = {"@type": "GeoCoordinates",
                                "latitude": r["lat"], "longitude": r["lon"]}
    if r.get("url"):
        d["offers"] = {"@type": "Offer", "url": r["url"],
                       "availability": "https://schema.org/InStock"}
    return f'<script type="application/ld+json">{json.dumps(d)}</script>'


def index_page(races, reports, base):
    rows = ""
    for r in races:
        n = len(reports.get(r["id"], []))
        dist = " / ".join(str(x) for x in r.get("d", [])) or "—"
        rows += f"""<tr>
  <td><a href="/races/{r['id']}/"><span class="rname">{e(r['name'])}</span></a>
      {'<span class="night">NIGHT</span>' if r.get('night') else ''}
      <span class="rloc">{e(r['town'])}, TX</span></td>
  <td>{e(r.get('date','—'))}</td>
  <td class="hide-sm">{e(r['county'])}</td>
  <td class="num">{dist}</td>
  <td class="num {'zero' if not n else ''}">{n}</td>
</tr>\n"""

    counties = len({r["county"] for r in races})
    total_reports = sum(len(v) for v in reports.values())
    body = f"""
<div class="strip"><div class="sw2">
  <div><span>Races tracked</span><b>{len(races)}</b></div>
  <div><span>Counties</span><b>{counties}</b></div>
  <div><span>Rider reports</span><b>{total_reports}</b></div>
</div></div>

<h1>Every gravel race in Texas</h1>
<p class="sub">{len(races)} races across {counties} counties, with surface breakdowns,
tire data and race-day climate built from what riders actually report.</p>

<table>
<thead><tr><th>Race</th><th>When</th><th class="hide-sm">County</th>
<th class="num">Distances</th><th class="num">Reports</th></tr></thead>
<tbody>
{rows}</tbody></table>
<p class="note">Missing a race? Every calendar in Texas has gaps. Tell us and it gets added.</p>
"""
    desc = (f"All {len(races)} gravel races in Texas with dates, distances, surface "
            f"breakdowns and rider-reported tire data. No editorial scores.")
    return shell("Every gravel race in Texas | Farm to Market", desc, "/", body, base)


def weather_block(w):
    if not w:
        return """<h2>Race-day weather</h2>
<div class="empty"><p>No climate profile built yet.</p>
<p>Fifteen years of race-window weather — typical high, heat odds, wind and rain.</p></div>"""

    def col(t):
        return "#A8481F" if t >= 95 else "#C98A24" if t >= 88 else "#3C6349" if t >= 75 else "#5C8FA8"

    H = w.get("high_histogram", [])
    peak = max([b["n"] for b in H] or [1])
    bars = "".join(
        f'<div title="{b["lo"]}–{b["hi"]}°F: {b["n"]} days ({b["pct"]}%)">'
        f'<b style="height:{max(3, b["n"]/peak*100):.0f}%;background:{col(b["lo"])}"></b>'
        f'<i>{b["lo"]}</i></div>' for b in H)

    return f"""<h2>Race-day weather</h2>
<p class="verdict">{e(w.get('verdict',''))}</p>
<div class="wgrid">
  <div><span>Typical high</span><b>{w['high_median']}°F</b></div>
  <div><span>1 year in 10</span><b>{w['high_p90']}°F</b></div>
  <div><span>Median wind</span><b>{w.get('wind_median_mph','—')} mph</b></div>
  <div><span>Wet days</span><b>{w['wet_day_pct']}%</b></div>
</div>
<p class="chartlbl">Heat distribution — every race-window day, {w['years']} years</p>
<div class="dist">{bars}</div>
<p class="note">Range {w.get('high_min','?')}–{w['high_max']}°F across {w['sample_days']} days.
{w['hot_day_pct']}% hit 90°F or more. {e(w.get('attribution',''))}.</p>"""




VERIFY_CHOICES = [
    ("caliche",   "Caliche or gravel",        "loose stone, white-ish, washboard"),
    ("chip_seal", "Chip seal",                "tar and gravel, rough, sealed"),
    ("two_track", "Dirt or ranch two-track",  "unsealed, ruts, grass down the middle"),
    ("pavement",  "Smooth asphalt",           "proper blacktop"),
    ("sand",      "Sand",                     "loose and deep"),
]


def load_verifications():
    """Rider segment reports from data/verifications.csv (or the Netlify API)."""
    rows = fetch_netlify_submissions(form="segment-verify")
    if not rows:
        vf = DATA / "verifications.csv"
        if vf.exists():
            with vf.open() as fh:
                rows = [r for r in csv.DictReader(fh) if r.get("race_id")]
    out = defaultdict(list)
    for r in rows:
        try:
            key = (r["race_id"], int(r["seg_index"]))
        except (KeyError, ValueError):
            continue
        if r.get("answer") in dict((c[0], 1) for c in VERIFY_CHOICES):
            out[key].append(r)
    return out


def apply_verifications(slug, geo, verifs):
    """Promote a segment once two riders agree. Flag it when they don't.

    Three honest states, all shown on the page:
      draft     — OpenStreetMap tags, nobody has confirmed
      verified  — two or more riders agree
      disputed  — riders disagree; we say so rather than pick
    """
    for i, f in enumerate(geo["features"]):
        rows = verifs.get((slug, i), [])
        p = f["properties"]
        p["votes"] = len(rows)
        p["state"] = "draft"
        if not rows:
            continue
        tally = Counter(r["answer"] for r in rows)
        top, n = tally.most_common(1)[0]
        rival = max((c for a, c in tally.items() if a != top), default=0)
        if n >= 2 and n > rival:
            p["surface"], p["label"] = top, LABEL_OF[top]
            p["color"] = SURFACE_COLOR[top]
            p["state"] = "verified"
        elif n == rival:
            p["state"] = "disputed"
    return geo


def recompute(geo):
    total = sum(f["properties"]["miles"] for f in geo["features"]) or 1
    by = defaultdict(float)
    for f in geo["features"]:
        by[f["properties"]["surface"]] += f["properties"]["miles"]
    comp = [{"surface": k, "label": LABEL_OF[k], "color": SURFACE_COLOR[k],
             "miles": round(v, 2), "pct": round(v / total * 100, 1)}
            for k, v in sorted(by.items(), key=lambda x: -x[1])]
    verified_mi = sum(f["properties"]["miles"] for f in geo["features"]
                      if f["properties"].get("state") == "verified")
    return {"composition": comp, "total_miles": round(total, 2),
            "segment_count": len(geo["features"]),
            "unverified_pct": round(by.get("unknown", 0) / total * 100, 1),
            "rider_verified_pct": round(verified_mi / total * 100, 1)}


def verify_ui(r, geo):
    """One dropdown, five buttons. Pick a stretch, say what it was."""
    STATE_WORD = {"verified": "rider-verified", "disputed": "riders disagree", "draft": "OSM draft"}
    opts = ""
    for i, f in enumerate(geo["features"]):
        p = f["properties"]
        road = f" · {p['road']}" if p.get("road") else ""
        state = STATE_WORD.get(p.get("state", "draft"), "OSM draft")
        v = f", {p['votes']} report{'s' if p['votes'] != 1 else ''}" if p.get("votes") else ""
        opts += (f'<option value="{i}" data-was="{e(p["label"])}">'
                 f'{p["start_mi"]:.1f}–{p["end_mi"]:.1f} mi{e(road)}'
                 f' — {e(p["label"])} ({state}{v})</option>')

    buttons = "".join(
        f'<button type="button" data-ans="{k}" title="{hint}">{lab}</button>'
        for k, lab, hint in VERIFY_CHOICES)

    verified = sum(1 for f in geo["features"] if f["properties"].get("state") == "verified")

    return f"""
<h2>Ridden this? Help fix the surface data</h2>
<p class="sub">Most of this comes from OpenStreetMap, which is often wrong about ranch roads.
Pick any stretch you remember and say what it actually was. Two riders agreeing marks it
verified — one answer never overrides anything on its own.
{f"So far {verified} of {len(geo['features'])} stretches are rider-verified." if verified else ""}</p>

<div class="verifybox" id="verifybox" data-race="{r['id']}">
  <label for="segpick">Which stretch?</label>
  <select id="segpick">{opts}</select>
  <label>What was it actually like?</label>
  <div class="segopts" id="segopts">{buttons}</div>
  <p class="note" id="verifynote"></p>
</div>
<script>
(function () {{
  var box = document.getElementById('verifybox');
  if (!box) return;
  var pick = document.getElementById('segpick');
  var note = document.getElementById('verifynote');
  var opts = document.getElementById('segopts');
  opts.addEventListener('click', function (ev) {{
    var b = ev.target.closest('button[data-ans]');
    if (!b) return;
    var opt = pick.options[pick.selectedIndex];
    opts.querySelectorAll('button').forEach(function (x) {{ x.disabled = true; }});
    note.textContent = 'Saving…';
    var body = new URLSearchParams({{
      'form-name': 'segment-verify', race_id: box.dataset.race,
      seg_index: opt.value, answer: b.dataset.ans,
      was: opt.dataset.was || '', road: opt.textContent
    }});
    fetch('/', {{ method: 'POST',
      headers: {{ 'Content-Type': 'application/x-www-form-urlencoded' }},
      body: body.toString() }})
      .then(function (res) {{
        note.textContent = res.ok
          ? 'Thanks — recorded. It shows on the map once a second rider agrees. Add another if you like.'
          : 'That did not save. Try again in a moment.';
        opts.querySelectorAll('button').forEach(function (x) {{ x.disabled = false; }});
        if (res.ok && pick.selectedIndex < pick.options.length - 1) pick.selectedIndex += 1;
      }})
      .catch(function () {{
        note.textContent = 'That did not save. Try again in a moment.';
        opts.querySelectorAll('button').forEach(function (x) {{ x.disabled = false; }});
      }});
  }});
}})();
</script>"""


def route_viewer(r, geo_exists):
    """Leaflet map + surface-coloured elevation profile, loaded from /routes/<id>.geojson."""
    if not geo_exists:
        return ""
    return f"""
<div id="routemap" data-src="/routes/{r['id']}.geojson"></div>
<svg id="routeprofile" role="img" aria-label="Elevation profile coloured by road surface"></svg>
<p class="readout" id="routereadout">Hover or drag across the profile to trace the course.</p>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
(function () {{
  var el = document.getElementById('routemap');
  if (!el || !window.L) return;
  fetch(el.dataset.src).then(function (r) {{ return r.json(); }}).then(function (geo) {{
    var map = L.map('routemap', {{ scrollWheelZoom: false }});
    L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',
      {{ maxZoom: 18, attribution: '&copy; OpenStreetMap contributors' }}).addTo(map);

    var bounds = [], pts = [], mi = 0;
    geo.features.forEach(function (f) {{
      var c = f.geometry.coordinates, e = f.properties.elev_ft || [];
      var per = c.length > 1 ? f.properties.miles / (c.length - 1) : 0;
      var ll = c.map(function (xy) {{ return [xy[1], xy[0]]; }});
      ll.forEach(function (p) {{ bounds.push(p); }});
      L.polyline(ll, {{ color: f.properties.color, weight: 5, opacity: .95 }})
        .bindTooltip(f.properties.label + (f.properties.road ? ' · ' + f.properties.road : '')
                     + ' · ' + f.properties.miles + ' mi').addTo(map);
      c.forEach(function (xy, i) {{
        pts.push({{ lat: xy[1], lon: xy[0], ele: e[i] || 0, mi: mi,
                   color: f.properties.color, label: f.properties.label,
                   road: f.properties.road }});
        mi += per;
      }});
    }});
    map.fitBounds(bounds, {{ padding: [16, 16] }});
    var cursor = L.circleMarker(bounds[0],
      {{ radius: 6, color: '#1F3B2C', fillColor: '#FBF9F4', fillOpacity: 1, weight: 2 }});

    var svg = document.getElementById('routeprofile');
    var total = pts[pts.length - 1].mi;
    var W = svg.clientWidth || 900, H = 150, padL = 40, padB = 20, padT = 10;
    var eles = pts.map(function (p) {{ return p.ele; }});
    var lo = Math.min.apply(null, eles), hi = Math.max.apply(null, eles);
    var span = Math.max(hi - lo, 1);
    function X(m) {{ return padL + (m / total) * (W - padL - 8); }}
    function Y(v) {{ return padT + (1 - (v - lo) / span) * (H - padT - padB); }}

    var bands = '', run = [pts[0]];
    function band(seg) {{
      if (seg.length < 2) return '';
      var top = seg.map(function (p) {{ return X(p.mi).toFixed(1) + ',' + Y(p.ele).toFixed(1); }}).join(' ');
      return '<polygon points="' + X(seg[0].mi).toFixed(1) + ',' + (H - padB) + ' ' + top + ' '
             + X(seg[seg.length - 1].mi).toFixed(1) + ',' + (H - padB)
             + '" fill="' + seg[0].color + '" opacity=".92"/>';
    }}
    for (var i = 1; i < pts.length; i++) {{
      if (pts[i].color !== run[0].color) {{ bands += band(run); run = [pts[i]]; }}
      else run.push(pts[i]);
    }}
    bands += band(run);

    var ticks = [0, .25, .5, .75, 1].map(function (f) {{
      var anchor = f === 0 ? 'start' : (f === 1 ? 'end' : 'middle');
      return '<text x="' + X(total * f) + '" y="' + (H - 5) + '" font-size="11" fill="#5C5850"'
           + ' text-anchor="' + anchor + '">' + Math.round(total * f) + '</text>';
    }}).join('');

    svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H);
    svg.innerHTML = '<line x1="' + padL + '" y1="' + (H - padB) + '" x2="' + (W - 8)
      + '" y2="' + (H - padB) + '" stroke="#D6CDBB"/>' + bands
      + '<text x="2" y="' + (Y(hi) + 4) + '" font-size="11" fill="#5C5850">' + Math.round(hi) + '</text>'
      + '<text x="2" y="' + (Y(lo) + 4) + '" font-size="11" fill="#5C5850">' + Math.round(lo) + '</text>'
      + ticks + '<line id="rp-cur" x1="0" y1="' + padT + '" x2="0" y2="' + (H - padB)
      + '" stroke="#A8481F" stroke-width="1.5" opacity="0"/>';

    var cur = svg.querySelector('#rp-cur');
    var out = document.getElementById('routereadout');
    function move(clientX) {{
      var box = svg.getBoundingClientRect();
      var m = ((clientX - box.left) / box.width * W - padL) / (W - padL - 8) * total;
      m = Math.max(0, Math.min(total, m));
      var best = pts[0], bd = Infinity;
      for (var j = 0; j < pts.length; j++) {{
        var d = Math.abs(pts[j].mi - m);
        if (d < bd) {{ bd = d; best = pts[j]; }}
      }}
      cur.setAttribute('x1', X(best.mi)); cur.setAttribute('x2', X(best.mi));
      cur.setAttribute('opacity', 1);
      out.innerHTML = '<b>Mile ' + best.mi.toFixed(1) + '</b> · ' + Math.round(best.ele)
                    + ' ft · ' + best.label + (best.road ? ' · ' + best.road : '');
      cursor.setLatLng([best.lat, best.lon]).addTo(map);
    }}
    svg.addEventListener('mousemove', function (ev) {{ move(ev.clientX); }});
    svg.addEventListener('touchmove', function (ev) {{ move(ev.touches[0].clientX); ev.preventDefault(); }});
    svg.addEventListener('mouseleave', function () {{
      cur.setAttribute('opacity', 0);
      out.textContent = 'Hover or drag across the profile to trace the course.';
      map.removeLayer(cursor);
    }});
  }}).catch(function (e) {{ console.error(e); }});
}})();
</script>"""


def route_block(r, route, geo=None):
    if route:
        mix = "".join(
            f'<div style="width:{c["pct"]}%;background:{SURFACE_COLOR.get(c["surface"],"#B9B2A4")}"'
            f' title="{c["label"]} {c["pct"]}%"></div>' for c in route["composition"])
        legend = " &nbsp; ".join(
            f'<span class="sw" style="background:{SURFACE_COLOR.get(c["surface"],"#B9B2A4")}"></span>'
            f'{c["label"]} {c["pct"]}%' for c in route["composition"])
        unv = route.get("unverified_pct", 0)
        rv = route.get("rider_verified_pct", 0)
        bits = []
        if rv:
            bits.append(f'<span class="ok">{rv}% confirmed by riders</span>')
        if unv:
            bits.append(f'<span class="warn">{unv}% still unverified</span>')
        warn = f'<p class="note">{" · ".join(bits)}</p>' if bits else ""
        out = f"""<h2>Surface breakdown</h2>
<div class="mix">{mix}</div><p class="legend">{legend}</p>
<p class="note">{route['total_miles']} miles in {route['segment_count']} segments.</p>{warn}
{route_viewer(r, (DATA / "routes" / (r["id"] + ".segments.geojson")).exists())}"""
    else:
        out = """<h2>Surface breakdown</h2>
<div class="empty"><p>No route segmented yet.</p>
<p>Caliche, chip seal, ranch two-track, pavement — split from the GPX and verified on the ground.</p></div>"""

    if r.get("gpx"):
        host = r["gpx"].split("//")[-1].split("/")[0].replace("www.", "")
        out += f"""<h2>Routes</h2>
<div class="empty ok"><p>The organizer publishes GPX and TCX files for every distance.</p>
<p><a href="{e(r['gpx'])}" rel="nofollow">Download from {e(host)}</a> — go pre-ride it.</p></div>"""
    else:
        out += """<h2>Routes</h2>
<div class="empty"><p>No route files linked yet.</p>
<p>Most Texas organizers publish GPX openly. Send a link if you have one.</p></div>"""
    return out


def tire_block(rows):
    if not rows:
        return """<h2>Tires and flats</h2>
<div class="empty"><p>No rider reports yet.</p>
<p>Flat rate by width, common choices, and what caused the flats. All rider-reported.</p></div>"""

    widths = defaultdict(lambda: {"n": 0, "flat": 0})
    for r in rows:
        w = r.get("width", "").strip()
        if not w or w.lower().startswith("don"):
            continue
        widths[w]["n"] += 1
        if r.get("flats", "").strip().lower() not in ("", "no flats", "0"):
            widths[w]["flat"] += 1

    order = [w for w in WIDTHS if not w.startswith("Don")]
    keys = [k for k in order if k in widths] + [k for k in widths if k not in order]
    peak = max([widths[k]["flat"] / widths[k]["n"] * 100 for k in keys] or [1])

    bars, axis = "", ""
    for k in keys:
        pct = widths[k]["flat"] / widths[k]["n"] * 100
        c = "#A8481F" if pct >= 25 else "#C98A24" if pct >= 15 else "#3C6349"
        bars += (f'<div><em>{pct:.0f}%</em>'
                 f'<b style="height:{max(4, pct/peak*82):.0f}%;background:{c}"></b></div>')
        axis += f'<span>{e(k)}<small>n={widths[k]["n"]}</small></span>'

    return f"""<h2>Tires and flats</h2>
<p class="chartlbl">Flat rate by tire width</p>
<div class="flatchart">{bars}</div>
<div class="axis">{axis}</div>
<p class="note">{len(rows)} rider reports. Widths under 15 reports are directional only.</p>"""


def race_page(r, weather, routes, reports, base, races, verifs=None):
    w = weather.get(r["id"])
    route = routes.get(r["id"])
    rows = reports.get(r["id"], [])

    geo = None
    gpath = DATA / "routes" / (r["id"] + ".segments.geojson")
    if gpath.exists():
        geo = apply_verifications(r["id"], json.loads(gpath.read_text()), verifs or {})
        route = dict(route or {}, **recompute(geo))
        (DIST / "routes").mkdir(parents=True, exist_ok=True)
        (DIST / "routes" / (r["id"] + ".geojson")).write_text(json.dumps(geo))

    dists = ", ".join(f"{x} mi" for x in r.get("d", [])) or "Varies by year"
    facts = f"""<dl class="facts">
<div><dt>When</dt><dd>{e(r.get('date','—'))}</dd></div>
<div><dt>Distances</dt><dd>{dists}</dd></div>
{f'<div><dt>Organizer</dt><dd>{e(r["org"])}</dd></div>' if r.get('org') else ''}
<div><dt>About</dt><dd>{e(r.get('note',''))}</dd></div>
{f'<div><dt>Register</dt><dd><a href="{e(r["url"])}" rel="nofollow">{e(r["url"].split("//")[-1].split("/")[0].replace("www.",""))}</a></dd></div>' if r.get('url') else ''}
</dl>"""

    same_month = [x for x in races if x.get("m") == r.get("m") and x["id"] != r["id"]]
    nearby = "".join(f'<li><a href="/races/{x["id"]}/">{e(x["name"])}</a> — {e(x["town"])}</li>'
                     for x in same_month[:5])
    also = (f'<h2>Also in {MONTHS[r["m"]] if r.get("m", 0) < 13 else "the calendar"}</h2>'
            f"<ul class=\"links\">{nearby}</ul>") if nearby else ""

    body = f"""<p class="crumb"><a href="/">All races</a></p>
<h1>{e(r['name'])}</h1>
<p class="sub">{e(r['town'])}, TX · {e(r['county'])} County{' · night race' if r.get('night') else ''}</p>
{facts}
{weather_block(w)}
{route_block(r, route, geo)}
{tire_block(rows)}
{verify_ui(r, geo) if geo else ""}
<h2>Add your report</h2>
<div class="empty ok"><p>Rode this race in any year? Two minutes of your memory makes this page useful for everyone else.</p>
<p><a href="/report/?race={r['id']}">Add a report</a> — tires, flats, conditions, and how it went.</p></div>
{also}"""

    title = f"{r['name']} — surface, tires and weather | Farm to Market"
    desc = (f"{r['name']} in {r['town']}, TX ({r.get('date','')}). "
            f"{dists}. Surface breakdown, rider-reported tire and flat data, and race-day climate.")
    return shell(title, desc[:300], f"/races/{r['id']}/", body,
                 base, race_schema(r, base))


RATING_QS = [
    ("course", "Course quality", "Was it worth driving to?"),
    ("surface", "Surface difficulty", "How technical was it?"),
    ("organization", "Organization", "Start, signage, timing, comms"),
    ("aid", "Aid stations", "Spacing, stocking, staffing"),
    ("value", "Value for the fee", ""),
    ("suffering", "How much it hurt", ""),
]

WIDTHS = ["Under 40mm", "40-42mm", "45mm", "50mm", "55mm", "Don't remember"]
WEIGHTS = ["Under 150 lb", "150-175 lb", "175-200 lb", "200 lb+", "Rather not say"]
FLATS = ["No flats", "One", "Two or more"]
CAUSES = ["Sidewall cut", "Thorn / goathead", "Pinch flat", "Rim strike", "Not sure", "N/A"]
CONDITIONS = ["Dry and fast", "Dry and loose", "Dusty", "Damp and tacky", "Muddy", "Washed out"]


def report_page(races, base):
    from datetime import date
    y0 = date.today().year
    years = "".join(f'<option>{y}</option>' for y in range(y0, y0 - 9, -1))
    opts = "".join(f'<option value="{r["id"]}">{e(r["name"])} — {e(r["town"])}</option>' for r in races)

    sliders = "".join(f"""
    <div class="slider-row">
      <label for="{k}">{lab}{f' <span class="hint-inline">{hint}</span>' if hint else ''}
        <output id="out-{k}">5</output></label>
      <input type="range" id="{k}" name="{k}" min="1" max="10" step="1" value="5">
    </div>""" for k, lab, hint in RATING_QS)

    def radios(name, items):
        return "".join(
            f'<label class="pill"><input type="radio" name="{name}" value="{e(v)}"><span>{e(v)}</span></label>'
            for v in items)

    body = f"""<p class="crumb"><a href="/">All races</a></p>
<h1>Add your report</h1>
<p class="sub">Any race, any year you rode it. Old memories still count — we record when you
submitted so the data can be weighted honestly. Two minutes.</p>

<form name="race-report" method="POST" data-netlify="true" netlify-honeypot="bot-field"
      action="/report/thanks/" id="report-form">
  <input type="hidden" name="form-name" value="race-report">
  <p class="hidden-field"><label>Leave this empty: <input name="bot-field"></label></p>

  <fieldset>
    <legend>The basics</legend>
    <label for="race_id">Which race?</label>
    <select id="race_id" name="race_id" required>
      <option value="">Choose a race…</option>
      {opts}
    </select>
    <label for="year">Which year did you ride it?</label>
    <select id="year" name="year" required>{years}</select>
    <label for="distance">Which distance? <span class="hint-inline">miles, roughly</span></label>
    <input type="text" id="distance" name="distance" inputmode="numeric" placeholder="62">
  </fieldset>

  <fieldset>
    <legend>Rate it</legend>
    <p class="hint">One to ten. Drag and move on.</p>
    {sliders}
    <label>Would you do it again?</label>
    <div class="opts">{radios("again", ["Yes", "No", "Only in better conditions"])}</div>
  </fieldset>

  <fieldset>
    <legend>Tires</legend>
    <p class="hint">The part everyone wants. Skip anything you don't remember.</p>
    <label for="tire_model">Tire model</label>
    <input type="text" id="tire_model" name="tire_model" placeholder="Pathfinder Pro">
    <label>Width</label>
    <div class="opts">{radios("width", WIDTHS)}</div>
    <label>Pressure <span class="hint-inline">front / rear, psi — only if you actually remember</span></label>
    <div class="pair">
      <input type="text" name="psi_front" inputmode="numeric" placeholder="Front">
      <input type="text" name="psi_rear" inputmode="numeric" placeholder="Rear">
    </div>
    <label>Your riding weight <span class="hint-inline">pressure data is meaningless without it</span></label>
    <div class="opts">{radios("rider_weight", WEIGHTS)}</div>
    <label>Did you flat? <span class="req">required</span></label>
    <div class="opts">{radios("flats", FLATS)}</div>
    <label>What caused it?</label>
    <div class="opts">{radios("flat_cause", CAUSES)}</div>
  </fieldset>

  <fieldset>
    <legend>Conditions</legend>
    <label for="conditions">Surface that day</label>
    <select id="conditions" name="conditions">
      <option value="">Choose…</option>
      {"".join(f'<option>{c}</option>' for c in CONDITIONS)}
    </select>
    <label for="water">Did you run out of water?</label>
    <div class="opts">{radios("water", ["No", "Yes", "Close"])}</div>
    <label for="tip">One thing you'd tell someone riding it next year</label>
    <input type="text" id="tip" name="tip" maxlength="200"
           placeholder="Fresh sealant. The thorns are real.">
  </fieldset>

  <fieldset>
    <legend>Credit</legend>
    <p class="hint">Optional. Your handle goes on the race page next to the data you helped build.</p>
    <label for="handle">Name or handle</label>
    <input type="text" id="handle" name="handle" placeholder="@yourhandle">
    <label for="email">Email <span class="hint-inline">to get the results — never sold, never spammed</span></label>
    <input type="email" id="email" name="email" placeholder="you@example.com">
  </fieldset>

  <button class="cta" type="submit">Submit report</button>
  <p class="err" id="err" role="alert"></p>
</form>

<form name="segment-verify" data-netlify="true" hidden>
  <input type="text" name="race_id"><input type="text" name="seg_index">
  <input type="text" name="answer"><input type="text" name="was"><input type="text" name="road">
</form>

<script>
document.querySelectorAll('input[type=range]').forEach(function (s) {{
  var o = document.getElementById('out-' + s.id);
  s.addEventListener('input', function () {{ o.textContent = s.value; }});
}});
var q = new URLSearchParams(location.search).get('race');
if (q) {{ var sel = document.getElementById('race_id');
  if ([].some.call(sel.options, function (o) {{ return o.value === q; }})) sel.value = q; }}
document.getElementById('report-form').addEventListener('submit', function (ev) {{
  var err = document.getElementById('err');
  if (!document.getElementById('race_id').value) {{
    ev.preventDefault(); err.textContent = 'Pick a race first.'; return; }}
  if (!document.querySelector('input[name=flats]:checked')) {{
    ev.preventDefault();
    err.textContent = "Tell us whether you flatted — it's the one field the data needs."; return; }}
  err.textContent = '';
}});
</script>"""
    return shell("Add a race report | Farm to Market",
                 "Report the tires, pressure, flats and conditions from any Texas gravel race, any year.",
                 "/report/", body, base)


def thanks_page(base):
    body = """<h1>Report added</h1>
<div class="empty ok">
<p>Thank you — that is now part of the record for that race.</p>
<p>Every figure on this site is built from reports like yours, and every one shows its sample size.</p>
</div>
<p style="margin-top:1.4rem"><a href="/">Back to all races</a></p>"""
    return shell("Report added | Farm to Market", "Thanks for adding a race report.",
                 "/report/thanks/", body, base)


CSS = """:root{--green:#1F3B2C;--green-mid:#3C6349;--caliche:#E9E3D6;--caliche-dk:#D6CDBB;
--rust:#A8481F;--ink:#1A1917;--ink-mid:#5C5850;--paper:#FBF9F4}
*{box-sizing:border-box;margin:0;padding:0}
html{-webkit-text-size-adjust:100%}
body{font-family:'Barlow',system-ui,sans-serif;background:var(--paper);color:var(--ink);font-size:16px;line-height:1.6}
a{color:var(--rust)}
.masthead{background:var(--green);color:var(--caliche);padding:14px 20px}
.mh{max-width:940px;margin:0 auto}
.brand{display:flex;align-items:center;gap:12px;text-decoration:none;color:inherit}
.shield{width:34px;height:38px;border:1.5px solid var(--caliche);border-radius:5px;display:flex;
flex-direction:column;align-items:center;justify-content:center;flex:none;line-height:1}
.shield b{font-family:'Barlow Condensed',sans-serif;font-size:11px;font-weight:500;letter-spacing:.06em}
.shield i{display:block;width:20px;height:1.5px;background:var(--rust);margin:2px 0}
.shield s{font-family:'Barlow Condensed',sans-serif;font-size:12px;font-weight:600;text-decoration:none}
.wm{display:block;font-family:'Barlow Condensed',sans-serif;font-size:23px;font-weight:600;letter-spacing:.05em;line-height:1.1}
.tag{display:block;font-size:12px;color:var(--caliche-dk)}
.wrap{max-width:940px;margin:0 auto;padding:22px 20px}
h1{font-family:'Barlow Condensed',sans-serif;font-size:30px;font-weight:600;line-height:1.15;margin-bottom:2px}
h2{font-family:'Barlow Condensed',sans-serif;font-size:19px;font-weight:600;margin:26px 0 10px}
.sub{font-size:14px;color:var(--ink-mid);margin-bottom:18px;max-width:62ch}
.crumb{font-size:13px;margin-bottom:12px}
.strip{background:var(--caliche);border:1px solid var(--caliche-dk);margin-bottom:22px}
.sw2{padding:14px 16px;display:flex;gap:26px;flex-wrap:wrap}
.sw2 span{display:block;font-size:12px;color:var(--ink-mid)}
.sw2 b{font-family:'Barlow Condensed',sans-serif;font-size:26px;font-weight:600;line-height:1.1}
table{width:100%;border-collapse:collapse}
th{font-family:'Barlow Condensed',sans-serif;font-size:13px;font-weight:600;text-align:left;
color:var(--ink-mid);border-bottom:1.5px solid var(--green);padding:0 8px 6px 0;white-space:nowrap}
td{border-bottom:1px solid var(--caliche-dk);padding:11px 8px 11px 0;font-size:14px;vertical-align:top}
td a{text-decoration:none;color:var(--ink)}
td a:hover .rname{color:var(--rust)}
.rname{display:block;font-weight:500}
.rloc{display:block;font-size:12px;color:var(--ink-mid)}
.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.zero{color:#B9B2A4}
.night{display:inline-block;font-size:10px;padding:1px 5px;background:var(--green);color:var(--caliche);border-radius:2px}
.facts{border-top:1.5px solid var(--green);margin-bottom:8px}
.facts div{display:flex;gap:14px;padding:9px 0;border-bottom:1px solid var(--caliche-dk);font-size:14px}
.facts dt{width:104px;flex:none;color:var(--ink-mid);font-size:13px}
.facts dd{flex:1;max-width:62ch}
.empty{background:var(--caliche);border-left:3px solid var(--rust);padding:14px 16px}
.empty.ok{border-left-color:var(--green)}
.empty p{font-size:14px}
.empty p+p{margin-top:7px;font-size:13px;color:var(--ink-mid)}
.verdict{font-size:15px;padding:12px 14px;background:var(--caliche);border-left:3px solid var(--green);margin-bottom:14px}
.wgrid{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:var(--caliche-dk);
border:1px solid var(--caliche-dk);margin-bottom:6px}
.wgrid div{background:var(--paper);padding:10px 12px}
.wgrid span{display:block;font-size:12px;color:var(--ink-mid)}
.wgrid b{font-family:'Barlow Condensed',sans-serif;font-size:22px;font-weight:600;line-height:1.15}
.chartlbl{font-family:'Barlow Condensed',sans-serif;font-size:14px;font-weight:600;color:var(--ink-mid);margin:18px 0 8px}
.dist{display:flex;align-items:flex-end;gap:3px;height:120px}
.dist div{flex:1;display:flex;flex-direction:column;justify-content:flex-end;height:100%;text-align:center}
.dist b{display:block;border-radius:2px 2px 0 0}
.dist i{font-style:normal;font-size:11px;color:var(--ink-mid);margin-top:4px}
.mix{display:flex;height:22px;border-radius:2px;overflow:hidden;margin-bottom:8px}
.legend{font-size:12px;color:var(--ink-mid);line-height:2}
.sw{display:inline-block;width:9px;height:9px;margin-right:5px}
.flatchart{display:flex;align-items:flex-end;gap:12px;height:104px;margin-bottom:6px}
.flatchart div{flex:1;display:flex;flex-direction:column;justify-content:flex-end;height:100%}
.flatchart em{font-style:normal;font-size:13px;text-align:center;margin-bottom:4px;font-variant-numeric:tabular-nums}
.flatchart b{display:block;border-radius:3px 3px 0 0}
.axis{display:flex;gap:12px;font-size:12px;color:var(--ink-mid);text-align:center}
.axis span{flex:1}
.axis small{display:block;color:#B9B2A4}
#routemap{height:320px;border:1px solid var(--caliche-dk);border-radius:3px;
margin:14px 0 12px;background:var(--caliche)}
#routeprofile{width:100%;height:150px;display:block;cursor:crosshair;touch-action:none}
.readout{font-size:13px;color:var(--ink-mid);min-height:22px;margin-top:4px;font-variant-numeric:tabular-nums}
.readout b{color:var(--ink);font-weight:500}
@media (max-width:620px){#routemap{height:240px}#routeprofile{height:120px}}
.verifybox{background:var(--caliche);border-left:3px solid var(--green);padding:14px 16px}
.verifybox label{display:block;font-size:13px;color:var(--ink-mid);margin:0 0 6px}
.verifybox label+.segopts,.verifybox select+label{margin-top:12px}
.verifybox select{width:100%;padding:9px 10px;border:1px solid var(--caliche-dk);
background:#fff;font-family:inherit;font-size:14px;border-radius:3px}
.segopts{display:flex;gap:6px;flex-wrap:wrap}
.segopts button{background:#fff;border:1px solid var(--caliche-dk);padding:8px 13px;
font-size:14px;border-radius:3px;cursor:pointer;color:var(--ink)}
.segopts button:hover{border-color:var(--green)}
.segopts button:disabled{opacity:.4;cursor:default}
#verifynote{min-height:18px}
.note .ok{color:var(--green-mid);font-weight:500}
.links{list-style:none;font-size:14px}
.links li{padding:7px 0;border-bottom:1px solid var(--caliche-dk)}
.note{font-size:12px;color:var(--ink-mid);margin-top:10px}
form{max-width:60ch}
fieldset{border:0;padding:0;margin:0 0 26px}
legend{font-family:'Barlow Condensed',sans-serif;font-size:18px;font-weight:600;
border-bottom:1.5px solid var(--green);width:100%;padding-bottom:5px;margin-bottom:12px}
form label{display:block;font-size:14px;margin:14px 0 6px}
.hint{font-size:13px;color:var(--ink-mid);margin-bottom:4px}
.hint-inline{font-size:12px;color:var(--ink-mid);font-weight:400}
.req{font-size:11px;color:var(--rust)}
input[type=text],input[type=email],select{width:100%;padding:9px 10px;
border:1px solid var(--caliche-dk);background:#fff;font-family:inherit;font-size:15px;border-radius:3px}
.pair{display:flex;gap:10px}
.slider-row{margin-bottom:4px}
.slider-row output{float:right;font-variant-numeric:tabular-nums;color:var(--rust);font-weight:500}
input[type=range]{width:100%;accent-color:var(--green)}
.opts{display:flex;gap:7px;flex-wrap:wrap}
.pill input{position:absolute;opacity:0;width:0;height:0}
.pill span{display:inline-block;border:1px solid var(--caliche-dk);background:#fff;
padding:8px 14px;font-size:14px;border-radius:3px;cursor:pointer}
.pill input:checked+span{background:var(--green);color:var(--caliche);border-color:var(--green)}
.pill input:focus-visible+span{outline:2px solid var(--rust);outline-offset:2px}
.hidden-field{position:absolute;left:-9999px}
.err{color:var(--rust);font-size:14px;margin-top:10px;min-height:20px}
button.cta{margin-top:6px}
.warn{color:var(--rust)}
footer{background:var(--green);color:var(--caliche-dk);font-size:12px;padding:20px 0;margin-top:36px}
footer .wrap{padding-top:0;padding-bottom:0;max-width:62ch;margin:0 auto}
@media (max-width:620px){.hide-sm{display:none}.wgrid{grid-template-columns:repeat(2,1fr)}
h1{font-size:25px}.facts dt{width:88px}}
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="", help="e.g. https://fmgravel.com (no trailing slash)")
    args = ap.parse_args()
    base = args.base.rstrip("/")

    races, weather, routes, reports, verifs = load()
    if not races:
        sys.exit("No races found in data/races/")

    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir(parents=True)

    (DIST / "style.css").write_text(CSS)
    (DIST / "index.html").write_text(index_page(races, reports, base))

    for r in races:
        d = DIST / "races" / r["id"]
        d.mkdir(parents=True)
        (d / "index.html").write_text(race_page(r, weather, routes, reports, base, races, verifs))

    rd = DIST / "report"; rd.mkdir()
    (rd / "index.html").write_text(report_page(races, base))
    (rd / "thanks").mkdir()
    (rd / "thanks" / "index.html").write_text(thanks_page(base))

    urls = ["/", "/report/"] + [f"/races/{r['id']}/" for r in races]
    sm = "".join(f"<url><loc>{base}{u}</loc></url>" for u in urls)
    (DIST / "sitemap.xml").write_text(
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{sm}</urlset>')
    (DIST / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {base}/sitemap.xml\n")

    have_w = sum(1 for r in races if r["id"] in weather)
    have_r = sum(1 for r in races if r["id"] in routes)
    have_p = sum(1 for r in races if reports.get(r["id"]))
    print(f"Built {len(urls)} pages into dist/")
    print(f"  weather profiles: {have_w}/{len(races)}")
    print(f"  segmented routes: {have_r}/{len(races)}")
    print(f"  races with reports: {have_p}/{len(races)}")
    if not base:
        print("\n  No --base set. Set it before deploying or canonical URLs will be relative.")


if __name__ == "__main__":
    main()
