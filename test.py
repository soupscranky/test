import sys
import time
import argparse
import random
import requests
import json
import os
import csv
import inspect
import platform
from seleniumbase import SB
from utils import get_otp
from dotenv import load_dotenv

load_dotenv()

if platform.system() == "Windows":
    def lock_file(file):
        pass

    def unlock_file(file):
        pass
else:
    import fcntl

    def lock_file(file):
        fcntl.flock(file.fileno(), fcntl.LOCK_EX)

    def unlock_file(file):
        fcntl.flock(file.fileno(), fcntl.LOCK_UN)


DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

COUNTRY_POOL = [
    "United States of America",
    "Germany",
    "Great Britain",
    "France",
    "Japan",
    "Italy",
    "Australia",
    "Canada",
    "Spain",
    "Brazil",
]


def is_truthy(value):
    return str(value).lower() in {"1", "true", "yes", "y"}


def is_ci():
    return is_truthy(os.getenv("CI")) or is_truthy(os.getenv("GITHUB_ACTIONS"))


def build_chromium_args():
    width = random.randint(1200, 1440)
    height = random.randint(720, 900)
    return [
        "--no-sandbox",
        "--disable-dev-shm-usage",
        f"--window-size={width},{height}",
        "--disable-background-networking",
        "--disable-background-timer-throttling",
        "--disable-renderer-backgrounding",
        "--mute-audio",
    ]


def create_sb():
    is_github = is_ci()
    headless_env = is_truthy(os.getenv("HEADLESS"))
    chromium_args = build_chromium_args()

    try:
        sig_params = inspect.signature(SB).parameters
    except (TypeError, ValueError):
        sig_params = {}

    sb_kwargs = {"uc": True}

    if is_github:
        if "xvfb" in sig_params:
            sb_kwargs["xvfb"] = True
    elif headless_env:
        if "headless2" in sig_params:
            sb_kwargs["headless2"] = True
        elif "headless" in sig_params:
            sb_kwargs["headless"] = True

    if is_github or headless_env:
        for key in ("no_sandbox", "disable_gpu", "disable_dev_shm"):
            if key in sig_params:
                sb_kwargs[key] = True

    if chromium_args:
        if "chromium_arg" in sig_params:
            sb_kwargs["chromium_arg"] = chromium_args
        elif "chromium_args" in sig_params:
            sb_kwargs["chromium_args"] = chromium_args

    if sig_params:
        sb_kwargs = {k: v for k, v in sb_kwargs.items() if k in sig_params}
    sb = SB(**sb_kwargs)

    if (
        chromium_args
        and hasattr(sb, "add_chromium_arg")
        and "chromium_arg" not in sig_params
        and "chromium_args" not in sig_params
    ):
        for arg in chromium_args:
            try:
                sb.add_chromium_arg(arg)
            except Exception:
                pass

    return sb


def normalize_field(name):
    return name.strip().lower().replace(" ", "_").replace("-", "_")


def resolve_column(fieldnames, candidates):
    normalized = {normalize_field(name): name for name in fieldnames if name}
    for candidate in candidates:
        key = normalize_field(candidate)
        if key in normalized:
            return normalized[key]
    return None


import base64
import io

def load_row_by_index(row_index, data_path="data.csv"):
    if row_index < 0:
        return None, "invalid_index"

    file_content = None
    b64_data = os.getenv("DATA_CSV_B64")
    
    if b64_data:
        try:
            file_content = base64.b64decode(b64_data).decode('utf-8')
        except Exception:
            pass

    if not file_content:
        if not os.path.exists(data_path):
            return None, "missing_data"
        with open(data_path, "r", encoding="utf-8") as f:
            file_content = f.read()

    f_obj = io.StringIO(file_content)
    reader = csv.DictReader(f_obj)
    if not reader.fieldnames:
        return None, "missing_header"

    email_key = resolve_column(reader.fieldnames, ["email"])
    password_key = resolve_column(reader.fieldnames, ["password", "pass"])
    
    # Optional fields for login bot
    first_key = resolve_column(reader.fieldnames, ["first_name", "firstname", "first"])
    last_key = resolve_column(reader.fieldnames, ["last_name", "lastname", "last"])
    zip_key = resolve_column(reader.fieldnames, ["zip_code", "zipcode", "zip"])

    if not all([email_key, password_key]):
        return None, "missing_columns"

    for index, row in enumerate(reader):
        if index == row_index:
            row_data = {
                "email": row.get(email_key, "").strip(),
                "password": row.get(password_key, "").strip(),
                "first_name": row.get(first_key, "John").strip() if first_key else "John",
                "last_name": row.get(last_key, "Doe").strip() if last_key else "Doe",
                "zip_code": row.get(zip_key, "90210").strip() if zip_key else "90210",
            }
            if not row_data["email"] or not row_data["password"]:
                return None, "missing_values"
            return row_data, None

    return None, "no_rows"


