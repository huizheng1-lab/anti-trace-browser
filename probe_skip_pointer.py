"""Verify pointer events fire — YouTube's player listens for pointerdown/mousedown
and ignores synthetic .click() in some cases. We simulate that."""
import base64, io, json, os, sys, tempfile, shutil, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

SESSION_DIR = tempfile.mkdtemp(prefix="atb_ptr_")
os.environ["WEBVIEW2_USER_DATA_FOLDER"] = SESSION_DIR
os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = "--autoplay-policy=no-user-gesture-required"

import wx
from main import Browser

# Note the listener: only pointerdown counts as a real click. plain .click() does nothing.
HTML = """
<!doctype html><html><body style="background:#222;color:#eee;font-family:sans-serif;padding:20px">
<h2>Pointer-event-only skip button</h2>
<p id="status">No button yet (appears in 2s)</p>
<script>
  window._events = [];
  setTimeout(function(){
    var b = document.createElement('button');
    b.className = 'ytp-skip-ad-button';
    b.innerText = 'Skip Ad';
    b.style.cssText = 'font-size:20px;padding:10px 20px;background:#fff;color:#000;border:none;cursor:pointer';
    // Block normal click so only pointer events register success.
    b.addEventListener('click', function(e){ window._events.push('click'); e.stopPropagation(); }, true);
    b.addEventListener('pointerdown', function(){
      window._events.push('pointerdown');
      window._skipped = Date.now();
      document.getElementById('status').innerText = 'pointerdown received! skip honoured';
    });
    b.addEventListener('mousedown', function(){ window._events.push('mousedown'); });
    document.body.appendChild(b);
    window._appeared = Date.now();
    document.getElementById('status').innerText = 'Button live; awaiting pointerdown…';
  }, 2000);
</script>
</body></html>
"""
URL = "data:text/html;base64," + base64.b64encode(HTML.encode()).decode()

def main():
    app = wx.App(False)
    frame = Browser(); frame.Show()
    wv = frame.get_active_webview(); wv.LoadURL(URL)
    t0 = time.time() * 1000
    print(f"[t=0] loaded pointer-only skip page")

    state = {"ok": False}

    def fire_click():
        desc = frame._execute_agent_action({"action":"click","text":"Skip"})
        print(f"[t={int(time.time()*1000-t0)}] click via text matcher: {desc}")

    def check():
        ok, raw = frame.get_active_webview().RunScript(
            "JSON.stringify({events: window._events, skipped: window._skipped, appeared: window._appeared})"
        )
        print(f"[t={int(time.time()*1000-t0)}] state: {raw}")
        try:
            obj = json.loads(raw)
            state["ok"] = obj.get("skipped") is not None
            if state["ok"]:
                print(f"  >>> SUCCESS: pointerdown fired; events={obj.get('events')}")
            else:
                print(f"  >>> FAIL: events={obj.get('events')}")
        except Exception as e:
            print(f"  parse error: {e}")
        frame.Close()

    wx.CallLater(300, fire_click)         # fire before button exists (polling kicks in)
    wx.CallLater(6000, check)             # button appears at 2s; check at 6s
    wx.CallLater(10000, frame.Close)
    app.MainLoop()
    shutil.rmtree(SESSION_DIR, ignore_errors=True)
    sys.exit(0 if state["ok"] else 1)

if __name__ == "__main__":
    main()
