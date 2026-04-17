"""Seed the test account with realistic NYC construction data for screenshots.

- 5 real-looking NYC projects at varied addresses
- 12 workers across trades/subcontractors
- 7 days of daily logs for each project
- A few active check-ins (for "on site" counter)

Safe to re-run — skips items that already exist by name/phone.
"""
import json
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone

API = "https://api.levelog.com"
EMAIL = "test@test.com"
PASSWORD = "test"


def _req(method, path, token=None, body=None):
    url = f"{API}{path}"
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            text = resp.read().decode()
            return resp.status, (json.loads(text) if text else None)
    except urllib.error.HTTPError as e:
        err_body = e.read().decode()
        return e.code, err_body


def login():
    status, data = _req("POST", "/api/auth/login", body={"email": EMAIL, "password": PASSWORD})
    if status != 200:
        raise RuntimeError(f"Login failed: {status} {data}")
    return data["token"], data.get("user", {})


# ── Seed data ──

PROJECTS = [
    {
        "name": "432 Park Avenue Tower",
        "address": "432 Park Ave, New York, NY 10022",
        "building_stories": 96,
        "building_height": 1396,
        "footprint_sqft": 30000,
        "status": "active",
        "ssp_number": "SSP-2024-1156",
    },
    {
        "name": "Hudson Yards Block 44",
        "address": "551 W 33rd St, New York, NY 10001",
        "building_stories": 58,
        "building_height": 720,
        "footprint_sqft": 42000,
        "status": "active",
        "ssp_number": "SSP-2025-0289",
    },
    {
        "name": "Brooklyn Navy Yard Build C",
        "address": "63 Flushing Ave, Brooklyn, NY 11205",
        "building_stories": 12,
        "building_height": 145,
        "footprint_sqft": 85000,
        "status": "active",
        "ssp_number": "SSP-2025-0341",
    },
    {
        "name": "Long Island City Residential",
        "address": "2835 Jackson Ave, Long Island City, NY 11101",
        "building_stories": 42,
        "building_height": 490,
        "footprint_sqft": 18500,
        "status": "active",
        "ssp_number": "SSP-2024-0978",
    },
    {
        "name": "Bronx Community Hospital Expansion",
        "address": "1650 Selwyn Ave, Bronx, NY 10457",
        "building_stories": 8,
        "building_height": 110,
        "footprint_sqft": 62000,
        "status": "active",
        "ssp_number": "SSP-2025-0412",
    },
]

WORKERS = [
    {"name": "Michael Torres",    "phone": "917-555-0101", "trade": "Concrete", "company": "Torres Masonry Inc."},
    {"name": "James O'Brien",     "phone": "917-555-0102", "trade": "Iron Worker", "company": "Local 40 Ironworkers"},
    {"name": "Carlos Rodriguez",  "phone": "917-555-0103", "trade": "Electrician", "company": "Petrocelli Electric"},
    {"name": "David Kim",         "phone": "917-555-0104", "trade": "Plumber", "company": "NYC Plumbing Co."},
    {"name": "Anthony Russo",     "phone": "917-555-0105", "trade": "Carpenter", "company": "Russo Construction"},
    {"name": "Rajesh Patel",      "phone": "917-555-0106", "trade": "Safety Manager", "company": "SafeSite Solutions"},
    {"name": "Marcus Johnson",    "phone": "917-555-0107", "trade": "Crane Operator", "company": "IUOE Local 14"},
    {"name": "Giovanni Ferrari",  "phone": "917-555-0108", "trade": "Mason", "company": "Ferrari Brothers Masonry"},
    {"name": "Thomas Walsh",      "phone": "917-555-0109", "trade": "Superintendent", "company": "Walsh General Contracting"},
    {"name": "Luis Hernandez",    "phone": "917-555-0110", "trade": "Laborer", "company": "LiUNA Local 79"},
    {"name": "Kevin Murphy",      "phone": "917-555-0111", "trade": "Welder", "company": "Murphy Welding"},
    {"name": "Sophia Chen",       "phone": "917-555-0112", "trade": "Site Engineer", "company": "BlueView Engineering"},
]

WEATHER_OPTIONS = [
    {"temp": "68°F", "wind": "8 mph NE",  "condition": "Partly Cloudy"},
    {"temp": "72°F", "wind": "5 mph SW",  "condition": "Clear"},
    {"temp": "58°F", "wind": "12 mph N",  "condition": "Overcast"},
    {"temp": "62°F", "wind": "10 mph E",  "condition": "Light Rain"},
    {"temp": "75°F", "wind": "6 mph S",   "condition": "Sunny"},
    {"temp": "55°F", "wind": "15 mph NW", "condition": "Cloudy"},
    {"temp": "70°F", "wind": "7 mph W",   "condition": "Clear"},
]

NOTES_SAMPLES = [
    "Foundation pour completed on schedule. Crew of 18 on site. No safety incidents.",
    "Steel erection continuing on floors 14-18. Crane lift operations complete at 3:45 PM.",
    "MEP rough-in progressing. Electrical subcontractor pulled feeders for north wing.",
    "Concrete placement 340 cubic yards. Temperature monitored, no cold joints.",
    "Facade panels installed on east elevation, floors 22-25. All QC checks passed.",
    "Daily safety meeting attended by 24 workers. Topic: fall protection at height.",
    "Excavation for footings complete. Shoring inspected and approved by competent person.",
]

