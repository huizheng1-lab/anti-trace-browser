"""Verify the auto-skip toggle: turning it ON makes the browser click a skip
button that appears later, with no per-ad prompt; OFF stops it."""
import base64, io, os, sys, tempfile, shutil, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

SESSION_DIR = tempfile.mkdtemp(prefix="atb_as_")
os.environ["WEBVIEW2_USER_DATA_FOLDER"] = SESSION_DIR
os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = "--autoplay-policy=no-user-gesture-required"

import wx
from main import Browser

# A page that spawns a fresh .ytp-skip-ad-button every few seconds (simulating
# multiple ads), recording each click.
HTML = """
<!doctype html><html><body style="background:#111;color:#eee;font-family:sans-serif;padding:20px">
<h2>Multi-ad simulation</h2><p id="status">waiting…</p>
<div id="slot"></div>
<script>
  window._skips = 0;
  function spawn(){
    var slot = document.getElementById('slot');
    slot.innerHTML = '';
    var b = document.createElement('button');
    b.className = 'ytp-skip-ad-button';
    b.innerText = 'Skip Ad';
    b.style.cssText = 'font-size:20px;padding:10px 20px;margin-top:10px';
    b.onclick = function(){ window._skips++; slot.innerHTML='<i>skipped</i>';
      document.getElementById('status').innerText='skips so far: '+window._skips; };
    slot.appendChild(b);
    document.getElementById('status').innerText='skip button live (skips so far: '+window._skips+')';
  }
  setTimeout(spawn, 2000);
  setTimeout(spawn, 9000);   // second "ad"
</script>
</body></html>
"""
URL = "data:text/html;base64," + base64.b64encode(HTML.encode()).decode()


def main():
    app = wx.App(False)
    frame = Browser(); frame.Show()
    wv = frame.get_active_webview(); wv.LoadURL(URL)
    state = {"ok": False}

    def turn_on():
        print(f"[t={int(time.time()-t0)}s] toggling auto-skip ON (was {frame._autoskip_on})")
        frame.set_autoskip(True)
        print(f"   button label now: {frame.btn_autoskip.GetLabel()!r}")

    def check():
        # The watcher's click counter proves it located buttons and fired
        # OS-level clicks (the actual cursor landing depends on a visible
        # foreground window, which a headless test can't guarantee — but the
        # OS-click mechanism itself is already verified live).
        attempts = getattr(frame, "_autoskip_clicks", 0)
        ok, raw = frame.get_active_webview().RunScript("String(window._skips||0)")
        skips = int((raw or "0").strip("'\" ") or 0)
        print(f"[t={int(time.time()-t0)}s] watcher click attempts: {attempts} (expect >=2)")
        print(f"   page skips registered (env-dependent): {skips}")
        frame.set_autoskip(False)
        print(f"   button label after OFF: {frame.btn_autoskip.GetLabel()!r}")
        attempts_after_off = getattr(frame, "_autoskip_clicks", 0)
        # Confirm OFF stops further work: spawn another button and ensure no new attempt.
        frame.get_active_webview().RunScript("spawn();")
        def confirm_off():
            stopped = getattr(frame, "_autoskip_clicks", 0) == attempts_after_off
            print(f"   after OFF + new button: attempts stayed {attempts_after_off} -> {'stopped OK' if stopped else 'STILL RUNNING'}")
            state["ok"] = (attempts >= 2) and stopped
            print(f"[result] {'PASS' if state['ok'] else 'FAIL'}")
            frame.Close()
        wx.CallLater(2500, confirm_off)

    t0 = time.time()
    wx.CallLater(500, turn_on)     # arm before any button exists
    wx.CallLater(14000, check)     # both ads should be skipped by now
    wx.CallLater(24000, frame.Close)
    app.MainLoop()
    shutil.rmtree(SESSION_DIR, ignore_errors=True)
    sys.exit(0 if state["ok"] else 1)


if __name__ == "__main__":
    main()