def human_pause(sb, min_s=0.15, max_s=0.45):
    try:
        sb.cdp.sleep(random.uniform(min_s, max_s))
    except Exception:
        time.sleep(random.uniform(min_s, max_s))


def human_mouse_move(sb, selector):
    try:
        js_code = f"""
        (function() {{
            let el = null;
            const selector = {json.dumps(selector)};
            try {{
                el = document.querySelector(selector);
            }} catch(e) {{}}
            if (!el && selector.startsWith('/')) {{
                const result = document.evaluate(selector, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);
                el = result.singleNodeValue;
            }}
            if (!el) return null;
            el.scrollIntoView({{ block: 'center', inline: 'center' }});
            const rect = el.getBoundingClientRect();
            return {{
                x: rect.left + rect.width / 2 + (Math.random() - 0.5) * rect.width * 0.3,
                y: rect.top + rect.height / 2 + (Math.random() - 0.5) * rect.height * 0.3
            }};
        }})();
        """
        pos = sb.cdp.evaluate(js_code)
        if pos and "x" in pos and "y" in pos:
            sb.cdp.sleep(random.uniform(0.05, 0.15))
            sb.cdp.gui_hover_element(selector)
            sb.cdp.sleep(random.uniform(0.05, 0.1))
    except Exception:
        pass


def human_click(sb, selector):
    try:
        sb.cdp.wait_for_element(selector, timeout=10)
        human_pause(sb, 0.05, 0.2)
        human_mouse_move(sb, selector)
        sb.cdp.sleep(random.uniform(0.1, 0.25))
        sb.cdp.click(selector)
        sb.cdp.sleep(random.uniform(0.15, 0.35))
        return True
    except Exception:
        try:
            sb.cdp.click(selector)
            return True
        except Exception:
            print(f"Click failed on selector: {selector}")
            return False


def select_option_by_text_strict(sb, selector, text, timeout=10):
    try:
        sb.cdp.wait_for_element(selector, timeout=timeout)
        human_mouse_move(sb, selector)
        human_pause(sb, 0.05, 0.2)
        sb.cdp.select_option_by_text(selector, (text or "").strip())
        sb.cdp.sleep(random.uniform(0.2, 0.4))
        return True
    except Exception:
        pass

    js_code = f"""
    (function() {{
        let el = null;
        const selector = {json.dumps(selector)};
        const targetText = {json.dumps((text or "").strip())};
        try {{
            el = document.querySelector(selector);
        }} catch (e) {{}}
        if (!el && selector.startsWith('/')) {{
            const result = document.evaluate(selector, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);
            el = result.singleNodeValue;
        }}
        if (!el) return {{ok: false, reason: 'select not found'}};
        const options = Array.from(el.options || []);
        const match = options.find(o => (o.textContent || '').trim() === targetText);
        if (!match) return {{ok: false, reason: 'option not found'}};
        el.value = match.value;
        el.dispatchEvent(new Event('input', {{ bubbles: true }}));
        el.dispatchEvent(new Event('change', {{ bubbles: true }}));
        return {{ok: true}};
    }})();
    """
    result = sb.cdp.evaluate(js_code)
    return isinstance(result, dict) and result.get("ok", False)


