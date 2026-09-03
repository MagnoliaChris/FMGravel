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
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA, DIST = ROOT / "data", ROOT / "dist"

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

    reports = defaultdict(list)
    cf = DATA / "reports.csv"
    if cf.exists():
        with cf.open() as fh:
            for row in csv.DictReader(fh):
                if row.get("race_id"):
                    reports[row["race_id"]].append(row)

    return races, weather, routes, reports


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


def route_block(r, route):
    if route:
        mix = "".join(
            f'<div style="width:{c["pct"]}%;background:{SURFACE_COLOR.get(c["surface"],"#B9B2A4")}"'
            f' title="{c["label"]} {c["pct"]}%"></div>' for c in route["composition"])
        legend = " &nbsp; ".join(
            f'<span class="sw" style="background:{SURFACE_COLOR.get(c["surface"],"#B9B2A4")}"></span>'
            f'{c["label"]} {c["pct"]}%' for c in route["composition"])
        unv = route.get("unverified_pct", 0)
        warn = (f'<p class="note warn">{unv}% of this route has no verified surface.</p>'
                if unv else "")
        out = f"""<h2>Surface breakdown</h2>
<div class="mix">{mix}</div><p class="legend">{legend}</p>
<p class="note">{route['total_miles']} miles in {route['segment_count']} segments.</p>{warn}"""
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

    order = ["Under 40mm", "40–42mm", "45mm", "50mm", "55mm"]
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


def race_page(r, weather, routes, reports, base, races):
    w = weather.get(r["id"])
    route = routes.get(r["id"])
    rows = reports.get(r["id"], [])

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
{route_block(r, route)}
{tire_block(rows)}
<h2>Add your report</h2>
<div class="empty ok"><p>Rode this race in any year? Two minutes of your memory makes this page useful for everyone else.</p>
<p><a href="/report/?race={r['id']}">Add a report</a> — tires, flats, conditions, and how it went.</p></div>
{also}"""

    title = f"{r['name']} — surface, tires and weather | Farm to Market"
    desc = (f"{r['name']} in {r['town']}, TX ({r.get('date','')}). "
            f"{dists}. Surface breakdown, rider-reported tire and flat data, and race-day climate.")
    return shell(title, desc[:300], f"/races/{r['id']}/", body,
                 base, race_schema(r, base))


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
.links{list-style:none;font-size:14px}
.links li{padding:7px 0;border-bottom:1px solid var(--caliche-dk)}
.note{font-size:12px;color:var(--ink-mid);margin-top:10px}
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

    races, weather, routes, reports = load()
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
        (d / "index.html").write_text(race_page(r, weather, routes, reports, base, races))

    urls = ["/"] + [f"/races/{r['id']}/" for r in races]
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
