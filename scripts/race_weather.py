#!/usr/bin/env python3
"""
race_weather.py — build race-day climate profiles from historical weather.

For each race, pulls the weather on that calendar date (plus a window either
side) across N past years and summarises what a rider should actually expect:
typical high, the hot years, rain odds, wind, and heat index.

Data: Open-Meteo ERA5 reanalysis archive. No API key. 9 km resolution, so it
is regional truth, not the exact reading at the start line — good enough for
"what does April in Castell feel like", not for race-morning decisions.

Licensing, read this: the weather DATA is CC BY 4.0 — free to store and
republish, including commercially, as long as you attribute Open-Meteo. The
free API ENDPOINT is non-commercial only. So: fetch once, cache the results
in your repo, and serve from your cache. If the site ever carries ads,
affiliate links or subscriptions, move to their paid customer endpoint or
self-host (the server is AGPL). Do not run this on every page view.

Usage:
    python3 race_weather.py races.json --years 15 --out weather.json
    python3 race_weather.py races.json --offline cached_archive.json
"""

import argparse, json, statistics, sys, time
from datetime import date, timedelta

ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
ATTRIB = "Historical weather: Open-Meteo ERA5 (CC BY 4.0)"

DAILY = ["temperature_2m_max", "temperature_2m_min", "precipitation_sum",
         "wind_speed_10m_max", "wind_gusts_10m_max", "apparent_temperature_max"]


def fetch(lat, lon, start, end, offline=None):
    if offline:
        return json.load(open(offline))
    import requests
    p = {"latitude": lat, "longitude": lon, "start_date": start, "end_date": end,
         "daily": ",".join(DAILY), "temperature_unit": "fahrenheit",
         "wind_speed_unit": "mph", "precipitation_unit": "inch",
         "timezone": "America/Chicago"}
    for attempt in range(3):
        r = requests.get(ARCHIVE, params=p, timeout=300)
        if r.status_code == 200:
            return r.json()
        print(f"    HTTP {r.status_code}, retrying in 15s")
        time.sleep(30)
    raise RuntimeError("Open-Meteo archive failed three times")


def window_days(month, day, years, pad):
    """Every date within +/- pad days of month/day, for the last `years` years."""
    out, this_year = [], date.today().year
    for y in range(this_year - years, this_year):
        try:
            anchor = date(y, month, day)
        except ValueError:            # Feb 29 in a non-leap year
            anchor = date(y, month, day - 1)
        for d in range(-pad, pad + 1):
            out.append(anchor + timedelta(days=d))
    return out