def select_option_by_text_safe(sb, selector, text, timeout=10):
    def _alt_text_candidates(t):
        t = (t or "").strip()
        if not t:
            return []
        alts = [t]
        alt = t.replace("&", "and")
        if alt != t:
            alts.append(alt)
        alt2 = t.replace(" and ", " & ")
        if alt2 != t:
            alts.append(alt2)
        out = []
        for a in alts:
            if a not in out:
                out.append(a)
        return out

    try:
        sb.cdp.wait_for_element(selector, timeout=timeout)
        human_mouse_move(sb, selector)
        human_pause(sb, 0.05, 0.2)
        for candidate in _alt_text_candidates(text):
            try:
                sb.cdp.select_option_by_text(selector, candidate)
                sb.cdp.sleep(random.uniform(0.2, 0.4))
                return True
            except Exception:
                continue
    except Exception:
        pass

    js_code = f"""
    (function() {{
        let el = null;
        const selector = {json.dumps(selector)};
        const targetTextRaw = {json.dumps(text)};
        try {{
            el = document.querySelector(selector);
        }} catch (e) {{}}
        if (!el && selector.startsWith('/')) {{
            const result = document.evaluate(selector, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);
            el = result.singleNodeValue;
        }}
        if (!el) return {{ok: false, reason: 'select not found'}};

        const normalize = (s) => (s || '')
            .replace(/\\u00a0/g, ' ')
            .replace(/\\s+/g, ' ')
            .trim()
            .toLowerCase()
            .replace(/&/g, 'and');

        const options = Array.from(el.options || []);
        const targetText = (targetTextRaw || '').trim();
        const nt = normalize(targetText);
        if (!nt) return {{ok: false, reason: 'empty target text'}};

        let match = options.find(o => (o.textContent || '').trim() === targetText);

        if (!match) {{
            match = options.find(o => normalize(o.textContent) === nt);
        }}

        if (!match) {{
            match = options.find(o => normalize(o.textContent).includes(nt) || nt.includes(normalize(o.textContent)));
        }}

        if (!match) return {{ok: false, reason: 'option not found', text: nt, available: options.map(o=>normalize(o.textContent))}};

        el.focus();
        el.value = match.value;
        match.selected = true;
        
        // Angular deeply listens to these specific event sequences
        el.dispatchEvent(new Event('input', {{ bubbles: true, cancelable: true }}));
        el.dispatchEvent(new Event('change', {{ bubbles: true, cancelable: true }}));
        el.blur();

        return {{ok: true, chosen: (match.textContent || '').trim()}};
    }})();
    """
    result = sb.cdp.evaluate(js_code)
    return isinstance(result, dict) and result.get("ok", False)


def click_add_another_for_select(sb, selector, timeout=8):
    try:
        sb.cdp.wait_for_element(selector, timeout=timeout)
    except Exception:
        return False

    js_code = """
    (function() {
        let el = null;
        const selector = __SELECTOR__;
        try {
            el = document.querySelector(selector);
        } catch (e) {}
        if (!el && selector.startsWith('/')) {
            const result = document.evaluate(selector, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);
            el = result.singleNodeValue;
        }
        if (!el) return {ok: false, reason: 'select not found'};

        const isVisible = (node) => {
            if (!node) return false;
            const style = window.getComputedStyle(node);
            if (style.display === 'none' || style.visibility === 'hidden') return false;
            const r = node.getBoundingClientRect();
            return (r.width > 0 && r.height > 0);
        };

        const looksLikeAddAnother = (node) => {
            if (!node) return false;
            const t = (node.textContent || '').replace(/\\s+/g, ' ').trim().toLowerCase();
            return t === 'add another' || t.includes('add another');
        };

        const queryAddBtn = (root) => {
            if (!root || !root.querySelector) return null;
            return root.querySelector(
                '[data-qa="add-button"], button[data-qa="add-button"], span[data-qa="add-button"], [aria-label*="add another" i]'
            );
        };

        let container = el;
        for (let depth = 0; depth < 10 && container; depth++) {
            let btn = queryAddBtn(container);
            if (btn && isVisible(btn)) {
                btn.scrollIntoView({block: 'center', inline: 'center'});
                btn.click();
                return {ok: true, via: 'qa'};
            }

            const candidates = Array.from(container.querySelectorAll('button,a,span,div'))
                .filter(n => looksLikeAddAnother(n) && isVisible(n));
            if (candidates.length) {
                const chosen = candidates.find(n => n.tagName === 'BUTTON') || candidates[0];
                chosen.scrollIntoView({block: 'center', inline: 'center'});
                chosen.click();
                return {ok: true, via: 'text'};
            }

            container = container.parentElement;
        }

        return {ok: false, reason: 'add button not found'};
    })();
    """
    js_code = js_code.replace("__SELECTOR__", json.dumps(selector))

    result = sb.cdp.evaluate(js_code)
    if isinstance(result, dict) and result.get("ok", False):
        sb.cdp.sleep(random.uniform(0.4, 0.8))
        return True
    return False


def enter_otp_code(sb, otp, timeout=60, fallback_selector=None):
    otp = (otp or "").strip()
    if not otp:
        return False

    js_fill = f"""
    (function() {{
      const code = {json.dumps(otp)};
      const input = document.querySelector("#gigya-textbox-code") || document.querySelector("input[name='code']");
      if (input) {{
        try {{
          const proto = input.tagName === 'TEXTAREA' ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
          const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
          setter.call(input, code);
        }} catch(e) {{
          input.value = code;
        }}
        try {{ input.dispatchEvent(new Event('input', {{bubbles:true}})); }} catch(e){{}}
        try {{ input.dispatchEvent(new Event('change', {{bubbles:true}})); }} catch(e){{}}
        try {{ input.dispatchEvent(new KeyboardEvent('keyup', {{bubbles:true}})); }} catch(e){{}}
        return {{ok: true, mode: 'single_injection'}};
      }}
      return {{ok: false, reason: 'gigya-textbox-code element not found'}};
    }})();
    """

    end = time.time() + timeout
    last = None
    while time.time() < end:
        try:
            last = sb.cdp.evaluate(js_fill)
            if isinstance(last, dict) and last.get("ok"):
                return True
        except Exception:
            last = None
        sb.cdp.sleep(0.8)

    try:
        url = sb.cdp.get_current_url()
        print(f"OTP entry failed after timeout. url={url} last={last}")
    except Exception:
        pass

    return False


