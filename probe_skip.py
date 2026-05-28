"""End-to-end: simulate YouTube's late-appearing skip button and verify our
polling click action actually clicks it."""
import base64, io, json, os, sys, tempfile, shutil

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# Fresh session dir so we don't disturb the user's running browser.
SESSION_DIR = tempfile.mkdtemp(prefix="atb_skip_")
os.environ["WEBVIEW2_USER_DATA_FOLDER"] = SESSION_DIR
os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = "--autoplay-policy=no-user-gesture-required"

import wx
from main import Browser

HTML = """
<!doctype html><html><body style="background:#222;color:#eee;font-family:sans-serif;padding:20px">
<h2>Synthetic YouTube ad-skip page</h2>
<p id="status">No skip button yet. (will appear after 4 seconds)</p>
<script>
  window._clickedAt = null;
  setTimeout(function(){
    var b = document.createElement('button');
    b.className = 'ytp-skip-ad-button';
    b.innerText = 'Skip Ad';
    b.style.cssText = 'font-size:20px;padding:10px 20px;background:#fff;color:#000;border:none;cursor:pointer';
    b.onclick = function(){
      window._clickedAt = Date.now();
      document.getElementById('status').innerText = 'Skip button was CLICKED!';
      b.disabled = true;
      b.innerText = 'Ad skipped';
    };
    document.body.appendChild(b);
    document.getElementById('status').innerText = 'Skip button appeared at t=' + Date.now();
    window._appearedAt = Date.now();
  }, 4000);
</script>
</body></html>
"""
URL = "data:text/html;base64," + base64.b64encode(HTML.encode()).decode()


def main():
    app = wx.App(False)
    frame = Browser()
    frame.Show()

    wv = frame.get_active_webview()
    wv.LoadURL(URL)
    start_ms = int(__import__("time").time() * 1000)
    print(f"[t=0] loaded ad-skip simulation page")

    state = {"step": 0, "ok": False}

    def step1_fire_click():
        # Fire the click action via the same code path the agent uses.
        action = {
            "action": "click",
            "selector": ".ytp-skip-ad-button",
        }
        # wait_ms default = 8000
        desc = frame._execute_agent_action(action)
        print(f"[t={int(__import__('time').time()*1000-start_ms)}] click dispatched: {desc}")

    def step2_check():
        wv2 = frame.get_active_webview()
        ok, raw = wv2.RunScript(
            "JSON.stringify({clicked: window._clickedAt, appeared: window._appearedAt})"
        )
        print(f"[t={int(__import__('time').time()*1000-start_ms)}] state: ok={ok} raw={raw}")
        try:
            obj = json.loads(raw)
            state["ok"] = obj.get("clicked") is not None
            if state["ok"]:
                delta = obj["clicked"] - (obj.get("appeared") or obj["clicked"])
                print(f"  >>> SUCCESS: button clicked {delta}ms after it appeared")
            else:
                print("  >>> FAIL: button was never clicked")
        except Exception as e:
            print(f"  parse error: {e}")
        frame.Close()

    # Fire click 500ms after load — well before the button appears at 4000ms.
    wx.CallLater(500, step1_fire_click)
    # Check at 8s — button appeared at 4s, click should have fired ~300ms after.
    wx.CallLater(8000, step2_check)
    # Hard timeout
    wx.CallLater(15000, frame.Close)

    app.MainLoop()
    shutil.rmtree(SESSION_DIR, ignore_errors=True)
    sys.exit(0 if state["ok"] else 1)


if __name__ == "__main__":
    main()