def profile(race, years=15, pad=3, offline=None):
    """Summarise race-date weather for one race."""
    wanted = set(window_days(race["month_num"], race["day"], years, pad))
    start = min(wanted).isoformat()
    end = max(wanted).isoformat()

    raw = fetch(race["lat"], race["lon"], start, end, offline)
    d = raw["daily"]
    rows = []
    for i, iso in enumerate(d["time"]):
        if date.fromisoformat(iso) not in wanted:
            continue
        rows.append({k: d[k][i] for k in DAILY} | {"date": iso})

    rows = [r for r in rows if r["temperature_2m_max"] is not None]
    if not rows:
        return None

    highs = [r["temperature_2m_max"] for r in rows]
    feels = [r["apparent_temperature_max"] for r in rows if r["apparent_temperature_max"] is not None]
    lows = [r["temperature_2m_min"] for r in rows]
    wind = [r["wind_speed_10m_max"] for r in rows if r["wind_speed_10m_max"] is not None]
    gust = [r["wind_gusts_10m_max"] for r in rows if r["wind_gusts_10m_max"] is not None]
    rain = [r["precipitation_sum"] or 0 for r in rows]

    # by-year highs on the anchor date only, for the year-over-year chart
    by_year = {}
    for r in rows:
        dt = date.fromisoformat(r["date"])
        if dt.month == race["month_num"] and dt.day == race["day"]:
            by_year[dt.year] = round(r["temperature_2m_max"])

    wet = sum(1 for p in rain if p >= 0.10)
    soaked = sum(1 for p in rain if p >= 0.50)

    # distribution of race-window highs, in 5°F buckets — the real story
    b_lo = int(min(highs) // 5 * 5)
    b_hi = int(max(highs) // 5 * 5 + 5)
    hist = []
    for b in range(b_lo, b_hi, 5):
        n = sum(1 for h in highs if b <= h < b + 5)
        hist.append({"lo": b, "hi": b + 5, "n": n, "pct": round(n / len(highs) * 100, 1)})

    return {
        "race_id": race["id"],
        "name": race["name"],
        "sample_days": len(rows),
        "years": years,
        "window_days": pad * 2 + 1,
        "high_median": round(statistics.median(highs)),
        "high_p90": round(sorted(highs)[int(len(highs) * 0.9)]),
        "high_p10": round(sorted(highs)[int(len(highs) * 0.1)]),
        "high_max": round(max(highs)),
        "high_min": round(min(highs)),
        "high_histogram": hist,
        "low_median": round(statistics.median(lows)),
        "feels_like_p90": round(sorted(feels)[int(len(feels) * 0.9)]) if feels else None,
        "wind_median_mph": round(statistics.median(wind)) if wind else None,
        "gust_p90_mph": round(sorted(gust)[int(len(gust) * 0.9)]) if gust else None,
        "wet_day_pct": round(wet / len(rows) * 100),
        "soaker_pct": round(soaked / len(rows) * 100),
        "hot_day_pct": round(sum(1 for h in highs if h >= 90) / len(highs) * 100),
        "freeze_risk_pct": round(sum(1 for l in lows if l <= 32) / len(lows) * 100),
        "by_year_high": dict(sorted(by_year.items())),
        "attribution": ATTRIB,
    }


def verdict(p):
    """One plain sentence a rider can act on."""
    bits = []
    if p["hot_day_pct"] >= 50:
        bits.append(f"expect heat — {p['hot_day_pct']}% of race-window days hit 90°F or more")
    elif p["hot_day_pct"] >= 20:
        bits.append(f"heat is a real possibility ({p['hot_day_pct']}% of days at 90°F+)")
    if p["freeze_risk_pct"] >= 15:
        bits.append(f"freezing starts happen ({p['freeze_risk_pct']}% of mornings at or below 32°F)")
    if p["wind_median_mph"] and p["wind_median_mph"] >= 15:
        bits.append(f"wind is the defining factor — median max {p['wind_median_mph']} mph")
    if p["wet_day_pct"] >= 30:
        bits.append(f"wet roughly {p['wet_day_pct']}% of the time")
    elif p["wet_day_pct"] <= 10:
        bits.append("usually dry")
    base = f"Typically {p['high_median']}°F"
    return base + ". " + "; ".join(bits).capitalize() + "." if bits else base + " and unremarkable."


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("races", help="JSON array of races with id,name,lat,lon,month_num,day")
    ap.add_argument("--years", type=int, default=15)
    ap.add_argument("--pad", type=int, default=3, help="days either side of race date")
    ap.add_argument("--out", default="weather.json")
    ap.add_argument("--offline", default="", help="single cached archive response, for testing")
    ap.add_argument("--sleep", type=float, default=2.0, help="seconds between API calls")
    args = ap.parse_args()

    races = json.load(open(args.races))
    out = {}
    for i, r in enumerate(races, 1):
        if not r.get("day"):
            print(f"  skip {r['name']} — no fixed date")
            continue
        print(f"[{i}/{len(races)}] {r['name']}")
        try:
            p = profile(r, args.years, args.pad, args.offline or None)
        except Exception as e:
            print(f"    failed: {e}")
            continue
        if p:
            p["verdict"] = verdict(p)
            out[r["id"]] = p
            print(f"    {p['verdict']}")
        if not args.offline:
            time.sleep(args.sleep)

    json.dump(out, open(args.out, "w"), indent=2)
    print(f"\nWrote {args.out} — {len(out)} races")
    print(ATTRIB)


if __name__ == "__main__":
    main()