def select_nth_named_select_option(sb, name_contains, index, option_text, timeout=12):
    def _list_selects():
        js = f"""
        (function() {{
            const needle = {json.dumps(name_contains)};
            const selects = Array.from(document.querySelectorAll('select'))
                .filter(s => s && s.name && s.name.includes(needle))
                .map(s => ({{
                    name: s.name,
                    visible: true,
                    disabled: !!s.disabled,
                    options: (s.options ? s.options.length : 0)
                }}));
            return {{count: selects.length, selects}};
        }})();
        """
        return sb.cdp.evaluate(js) or {}

    for attempt in range(6):
        info = _list_selects()
        selects = info.get("selects") if isinstance(info, dict) else None
        if not selects:
            if attempt == 5 and is_truthy(os.getenv("DEBUG_DOM")):
                try:
                    all_names = sb.cdp.evaluate(
                        "(function(){return Array.from(document.querySelectorAll('select')).map(s=>s.name||s.id||null).filter(Boolean).slice(0,50)})();"
                    )
                    print(f"DEBUG_DOM no selects matching '{name_contains}'. First select names/ids: {all_names}")
                except Exception:
                    pass
            sb.cdp.sleep(0.8)
            continue

        if len(selects) < index:
            last_name = selects[-1].get("name")
            if last_name:
                last_sel = f"select[name={json.dumps(last_name)}]"
                click_add_another_for_select(sb, last_sel, timeout=4)
            sb.cdp.sleep(0.9)
            continue

        target = selects[index - 1]
        target_name = target.get("name")
        target_visible = target.get("visible")

        if not target_name:
            sb.cdp.sleep(0.5)
            continue

        target_selector = f"select[name={json.dumps(target_name)}]"
        return select_option_by_text_safe(sb, target_selector, option_text, timeout=timeout)

    return False


def select_random_option_in_nth_named_select(sb, name_contains, index, exclude_texts=None, include_texts=None, timeout=12):
    exclude_texts = {t.strip() for t in (exclude_texts or []) if t and str(t).strip()}
    include_texts = {t.strip() for t in (include_texts or []) if t and str(t).strip()}

    js = f"""
    (function() {{
        const needle = {json.dumps(name_contains)};
        const selects = Array.from(document.querySelectorAll('select'))
            .filter(s => s && s.name && s.name.includes(needle));
        const i = {index} - 1;
        if (selects.length <= i) return {{ok:false, reason:'select index missing', count: selects.length}};
        const sel = selects[i];
        const options = Array.from(sel.options || [])
            .map(o => ({{
                text: (o.textContent || '').replace(/\\s+/g,' ').trim(),
                value: o.value,
                disabled: !!o.disabled
            }}));
        return {{
            ok: true,
            name: sel.name,
            visible: true,
            options
        }};
    }})();
    """

    info = sb.cdp.evaluate(js)
    if not (isinstance(info, dict) and info.get("ok")):
        return None

    sel_name = info.get("name")
    options = info.get("options") or []
    if not sel_name or not options:
        return None

    cleaned = []
    for opt in options:
        t = (opt.get("text") or "").strip()
        if not t:
            continue
        lt = t.lower()
        if lt in {"select", "select one", "please select", "-", "--"}:
            continue
        if t in exclude_texts:
            continue
        if include_texts and t not in include_texts:
            continue
        if opt.get("disabled"):
            continue
        cleaned.append(t)

    if not cleaned:
        return None

    random.shuffle(cleaned)
    target_selector = f"select[name={json.dumps(sel_name)}]"
    for candidate in cleaned[:10]:
        if select_option_by_text_safe(sb, target_selector, candidate, timeout=timeout):
            return candidate

    return None


