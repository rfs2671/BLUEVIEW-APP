"""Seed Blueview Builders demo data.

1. Login as owner (rfs2671@gmail.com).
2. Create company 'Blueview Builders' + admin 'rfs2671+blueview@gmail.com' / '1234'.
3. Login as that admin.
4. Create 4 NYC projects at the given addresses.
5. Set GC legal name 'Blueview Builders' on each project (triggers DOB resolution).
6. Refresh insurance from DOB for the company.
7. Seed 15 workers across trades.
8. Seed 14 days of daily jobsite logs per project.

Safe to re-run — skips existing items where possible.
"""
import json
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone

API = "https://api.levelog.com"

OWNER_EMAIL = "rfs2671@gmail.com"
OWNER_PASSWORD = "Asdddfgh1$"

ADMIN_EMAIL = "rfs2671+blueview@gmail.com"
ADMIN_PASSWORD = "1234"

COMPANY_NAME = "Blueview Builders"
GC_LEGAL_NAME = "Blueview Builders"

PROJECTS = [
    {"name": "3846 Bailey Avenue",     "address": "3846 Bailey Ave, Bronx, NY 10463"},
    {"name": "533 Concord Avenue",     "address": "533 Concord Ave, Bronx, NY 10455"},
    {"name": "638 Lafayette Avenue",   "address": "638 Lafayette Ave, Brooklyn, NY 11221"},
    {"name": "852 East 176th Street",  "address": "852 E 176th St, Bronx, NY 10460"},
]

WORKERS = [
    {"name": "Michael Torres",    "phone": "917-555-2001", "trade": "Concrete",         "company": "Torres Masonry Inc."},
    {"name": "James O'Brien",     "phone": "917-555-2002", "trade": "Iron Worker",      "company": "Local 40 Ironworkers"},
    {"name": "Carlos Rodriguez",  "phone": "917-555-2003", "trade": "Electrician",      "company": "Petrocelli Electric"},
    {"name": "David Kim",         "phone": "917-555-2004", "trade": "Plumber",          "company": "NYC Plumbing Co."},
    {"name": "Anthony Russo",     "phone": "917-555-2005", "trade": "Carpenter",        "company": "Russo Construction"},
    {"name": "Rajesh Patel",      "phone": "917-555-2006", "trade": "Safety Manager",   "company": "Blueview Builders"},
    {"name": "Marcus Johnson",    "phone": "917-555-2007", "trade": "Crane Operator",   "company": "IUOE Local 14"},
    {"name": "Giovanni Ferrari",  "phone": "917-555-2008", "trade": "Mason",            "company": "Ferrari Brothers Masonry"},
    {"name": "Thomas Walsh",      "phone": "917-555-2009", "trade": "Superintendent",   "company": "Blueview Builders"},
    {"name": "Luis Hernandez",    "phone": "917-555-2010", "trade": "Laborer",          "company": "LiUNA Local 79"},
    {"name": "Kevin Murphy",      "phone": "917-555-2011", "trade": "Welder",           "company": "Murphy Welding"},
    {"name": "Sophia Chen",       "phone": "917-555-2012", "trade": "Site Engineer",    "company": "Blueview Builders"},
    {"name": "Ahmed Hassan",      "phone": "917-555-2013", "trade": "Drywall",          "company": "Liberty Drywall"},
    {"name": "Ryan O'Connor",     "phone": "917-555-2014", "trade": "HVAC",             "company": "Empire HVAC"},
    {"name": "Daniel Vasquez",    "phone": "917-555-2015", "trade": "Roofer",           "company": "Vasquez Roofing"},
]

WEATHER = [
    {"temp": "68°F", "wind": "8 mph NE",  "condition": "Partly Cloudy"},
    {"temp": "72°F", "wind": "5 mph SW",  "condition": "Clear"},
    {"temp": "58°F", "wind": "12 mph N",  "condition": "Overcast"},
    {"temp": "62°F", "wind": "10 mph E",  "condition": "Light Rain"},
    {"temp": "75°F", "wind": "6 mph S",   "condition": "Sunny"},
    {"temp": "55°F", "wind": "15 mph NW", "condition": "Cloudy"},
    {"temp": "70°F", "wind": "7 mph W",   "condition": "Clear"},
]

