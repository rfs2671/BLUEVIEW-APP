"""Capture Play Store screenshots at phone + 7" tablet + 10" tablet sizes.

Logs in via API, stashes token in AsyncStorage-compatible localStorage keys,
then screenshots each route.
"""
import asyncio
import json
import urllib.request
from pathlib import Path
from playwright.async_api import async_playwright

BASE = Path(r"C:\Users\asddd\Downloads\BLUEVIEW-APP-main\BLUEVIEW-APP-main\play-store-assets\screenshots")

EMAIL = "test@test.com"
PASSWORD = "test"
SITE = "https://www.levelog.com"
API  = "https://api.levelog.com"

PROJ_ID = "69dfe89f079abf2b78ee01e6"   # 432 Park Ave
TODAY   = "2026-04-15"

SCREENS = [
    ("01-dashboard",      "/"),
    ("02-projects",       "/projects"),
    ("03-project-detail", f"/project/{PROJ_ID}"),
    ("04-logbooks",       "/logbooks"),
    ("05-jobsite-log",    f"/logbooks/daily_jobsite?projectId={PROJ_ID}&date={TODAY}"),
    ("06-toolbox-talk",   f"/logbooks/toolbox_talk?projectId={PROJ_ID}&date={TODAY}"),
    ("07-preshift",       f"/logbooks/preshift_signin?projectId={PROJ_ID}&date={TODAY}"),
    ("08-settings",       "/settings"),
]

# (label, logical_width, logical_height, dpr)
# Output size = logical * dpr. Targets Play Store spec.
DEVICES = [
    ("phone",      390,  693,  2.77),   # -> 1080x1920  (Pixel-ish, DPR 2.77)
    ("tablet-7",   720, 1152,  1.67),   # -> 1200x1920
    ("tablet-10",  800, 1280,  2.0),    # -> 1600x2560
]


def get_auth():
    """Hit /api/auth/login and return (token, user_json_str)."""
    body = json.dumps({"email": EMAIL, "password": PASSWORD}).encode()
    req = urllib.request.Request(
        f"{API}/api/auth/login",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read())
    token = data.get("token")
    user  = data.get("user") or {}
    if not token:
        raise RuntimeError(f"No token in response: {data}")
    return token, json.dumps(user)


async def capture_device(playwright, device_label, width, height, dpr, token, user_json):
    outdir = BASE / device_label
    outdir.mkdir(parents=True, exist_ok=True)

    browser = await playwright.chromium.launch()
    context = await browser.new_context(
        viewport={"width": width, "height": height},
        device_scale_factor=dpr,
        is_mobile=(device_label == "phone"),
        has_touch=True,
        color_scheme="dark",
    )
    page = await context.new_page()
    print(f"\n=== {device_label} ({width}x{height}) ===")

    # Plant the token BEFORE any app JS runs so the app boots authenticated
    await page.goto(SITE, wait_until="domcontentloaded")
    await page.evaluate(
        """({token, user}) => {
            localStorage.setItem('blueview_token', token);
            localStorage.setItem('blueview_user', user);
        }""",
        {"token": token, "user": user_json},
    )

    for label, path in SCREENS:
        url = f"{SITE}{path}"
        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(2000)  # let animations settle
            out = outdir / f"{label}.png"
            await page.screenshot(path=str(out), full_page=False)
            print(f"  saved {out.name}")
        except Exception as e:
            print(f"  FAILED {label}: {e}")

    await context.close()
    await browser.close()


async def main():
    print("Authenticating via API...")
    token, user = get_auth()
    print(f"  got token: {token[:20]}...")
    async with async_playwright() as p:
        for label, w, h, dpr in DEVICES:
            await capture_device(p, label, w, h, dpr, token, user)
    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