def human_type(sb, selector, text):
    try:
        sb.cdp.wait_for_element(selector, timeout=10)
        human_mouse_move(sb, selector)
        human_pause(sb, 0.1, 0.3)
        sb.cdp.click(selector)
        human_pause(sb, 0.1, 0.2)
        sb.cdp.type(selector, text)
        human_pause(sb, 0.2, 0.4)
    except Exception as e:
        print(f"Typing error on selector: {selector} - {e}")
        try:
            # Fallback to JS typing if standard CDP interaction fails
            js_code = f"""
            (function() {{
                const el = document.querySelector({json.dumps(selector)});
                if (!el) return false;
                el.value = {json.dumps(text)};
                el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                return true;
            }})();
            """
            success = sb.cdp.evaluate(js_code)
            if not success:
               sb.cdp.type(selector, text)
        except Exception as fallback_e:
            print(f"Fallback typing failed: {fallback_e}")


def run_task(
    email,
    password,
    first_name,
    last_name,
    zip_code,
    country="United States of America",
    row_index=None,
):
    row_label = f"row index {row_index}" if row_index is not None else "manual run"
    print(f"Starting task for {row_label}")

    sb = create_sb()
    with sb as sb:
        try:
            try:
                sb.driver.set_page_load_timeout(60)
                sb.driver.set_script_timeout(60)
                sb.driver.implicitly_wait(5)
                sb.driver.set_window_size(
                    random.randint(1200, 1440),
                    random.randint(720, 900),
                )
            except Exception:
                pass

            try:
                stealth_js = """
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                window.chrome = { runtime: {} };
                Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3]});
                Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
                try { 
                    const originalQuery = window.navigator.permissions.query;
                    window.navigator.permissions.query = (parameters) => (
                      parameters.name === 'notifications' ?
                        Promise.resolve({ state: Notification.permission }) :
                        originalQuery(parameters)
                    );
                } catch(e) {}
                """
                sb.driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": stealth_js})
            except Exception:
                pass

            print("Navigating to target page via CDP Mode...")
            for attempt in range(3):
                try:
                    sb.activate_cdp_mode("https://tickets.la28.org/mycustomerdata/?affiliate=28A")
                    break
                except Exception:
                    if attempt == 2:
                        raise
                    time.sleep(2)

            print("Waiting for Gigya UI to render...")
            try:
                # Wait for any gigya input to exist, signifying the framework has loaded
                sb.cdp.wait_for_element("input.gigya-input-text", timeout=20)
                sb.cdp.sleep(1.5)
            except Exception:
                sb.cdp.sleep(5)
                
            print("Switching to Login form...")
            try:
                js = """
                (function(){
                  const all_els = Array.from(document.querySelectorAll('a, button, div, span, h2'));
                  const isLogin = all_els.some(el => (el.textContent||'').toLowerCase().includes('log in to your la28 id'));
                  if (isLogin) {
                      return "Already on Login form";
                  }
                  
                  const cand = Array.from(document.querySelectorAll('a, button')).find(el => {
                      const t = (el.textContent||'').toLowerCase();
                      return t.includes('already have an account');
                  });
                  if (cand) {
                      cand.scrollIntoView({block:'center', inline:'center'});
                      cand.click();
                      return "Clicked switch: " + cand.textContent;
                  }
                  return "Switch link not found";
                })();
                """
                res = sb.cdp.evaluate(js)
                print(f"Switch result: {res}")
                sb.cdp.sleep(2)
            except Exception as e:
                print(f"Switch failed: {e}")

            email_selector = "form.gigya-login-form input[name='email'], #gigya-login-screen input[name='loginID'], input[name='email']"
            
            print("Waiting for login form to load...")
            try:
                sb.cdp.wait_for_element("input[name='email']:not([hidden]), form.gigya-login-form input", timeout=10)
                human_pause(sb, 0.8, 1.6)
            except Exception:
                # Debug why it's invisible
                dbg = sb.cdp.evaluate("""
                (function(){
                  const els = Array.from(document.querySelectorAll('input[name="email"], input[type="email"], input.gigya-input-text'));
                  return els.map(e => ({
                    name: e.name, className: e.className, id: e.id,
                    rect: e.getBoundingClientRect(),
                    w: e.offsetWidth, h: e.offsetHeight,
                    parentClass: e.parentElement ? e.parentElement.className : ''
                  }));
                })();
                """)
                print(f"DEBUG VISIBILITY: {dbg}")
                sb.cdp.sleep(2)
            print("Login form load wait complete.")

            try:
                if sb.cdp.is_element_visible("button#onetrust-accept-btn-handler"):
                    print("Accepting cookies...")
                    human_click(sb, "button#onetrust-accept-btn-handler")
                    human_pause(sb, 0.3, 0.7)
            except Exception:
                pass

            print("Filling login credentials...")
            js_fill = f"""
            (function(){{
                const isVis = (el) => {{
                    if(!el) return false;
                    const r = el.getBoundingClientRect();
                    return r.width > 0 && r.height > 0;
                }};
                
                const texts = Array.from(document.querySelectorAll('input[type="text"], input[type="email"], input.gigya-input-text'));
                const visEmail = texts.find(e => isVis(e) && (e.name === 'email' || e.name === 'username' || e.name === 'loginID' || (e.name||'').includes('email')));
                
                const passes = Array.from(document.querySelectorAll('input[type="password"]'));
                const visPass = passes.find(e => isVis(e));
                
                if(visEmail) {{
                    visEmail.value = {json.dumps(email)};
                    visEmail.dispatchEvent(new Event('input', {{bubbles: true}}));
                    visEmail.dispatchEvent(new Event('change', {{bubbles: true}}));
                }}
                
                if(visPass) {{
                    visPass.value = {json.dumps(password)};
                    visPass.dispatchEvent(new Event('input', {{bubbles: true}}));
                    visPass.dispatchEvent(new Event('change', {{bubbles: true}}));
                }}
                
                return {{emailFound: !!visEmail, passFound: !!visPass}};
            }})();
            """
            
            fill_res = sb.cdp.evaluate(js_fill)
            print(f"DEBUG FILL: {fill_res}")
            sb.cdp.sleep(1)
            
            print("Submitting login... (Double click to clear overlays)")
            try:
                js_submit = """
                (function(){
                  const findBtn = () => {
                      const btns = Array.from(document.querySelectorAll('input.gigya-input-submit, input[data-gigya-type="submit"], button, input[type="submit"]'));
                      return btns.find(b => {
                          const r = b.getBoundingClientRect();
                          if(r.width === 0 || r.height === 0) return false;
                          const t = (b.value || b.innerText || '').toLowerCase();
                          return t.includes('log in') || t.includes('login') || t.includes('submit');
                      });
                  };
                  
                  const btn = findBtn();
                  if(btn) {
                      btn.scrollIntoView({block:'center', inline:'center'});
                      btn.click();
                      return true;
                  }
                  return false;
                })();
                """
                # First click (dismisses popup)
                sb.cdp.evaluate(js_submit)
                sb.cdp.sleep(1)
                
                # Second click (actual submit)
                sb.cdp.evaluate(js_submit)
                sb.cdp.sleep(1)
                
            except Exception as e:
                print(f"Submit error: {e}")
                
            birth_year_selector = 'select[name^="additionalCustomerAttributes"]'

            print("Waiting for profile page to load...")
                
            profile_loaded = False
            for _ in range(30):
                try:
                    is_ready = sb.cdp.evaluate("document.querySelector('select[name^=\"additionalCustomerAttributes\"]') !== null")
                    if is_ready:
                        profile_loaded = True
                        break
                except Exception:
                    pass
                sb.cdp.sleep(1)
                
            if not profile_loaded:
                print("ERROR: Profile page failed to load after 30 seconds. Taking screenshot and exiting.")
                try:
                    sb.driver.save_screenshot("debug_login_fail.png")
                except Exception:
                    pass
                return False
                
            print("Profile page load wait complete.")

            print("Profile page loaded.")
            human_pause(sb, 0.8, 1.6)

            birth_years = [
                "1960",
                "1961",
                "1962",
                "1963",
                "1964",
                "1965",
                "1966",
                "1967",
                "1968",
                "1969",
                "1970",
                "1971",
                "1972",
                "1973",
                "1974",
                "1975",
                "1976",
                "1977",
                "1978",
                "1979",
                "1980",
                "1981",
                "1982",
                "1983",
                "1984",
                "1985",
                "1986",
                "1987",
                "1988",
                "1989",
                "1990",
                "1991",
                "1992",
                "1993",
                "1994",
                "1995",
                "1996",
                "1997",
                "1998",
                "1999",
                "2000",
                "2001",
                "2002",
                "2003",
                "2004",
                "2005",
                "2006",
                "2007",
            ]

            print("Selecting birth year...")
            try:
                chosen_year = select_random_option_in_nth_named_select(
                    sb,
                    name_contains="additionalCustomerAttributes",
                    index=1,
                    exclude_texts=[],
                    include_texts=birth_years,
                    timeout=14,
                )
                if chosen_year:
                    print(f"  Selected birth year: {chosen_year}")
                    human_pause(sb, 0.8, 1.6)
                else:
                    random_year = random.choice(birth_years)
                    if select_option_by_text_safe(sb, birth_year_selector, random_year, timeout=12):
                        print(f"  Selected birth year (fallback): {random_year}")
                        human_pause(sb, 0.8, 1.6)
                    else:
                        print("  Birth year selection failed.")
            except Exception:
                print("  Birth year selection failed.")

            if is_truthy(os.getenv("DEBUG_DOM")):
                try:
                    js = """
                    (function(){
                      const selects = Array.from(document.querySelectorAll('select'))
                        .map(s => ({name: s.name || null, id: s.id || null}))
                        .filter(x => x.name || x.id);
                      const fav = selects.filter(x => (x.name||'').toLowerCase().includes('favorite') || (x.id||'').toLowerCase().includes('favorite'));
                      return {
                        totalSelects: selects.length,
                        first10: selects.slice(0,10),
                        favorites: fav.slice(0,30),
                      };
                    })();
                    """
                    dbg = sb.cdp.evaluate(js)
                    print(f"DEBUG_DOM selects: {dbg}")
                except Exception:
                    pass

            # --- Expand sports dropdowns to 5 slots ---
            print("Expanding Olympic Sports dropdowns to 5 slots...")
            for click_attempt in range(4):
                vis_count = sb.cdp.evaluate("""
                (function(){
                    const sels = Array.from(document.querySelectorAll('select'));
                    return sels.filter(s => {
                        const r = s.getBoundingClientRect();
                        return r.width > 0 && r.height > 0 && (s.id||'').includes('categoryFavorites288');
                    }).length;
                })();
                """)
                print(f"  Visible sport selects: {vis_count}")
                if vis_count >= 5:
                    break
                
                try:
                    add_els = sb.cdp.find_elements_by_text("Add another")
                    # Click the first visible one (sports section is above teams)
                    clicked = False
                    for el in add_els:
                        try:
                            el.scroll_into_view()
                            el.mouse_click()
                            clicked = True
                            print(f"  Clicked 'Add another' (sports) via mouse_click")
                            break
                        except Exception:
                            continue
                    if not clicked:
                        print("  No clickable 'Add another' found for sports")
                        break
                except Exception as e:
                    print(f"  Error finding 'Add another': {e}")
                    break
                sb.cdp.sleep(1.5)

            olympic_sports = [
                "Basketball",
                "Swimming",
                "Artistic Gymnastics",
                "Athletics",
                "Football (Soccer)",
                "Baseball",
                "Olympic Ceremonies",
                "Beach Volleyball",
                "Tennis",
                "Golf",
                "Softball",
                "Volleyball",
                "Wrestling",
                "Boxing",
                "Skateboarding",
            ]

            chosen_sports = random.sample(olympic_sports, k=5)

            print(f"Selecting Olympic sport preferences ({len(chosen_sports)})...")
            selected_sports = []
            for i, sport in enumerate(chosen_sports, start=1):
                select_timeout = 15 if i == 1 else 12
                if select_nth_named_select_option(
                    sb,
                    name_contains="categoryFavorites288",
                    index=i,
                    option_text=sport,
                    timeout=select_timeout,
                ):
                    print(f"  Selected Olympic sport {i}: {sport}")
                    selected_sports.append(sport)
                    human_pause(sb, 0.6, 1.2)
                else:
                    chosen = select_random_option_in_nth_named_select(
                        sb,
                        name_contains="categoryFavorites288",
                        index=i,
                        exclude_texts=selected_sports,
                        timeout=select_timeout,
                    )
                    if chosen:
                        print(f"  Selected Olympic sport {i} (fallback): {chosen}")
                        selected_sports.append(chosen)
                        human_pause(sb, 0.6, 1.2)
                    else:
                        print(f"  Olympic sport {i} selection failed.")

            # --- Expand teams dropdowns to 3 slots ---
            print("Expanding Olympic & Paralympic Teams dropdowns to 3 slots...")
            for click_attempt in range(2):
                vis_count = sb.cdp.evaluate("""
                (function(){
                    const sels = Array.from(document.querySelectorAll('select'));
                    return sels.filter(s => {
                        const r = s.getBoundingClientRect();
                        return r.width > 0 && r.height > 0 && ((s.id||'').includes('artistFavorites') || (s.id||'').includes('categoryFavorites289'));
                    }).length;
                })();
                """)
                print(f"  Visible team selects: {vis_count}")
                if vis_count >= 3:
                    break
                
                try:
                    add_els = sb.cdp.find_elements_by_text("Add another")
                    # Click the LAST visible one (teams section is below sports)
                    clicked = False
                    for el in reversed(add_els):
                        try:
                            el.scroll_into_view()
                            el.mouse_click()
                            clicked = True
                            print(f"  Clicked 'Add another' (teams) via mouse_click")
                            break
                        except Exception:
                            continue
                    if not clicked:
                        print("  No clickable 'Add another' found for teams")
                        break
                except Exception as e:
                    print(f"  Error finding 'Add another': {e}")
                    break
                sb.cdp.sleep(1.5)

            teams = random.sample(COUNTRY_POOL, k=3)

            print(f"Selecting team preferences ({len(teams)})...")
            for i, team in enumerate(teams, start=1):
                select_timeout = 15 if i == 1 else 12
                if select_nth_named_select_option(
                    sb,
                    name_contains="artistFavorites",
                    index=i,
                    option_text=team,
                    timeout=select_timeout,
                ):
                    print(f"  Selected team {i}: {team}")
                    human_pause(sb, 0.6, 1.2)
                else:
                    print(f"  Team {i} selection failed.")
                    continue

            print("Saving profile...")

            save_clicked = False
            for sel in [
                "button.btn-primary.btn-xlg",  # Based on standard button classes found
                "button[class*='theme-interaction-btn-bg']",
                "app-sports-profile-save-section button",
                "app-sports-profile-save-section ev-pl-button button",
            ]:
                if human_click(sb, sel):
                    save_clicked = True
                    break

            if not save_clicked:
                print("Save button click failed with CSS, trying JS fallback.")
                try:
                    js = """
                    (function(){
                      const norm = (t)=> (t||'').replace(/\\s+/g,' ').trim().toLowerCase();
                      const nodes = Array.from(document.querySelectorAll('button,[role="button"],a,input[type="button"],input[type="submit"]'));
                      const cand = nodes.find(n=>{const t=norm(n.textContent||n.value||n.getAttribute('aria-label')||''); return t==='save' || t.includes('save') || t.includes('submit');});
                      if(!cand) return {ok:false};
                      cand.scrollIntoView({block:'center', inline:'center'});
                      cand.click();
                      return {ok:true};
                    })();
                    """
                    r = sb.cdp.evaluate(js)
                    if isinstance(r, dict) and r.get("ok"):
                        save_clicked = True
                except Exception:
                    pass

            human_pause(sb, 4, 6)

            final_url = sb.cdp.get_current_url()
            if "mydatasuccess" in final_url:
                print("=" * 60)
                print("TASK COMPLETED SUCCESSFULLY!")
                print("=" * 60)

                if DISCORD_WEBHOOK_URL:
                    send_discord_webhook(row_index=row_index)
                return True
            else:
                print("Profile saved, checking status...")
                return True

        except Exception:
            print("Error in execution.")
            return False


