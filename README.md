[README.md](https://github.com/user-attachments/files/31761718/README.md)
# FMGravel
Building out FM Gravel site 
# fmgravel.com

Texas gravel race data. Static site, no database, no server.

## Layout

    data/races/*.json      one file per race — the source of truth, edit by hand
    data/weather.json      from scripts/race_weather.py
    data/routes/*.json     from scripts/segment_route.py
    data/reports.csv       rider submissions, exported from your sheet
    scripts/build.py       generates dist/
    dist/                  what gets deployed (never edit; it is regenerated)

## Build

    python3 scripts/build.py --base https://fmgravel.com

Writes one real HTML page per race at /races/<id>/, plus sitemap.xml and
robots.txt. Every race page carries its own title, meta description,
canonical URL and SportsEvent JSON-LD.

## Adding a race

Copy any file in data/races/, change the values, rebuild. Fields:

    id        url slug — permanent, do not change once indexed
    name, town, county, month, m (month number), date
    d         array of distances in miles
    lat, lon  used by race_weather.py
    org, url  organizer and registration link
    gpx       organizer's route-file page (link, never rehost)
    note      what a rider needs to know
    night     1 for night races

## Weather

    python3 scripts/race_weather.py races.json --years 15 --out data/weather.json

Needs a races.json array with id, name, lat, lon, month_num, day.
Open-Meteo's free endpoint is non-commercial. The data is CC BY 4.0, so
cache it here and serve from the cache. If the site starts earning, move
to their paid endpoint or self-host.

## Routes

    python3 scripts/segment_route.py castell-62.gpx --out data/routes/castell-grind

Draft surface segments from OpenStreetMap tags. Always verify before
publishing — unverified miles are labelled as such on the page.

## Deploy

Push to GitHub, connect to Netlify or Cloudflare Pages.
Build command: python3 scripts/build.py --base https://fmgravel.com
Publish directory: dist
Point txgravel.com at fmgravel.com as a 301. Never serve both.