NOTES = [
    "Foundation pour completed on schedule. Crew of 18 on site. No safety incidents.",
    "Steel erection continuing on floors 3-5. Crane lift operations complete at 3:45 PM.",
    "MEP rough-in progressing. Electrical subcontractor pulled feeders for north wing.",
    "Concrete placement 340 cubic yards. Temperature monitored, no cold joints.",
    "Facade work continued on east elevation. All QC checks passed by CP.",
    "Daily safety meeting attended by 22 workers. Topic: fall protection at height.",
    "Excavation for footings complete. Shoring inspected and approved by competent person.",
    "Underpinning operations on adjacent building continued. No movement recorded.",
    "Dewatering pumps in service. Groundwater levels stable.",
    "Reinforcement inspection completed prior to pour. Passed SOE review.",
    "Scaffold inspection conducted by qualified person. All tags current.",
    "Waste disposal coordinated with carting company. Dumpster exchanged.",
    "Site logistics plan updated for crane relocation next week.",
    "Weekly toolbox talk — silica dust exposure. 24 attendees signed in.",
]

WORK_PERFORMED = [
    "Formwork stripping, rebar tying for columns on floor 4",
    "Steel beam erection, decking installation, welding inspections",
    "Conduit rough-in, panel installation, ground testing",
    "Concrete placement, finishing, curing protection",
    "Curtain wall installation, waterproofing, glazing",
    "Fall protection setup, scaffold inspection, toolbox talk",
    "Excavation, shoring, dewatering operations",
    "Underpinning, monitoring, SOE compliance checks",
    "Masonry, parging, brick layout on ground floor",
    "Interior framing, fireproofing, drywall stocking",
    "HVAC duct installation, chiller placement on roof",
    "Plumbing riser installation, pressure testing",
    "Site cleanup, debris removal, housekeeping walk",
    "Permit renewal prep, DOB inspection coordination",
]


def _req(method, path, token=None, body=None, timeout=30):
    url = f"{API}{path}"
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode()
            return resp.status, (json.loads(text) if text else None)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, None


def login(email, password):
    status, data = _req("POST", "/api/auth/login", body={"email": email, "password": password})
    if status != 200:
        raise RuntimeError(f"Login failed for {email}: {status} {data}")
    return data["token"]


def ensure_admin_account(owner_token):
    # Check if Blueview Builders company already exists with our admin
    status, admins = _req("GET", "/api/owner/admins", owner_token)
    if isinstance(admins, list):
        for a in admins:
            if a.get("email") == ADMIN_EMAIL:
                print(f"  admin already exists: {ADMIN_EMAIL}")
                return
    # Create
    body = {
        "name": "Roy Fishman",
        "email": ADMIN_EMAIL,
        "password": ADMIN_PASSWORD,
        "company_name": COMPANY_NAME,
    }
    status, data = _req("POST", "/api/owner/admins", owner_token, body=body)
    if status not in (200, 201):
        raise RuntimeError(f"Create admin failed: {status} {data}")
    print(f"  + admin created: {ADMIN_EMAIL} ({COMPANY_NAME})")


def list_projects(admin_token):
    status, data = _req("GET", "/api/projects", admin_token)
    if isinstance(data, dict):
        return data.get("items") or data.get("projects") or []
    if isinstance(data, list):
        return data
    return []


def seed_projects(admin_token):
    existing = {p.get("name"): p for p in list_projects(admin_token)}
    created = []
    for p in PROJECTS:
        if p["name"] in existing:
            print(f"  skip project (exists): {p['name']}")
            created.append(existing[p["name"]])
            continue
        status, data = _req("POST", "/api/projects", admin_token, body=p)
        if status in (200, 201):
            created.append(data)
            print(f"  + project: {p['name']} (BIN: {data.get('nyc_bin') or 'not resolved'})")
        else:
            print(f"  ! project failed ({status}): {p['name']} -- {str(data)[:180]}")
    return created


def set_gc_legal_name(admin_token, projects):
    for p in projects:
        pid = p.get("id") or p.get("_id")
        if not pid:
            continue
        status, data = _req(
            "PUT",
            f"/api/projects/{pid}/dob-config",
            admin_token,
            body={"gc_legal_name": GC_LEGAL_NAME},
        )
        if status == 200:
            print(f"  + gc_legal_name set on {p.get('name')}: {data.get('gc_legal_name')}")
        else:
            print(f"  ! gc_legal_name failed ({status}) for {p.get('name')}: {str(data)[:140]}")


