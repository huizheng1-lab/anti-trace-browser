"""Regression test: dispatching many new_tab search actions in one response
must NOT burst them in the same UI tick, because sites' abuse detection flags
simultaneous automated requests. E.g. hitting google.com/search 10x within
~130ms reliably trips Google's "unusual traffic" interstitial on most of them
(reproduced: 8/10 blocked before the _finish_async spacing fix). With the
actions paced ~1.8s apart, all 10 should come back as real result pages."""
import io, json, os, sys, tempfile, shutil
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

SESSION_DIR = tempfile.mkdtemp(prefix="atb_spacing_")
os.environ["WEBVIEW2_USER_DATA_FOLDER"] = SESSION_DIR
os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = "--autoplay-policy=no-user-gesture-required"

import wx
from main import Browser

QUERIES = ["quantum computing basics", "deep sea creatures", "Renaissance art history",
           "sustainable architecture", "machine learning algorithms", "ancient Egyptian pyramids",
           "solar system exploration", "jazz music origins", "coral reef conservation",
           "black hole physics"]

BLOCK_MARKERS = ("unusual traffic", "captcha", "our systems have detected",
                  "verify you", "recaptcha", "not a robot")

RESULT = {"blocked": None, "total": None}

def main():
    app = wx.App(False)
    frame = Browser(); frame.Show()
    frame.set_autoskip(False)
    frame._toggle_assistant()
    panel = frame._assistant_panel

    actions = [{"action": "new_tab", "url": f"https://www.google.com/search?q={q.replace(' ','+')}"}
               for q in QUERIES]
    panel._finish_async(actions)

    def check():
        blocked = 0
        for i, wv in enumerate(frame._webviews):
            try:
                ok, raw = wv.RunScript(
                    "JSON.stringify({title:document.title,"
                    "bodyStart:(document.body.innerText||'').slice(0,120)})")
                d = json.loads(raw)
            except Exception:
                d = {}
            low = (d.get("title", "") + " " + d.get("bodyStart", "")).lower()
            is_blocked = any(k in low for k in BLOCK_MARKERS)
            print(f"  tab{i}: [{'BLOCKED' if is_blocked else 'ok'}] {d.get('title','')!r}")
            if is_blocked:
                blocked += 1
        RESULT["blocked"] = blocked
        RESULT["total"] = len(frame._webviews) - 1  # minus the initial home tab
        print(f"\n{RESULT['total'] - blocked}/{RESULT['total']} real results, {blocked} blocked")
        frame.Close()

    # ~1.8s spacing * 9 gaps = ~16.2s until the last tab starts; give it room to load.
    wx.CallLater(20000, check)
    wx.CallLater(28000, frame.Close)
    app.MainLoop()
    shutil.rmtree(SESSION_DIR, ignore_errors=True)
    # Allow at most 1 incidental block (Google's detection isn't 100%
    # deterministic) — fail if spacing regresses back to burst behavior.
    ok = RESULT["blocked"] is not None and RESULT["blocked"] <= 1
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    main()
