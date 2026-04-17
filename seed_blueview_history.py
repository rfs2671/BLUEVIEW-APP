"""Add OSHA + SST certifications to all Blueview workers and seed
realistic check-in history (14 days x 4 projects x rotating crews).
"""
import json
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone

API = "https://api.levelog.com"
ADMIN_EMAIL = "rfs2671+blueview@gmail.com"
ADMIN_PASSWORD = "1234"


def _req(method, path, token=None, body=None, timeout=30):
    url = f"{API}{path}"
    data = json.dumps(body, default=str).encode() if body is not None else None
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
            return e.code, e.read().decode()[:300]


def login():
    status, data = _req("POST", "/api/auth/login",
                        body={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    if status != 200:
        raise RuntimeError(f"Login failed: {status} {data}")
    return data["token"]


def main():
    print("Logging in...")
    token = login()

    # 1. Get workers
    status, ws = _req("GET", "/api/workers", token)
    workers = ws.get("items") if isinstance(ws, dict) else (ws if isinstance(ws, list) else [])
    print(f"Found {len(workers)} workers")

    # 2. Get projects
    status, ps = _req("GET", "/api/projects", token)
    projects = ps.get("items") if isinstance(ps, dict) else (ps if isinstance(ps, list) else [])
    projects = [p for p in projects if "Blueview" not in p.get("name", "") and p.get("name") != "3846 Bailey Avenue, The Bronx, NY, USA"]
    # Keep only the 4 we explicitly seeded for Blueview
    KEEP_NAMES = {"3846 Bailey Avenue", "533 Concord Avenue", "638 Lafayette Avenue", "852 East 176th Street"}
    projects = [p for p in projects if p.get("name") in KEEP_NAMES]
    print(f"Projects: {[p.get('name') for p in projects]}")

    # 3. Add OSHA + SST certs to each worker (1 year valid)
    today = datetime.now(timezone.utc)
    issue = (today - timedelta(days=180)).isoformat()
    expiry = (today + timedelta(days=365)).isoformat()

    print("\nAdding certifications to workers...")
    for w in workers:
        wid = w.get("id") or w.get("_id")
        existing_types = {c.get("type") for c in (w.get("certifications") or [])}
        for ctype, label in [("OSHA_30", "OSHA-30"), ("SST_FULL", "SST Full")]:
            if ctype in existing_types:
                continue
            body = {
                "type": ctype,
                "card_number": f"{ctype}-{(w.get('phone') or '0000000000').replace('+', '').replace('-', '')[-6:]}",
                "issue_date": issue,
                "expiration_date": expiry,
                "verified": True,
                "verified_by": "Demo seed",
            }
            status, data = _req("POST", f"/api/workers/{wid}/certifications", token, body=body)
            if status in (200, 201):
                print(f"  + {label} -> {w.get('name')}")
            else:
                print(f"  ! {label} -> {w.get('name')} HTTP {status}: {str(data)[:120]}")

    # 4. Seed check-ins: rotating crew across 14 days, all 4 projects
    print("\nSeeding check-ins (14 days × 4 projects, rotating crews)...")
    for d_ago in range(14):
        # Each day pick 4-7 workers per project (deterministic rotation)
        for p_idx, proj in enumerate(projects):
            pid = proj.get("id") or proj.get("_id")
            crew_size = 4 + ((d_ago + p_idx) % 4)
            for w_idx in range(crew_size):
                worker = workers[(d_ago * 3 + p_idx * 5 + w_idx) % len(workers)]
                wid = worker.get("id") or worker.get("_id")
                body = {"worker_id": str(wid), "project_id": str(pid)}
                status, data = _req("POST", "/api/checkins", token, body=body)
                if status in (200, 201):
                    pass
                elif status == 403 and isinstance(data, dict) and data.get("detail", {}).get("blocked"):
                    print(f"  ! cert block: {worker.get('name')} -> {data.get('detail',{}).get('blocks')}")
                    return
                elif status not in (400, 409):
                    print(f"  ! HTTP {status} ({worker.get('name')} -> {proj.get('name')[:25]}): {str(data)[:120]}")

    print("\nVerifying...")
    status, ci = _req("GET", "/api/checkins?limit=200", token)
    items = ci.get("items") if isinstance(ci, dict) else []
    print(f"Total check-ins now: {len(items)}")
    if items:
        latest = items[0]
        print(f"  Latest: {latest.get('worker_name')} @ {latest.get('project_name')}")

    print("\nDone.")


if __name__ == "__main__":
    main()
