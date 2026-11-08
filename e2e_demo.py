import json, sys, time
sys.stdout.reconfigure(encoding='utf-8')
from playwright.sync_api import sync_playwright
errors = []
img_src = None
with sync_playwright() as p:
    b = p.chromium.launch(headless=True,
        executable_path="C:/Program Files/Google/Chrome/Application/chrome.exe",
        args=["--no-sandbox"])
    pg = b.new_page()
    pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto("http://127.0.0.1:18733/demo", wait_until="networkidle")
    title = pg.title()
    models = pg.eval_on_selector("#model", "el => el.options.length")
    has_stats = pg.eval_on_selector("#stats", "el => el.textContent.length > 10")
    print(f"page: title={title!r} model_options={models} stats_loaded={has_stats}")
    pg.select_option("#model", "pix-editor-cheap")
    pg.fill("#prompt", "e2e test: make the sky golden at sunset")
    pg.click("#go")
    pg.wait_for_selector("#imgbox img", timeout=120000)
    img_src = pg.get_attribute("#imgbox img", "src")
    status_text = pg.inner_text("#status")
    print(f"result: {status_text}")
    print(f"img: {img_src[:100]}")
    pg.screenshot(path="C:/Users/Administrator.DESKTOP-EGNE9ND/Desktop/逆向产物/PixEditor/2api/demo_e2e.png", full_page=True)
    b.close()
print("console errors:", len(errors), errors[:3])
print("E2E:", "PASS" if not errors and img_src else "FAIL")