def send_discord_webhook(row_index=None):
    if not DISCORD_WEBHOOK_URL:
        return

    fields = []
    if row_index is not None:
        fields.append({"name": "Row Index", "value": str(row_index), "inline": True})

    embed = {
        "title": "Task Completed Successfully",
        "color": 5763719,
        "fields": fields,
        "footer": {"text": "Test Bot"},
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
    }

    payload = {"embeds": [embed]}

    try:
        response = requests.post(DISCORD_WEBHOOK_URL, json=payload)
        if response.status_code == 204:
            print("Discord webhook sent successfully")
        else:
            print(f"Discord webhook failed: {response.status_code}")
    except Exception as e:
        print(f"Discord webhook error: {e}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--row-index", type=int, default=None)
    parser.add_argument("--email")
    parser.add_argument("--password")
    parser.add_argument("--first")
    parser.add_argument("--last")
    parser.add_argument("--zip")

    args = parser.parse_args()

    if args.row_index is not None:
        row_data, reason = load_row_by_index(args.row_index)
        if reason == "no_rows":
            print("No rows remaining for the requested index.")
            sys.exit(0)
        if row_data is None:
            if reason == "missing_data":
                print("data.csv not found.")
            elif reason == "missing_columns":
                print("data.csv is missing required columns.")
            elif reason == "missing_values":
                print("Selected row is missing required values.")
            elif reason == "invalid_index":
                print("Row index must be >= 0.")
            else:
                print("Failed to load row for processing.")
            sys.exit(1)

        success = run_task(
            email=row_data["email"],
            password=row_data["password"],
            first_name=row_data["first_name"],
            last_name=row_data["last_name"],
            zip_code=row_data["zip_code"],
            row_index=args.row_index,
        )
        sys.exit(0 if success else 1)

    if args.email:
        if not all([args.password, args.first, args.last, args.zip]):
            print("Direct mode requires email, password, first, last, and zip.")
            sys.exit(1)
        success = run_task(
            args.email,
            args.password,
            args.first,
            args.last,
            args.zip,
            row_index=None,
        )
        sys.exit(0 if success else 1)

    parser.error("Requires --row-index or --email.")


if __name__ == "__main__":
    main()
