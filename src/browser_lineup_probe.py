"""Read-only browser comparison for MFL's current-week lineup form.

Identifies whether JavaScript changes starter selections after page load.
Never submits a form, records player names, saves screenshots, or logs IDs,
cookies, username, password, URLs, or complete HTML.
"""
from http.cookies import SimpleCookie
from urllib.parse import urlencode
import os

from playwright.sync_api import sync_playwright
from .mfl_owner_auth import _make_opener, owner_login, OwnerAuthError


def safe_counts(page):
    return page.evaluate("""() => {
        const f = document.querySelector('form[method="POST"],form[method="post"]');
        const boxes = f ? Array.from(f.querySelectorAll('input[type="checkbox"]')) : [];
        const selected = document.querySelector('select[name="WEEK"]') ||
                         document.querySelector('select[name="W"]');
        const hidden = f ? f.querySelector('input[type="hidden"][name="WEEK"]') : null;
        return {
          forms:document.forms.length,
          checkboxes:boxes.length,
          checked:boxes.filter(x=>x.checked).length,
          default_checked:boxes.filter(x=>x.defaultChecked).length,
          week_hidden:hidden && /^\\d{1,2}$/.test(hidden.value) ? hidden.value : null,
          week_selector:selected && /^\\d{1,2}$/.test(selected.value) ? selected.value : null,
          week_option_count:selected ? selected.options.length : 0,
          form_method:f ? f.method.toLowerCase() : null
        };
    }""")


def run():
    year = os.getenv("MFL_SEASON") or "2026"
    league = os.getenv("MFL_LEAGUE_ID") or ""
    franchise = os.getenv("MFL_FRANCHISE_ID") or ""
    username = os.getenv("MFL_OWNER_USERNAME") or ""
    password = os.getenv("MFL_OWNER_PASSWORD") or ""
    if not all((username, password, year.isdigit(), league.isdigit(), franchise.isdigit())):
        print("BROWSER PROBE: missing owner login or numeric league identifiers")
        return

    opener = _make_opener()
    try:
        cookie = owner_login(opener, year, username, password, league)
    except OwnerAuthError:
        print("BROWSER PROBE: owner login unavailable; no lineup submitted")
        return
    parsed = SimpleCookie()
    parsed.load(cookie)
    cookies = [
        {"name": key, "value": morsel.value,
         "domain": "www46.myfantasyleague.com", "path": "/", "secure": True}
        for key, morsel in parsed.items()
    ]
    cookie = ""
    if not cookies:
        print("BROWSER PROBE: no usable session cookies")
        return

    base = f"https://www46.myfantasyleague.com/{year}/lineup?"
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context()
        context.add_cookies(cookies)
        for variant, data in (
            ("default", {"L":league, "FRANCHISE":franchise}),
            ("WEEK12", {"L":league, "FRANCHISE":franchise, "WEEK":"12"}),
        ):
            url = base + urlencode(data)
            page = context.new_page()
            seen = []
            def observe(req):
                if req.method != "GET":
                    return
                path = req.url.split("?")[0].rsplit("/",1)[-1].lower()
                for tag in ("lineup", "options", "ajax", "export", "score", "roster"):
                    if tag in path:
                        seen.append(tag)
                        break
            page.on("request",observe)
            try:
                response = page.goto(url, wait_until="domcontentloaded",timeout=30000)
                initial = safe_counts(page)
                page.wait_for_timeout(5000)
                final = safe_counts(page)
                print(f"BROWSER PROBE {variant}: http_ok={bool(response and response.status==200)}"
                      f" initial={initial} after_js={final} "
                      f"recognized_get_requests={sorted(set(seen))}")
            except Exception:
                print(f"BROWSER PROBE {variant}: navigation_or_evaluation_failed")
            finally:
                page.close()
        context.close()
        browser.close()


if __name__=="__main__":
    run()