WORK_PERFORMED = [
    "Formwork stripping, rebar tying for columns on floor 8",
    "Steel beam erection, decking installation, welding inspections",
    "Conduit rough-in, panel installation, ground testing",
    "Concrete placement, finishing, curing protection",
    "Curtain wall installation, waterproofing, glazing",
    "Fall protection setup, scaffold inspection, toolbox talk",
    "Excavation, shoring, dewatering operations",
]


def seed_projects(token):
    status, existing = _req("GET", "/api/projects", token)
    names = set()
    if isinstance(existing, dict):
        names = {p.get("name") for p in (existing.get("items") or existing.get("projects") or [])}
    elif isinstance(existing, list):
        names = {p.get("name") for p in existing}

    created = []
    for p in PROJECTS:
        if p["name"] in names:
            print(f"  skip project (exists): {p['name']}")
            continue
        status, data = _req("POST", "/api/projects", token, body=p)
        if status in (200, 201):
            created.append(data)
            print(f"  + project: {p['name']}")
        else:
            print(f"  ! project failed ({status}): {p['name']} -- {str(data)[:120]}")

    # Fetch full list after creation
    status, listing = _req("GET", "/api/projects", token)
    projects = []
    if isinstance(listing, dict):
        projects = listing.get("items") or listing.get("projects") or []
    elif isinstance(listing, list):
        projects = listing
    return projects


def seed_workers(token):
    status, existing = _req("GET", "/api/workers", token)
    phones = set()
    if isinstance(existing, dict):
        phones = {w.get("phone") for w in (existing.get("items") or existing.get("workers") or [])}
    elif isinstance(existing, list):
        phones = {w.get("phone") for w in existing}

    created = []
    for w in WORKERS:
        if w["phone"] in phones:
            print(f"  skip worker (exists): {w['name']}")
            continue
        status, data = _req("POST", "/api/workers", token, body=w)
        if status in (200, 201):
            created.append(data)
            print(f"  + worker: {w['name']}")
        else:
            print(f"  ! worker failed ({status}): {w['name']} -- {str(data)[:120]}")

    status, listing = _req("GET", "/api/workers", token)
    workers = []
    if isinstance(listing, dict):
        workers = listing.get("items") or listing.get("workers") or []
    elif isinstance(listing, list):
        workers = listing
    return workers


def seed_daily_logs(token, projects):
    today = datetime.now(timezone.utc).date()
    for idx, proj in enumerate(projects):
        pid = proj.get("id") or proj.get("_id")
        for days_ago in range(7):
            date = (today - timedelta(days=days_ago)).isoformat()
            w = WEATHER_OPTIONS[(idx + days_ago) % len(WEATHER_OPTIONS)]
            body = {
                "project_id": pid,
                "date": date,
                "weather": f"{w['condition']}, {w['temp']}, wind {w['wind']}",
                "weather_temp": w["temp"],
                "weather_wind": w["wind"],
                "weather_condition": w["condition"],
                "notes": NOTES_SAMPLES[(idx + days_ago) % len(NOTES_SAMPLES)],
                "work_performed": WORK_PERFORMED[(idx + days_ago) % len(WORK_PERFORMED)],
                "worker_count": 12 + ((idx * 3 + days_ago * 2) % 15),
            }
            status, data = _req("POST", "/api/daily-logs", token, body=body)
            if status in (200, 201):
                print(f"  + log: {proj.get('name', '?')[:30]} @ {date}")
            else:
                # Duplicate logs often return 400 — suppress noise
                if status not in (400, 409):
                    print(f"  ! log failed ({status}) @ {date}: {str(data)[:100]}")


def seed_checkins(token, workers, projects):
    """Try to check a handful of workers in for 'on site' counter."""
    if not workers or not projects:
        return
    # check in first 4 workers across first 2 projects
    pairs = [
        (workers[0], projects[0]),
        (workers[1], projects[0]),
        (workers[2], projects[1]),
        (workers[3], projects[1]),
    ]
    for w, p in pairs:
        wid = w.get("id") or w.get("_id")
        pid = p.get("id") or p.get("_id")
        body = {"worker_id": wid, "project_id": pid}
        status, data = _req("POST", "/api/checkins", token, body=body)
        if status in (200, 201):
            print(f"  + check-in: {w.get('name')} @ {p.get('name','?')[:30]}")
        else:
            msg = str(data)[:140]
            print(f"  ! check-in ({status}) {w.get('name')}: {msg}")


def main():
    print("Logging in...")
    token, user = login()
    print(f"  user: {user.get('email')} (role={user.get('role')})")

    print("\nSeeding projects...")
    projects = seed_projects(token)
    print(f"  total projects: {len(projects)}")

    print("\nSeeding workers...")
    workers = seed_workers(token)
    print(f"  total workers: {len(workers)}")

    print("\nSeeding daily logs (7 days each)...")
    seed_daily_logs(token, projects[:5])

    print("\nSeeding active check-ins...")
    seed_checkins(token, workers, projects)

    print("\nDone.")


if __name__ == "__main__":
    main()