def refresh_insurance(admin_token):
    status, data = _req("POST", "/api/admin/company/insurance/refresh", admin_token, timeout=60)
    if status == 200:
        records = data.get("gc_insurance_records", [])
        print(f"  + insurance refresh OK ({len(records)} records, license: {data.get('gc_license_status')})")
    else:
        print(f"  ! insurance refresh failed ({status}): {str(data)[:200]}")


def list_workers(admin_token):
    status, data = _req("GET", "/api/workers", admin_token)
    if isinstance(data, dict):
        return data.get("items") or data.get("workers") or []
    if isinstance(data, list):
        return data
    return []


def seed_workers(admin_token):
    existing = {w.get("phone") for w in list_workers(admin_token)}
    for w in WORKERS:
        # Also check normalized form +1XXXXXXXXXX since backend normalizes phones
        digits = "".join(c for c in w["phone"] if c.isdigit())
        normalized = f"+1{digits}" if len(digits) == 10 else f"+{digits}"
        if w["phone"] in existing or normalized in existing:
            print(f"  skip worker (exists): {w['name']}")
            continue
        status, data = _req("POST", "/api/workers", admin_token, body=w)
        if status in (200, 201):
            print(f"  + worker: {w['name']} ({w['trade']})")
        elif status == 400 and "exists" in str(data):
            print(f"  skip worker (exists via phone): {w['name']}")
        else:
            print(f"  ! worker failed ({status}): {w['name']} -- {str(data)[:140]}")
    return list_workers(admin_token)


def seed_daily_logs(admin_token, projects, days=14):
    today = datetime.now(timezone.utc).date()
    for idx, proj in enumerate(projects):
        pid = proj.get("id") or proj.get("_id")
        name = proj.get("name", "?")
        for d_ago in range(days):
            date = (today - timedelta(days=d_ago)).isoformat()
            w = WEATHER[(idx + d_ago) % len(WEATHER)]
            body = {
                "project_id": pid,
                "date": date,
                "weather": f"{w['condition']}, {w['temp']}, wind {w['wind']}",
                "weather_temp": w["temp"],
                "weather_wind": w["wind"],
                "weather_condition": w["condition"],
                "notes": NOTES[(idx + d_ago) % len(NOTES)],
                "work_performed": WORK_PERFORMED[(idx + d_ago) % len(WORK_PERFORMED)],
                "worker_count": 12 + ((idx * 3 + d_ago * 2) % 15),
            }
            status, data = _req("POST", "/api/daily-logs", admin_token, body=body)
            if status in (200, 201):
                print(f"  + log: {name[:32]:32s} @ {date}")
            elif status not in (400, 409):
                print(f"  ! log ({status}) {name} @ {date}: {str(data)[:100]}")


def main():
    print("=== Blueview Builders demo seed ===\n")

    print("[1/7] Login as owner...")
    owner_token = login(OWNER_EMAIL, OWNER_PASSWORD)
    print(f"  owner OK\n")

    print("[2/7] Create company + admin...")
    ensure_admin_account(owner_token)

    print("\n[3/7] Login as new admin...")
    admin_token = login(ADMIN_EMAIL, ADMIN_PASSWORD)
    print(f"  admin OK\n")

    print("[4/7] Create projects...")
    projects = seed_projects(admin_token)
    print(f"  total projects: {len(projects)}\n")

    print("[5/7] Set GC Legal Name on projects...")
    set_gc_legal_name(admin_token, projects)

    print("\n[6/7] Refresh insurance from NYC DOB...")
    refresh_insurance(admin_token)

    print("\n[7/7] Seed workers + daily logs...")
    workers = seed_workers(admin_token)
    print(f"  total workers: {len(workers)}")
    seed_daily_logs(admin_token, projects)

    print("\n=== DONE ===")
    print(f"Login:   {ADMIN_EMAIL} / {ADMIN_PASSWORD}")
    print(f"Owner login still works for managing this company.")


if __name__ == "__main__":
    main()
