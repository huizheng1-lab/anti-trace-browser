"""Real-world test: open kuaishou.com, click the 直播 (LIVE) button, expect a new tab."""
import io
import os
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

SESSION_DIR = tempfile.mkdtemp(prefix="atb_ks_")
os.environ["WEBVIEW2_USER_DATA_FOLDER"] = SESSION_DIR
os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = "--autoplay-policy=no-user-gesture-required"

import wx
import wx.html2
from main import Browser  # noqa: E402

START_URL = "https://www.kuaishou.com/"

# Find every anchor/button whose text or aria-label contains 直播 or LIVE, log them,
# and click the first one. The click runs inside a synthetic user-gesture handler
# (button.click in JS) which WebView2 allows via target=_blank or window.open.
CLICK_LIVE_JS = r"""
(function(){
  var hits = [];
  var nodes = document.querySelectorAll('a,button,[role="button"]');
  for (var i=0;i<nodes.length;i++){
    var n = nodes[i];
    var txt = (n.innerText||'') + ' ' + (n.getAttribute('aria-label')||'') + ' ' + (n.title||'');
    if (/直播|LIVE/i.test(txt)) {
      hits.push({
        tag: n.tagName,
        href: n.href || '',
        text: (n.innerText||'').slice(0,40).replace(/\s+/g,' ').trim(),
      });
    }
  }
  document.title = '__HITS__' + JSON.stringify(hits).slice(0,400);
  // Click the first match.
  for (var j=0;j<nodes.length;j++){
    var m = nodes[j];
    var t = (m.innerText||'') + ' ' + (m.getAttribute('aria-label')||'') + ' ' + (m.title||'');
    if (/直播|LIVE/i.test(t)) {
      m.click();
      return 'clicked: ' + (m.innerText||'').slice(0,40);
    }
  }
  return 'no live element found';
})();
"""


def main():
    app = wx.App(False)
    frame = Browser()
    frame.Show()

    wv = frame.get_active_webview()
    wv.LoadURL(START_URL)
    initial_tabs = frame.notebook.GetPageCount()
    state = {"step": "loading_home", "msg": "", "tabs_after_click": initial_tabs, "ok": False}

    def after_load(_evt=None):
        if state["step"] != "loading_home":
            return
        state["step"] = "clicked"
        print(f"[probe] home loaded: {wv.GetCurrentURL()!r} (title={wv.GetCurrentTitle()!r})")
        # Give the SPA a moment to render dynamic nav.
        wx.CallLater(2500, do_click)

    def do_click(*_):
        wv.RunScript(CLICK_LIVE_JS)
        # WebView2 RunScript is async; sample title shortly after.
        wx.CallLater(500, sample)

    def sample():
        title = wv.GetCurrentTitle() or ""
        if "__HITS__" in title:
            print("[probe] candidates: " + title.split("__HITS__", 1)[1])
        wx.CallLater(3500, finalize)

    def finalize():
        state["tabs_after_click"] = frame.notebook.GetPageCount()
        state["ok"] = state["tabs_after_click"] > initial_tabs or (
            wv.GetCurrentURL() and "live.kuaishou" in wv.GetCurrentURL()
        )
        print(f"[probe] tabs before: {initial_tabs}  after: {state['tabs_after_click']}")
        for i in range(frame.notebook.GetPageCount()):
            print(f"  tab {i}: {frame.notebook.GetPage(i).GetCurrentURL()!r}")
        frame.Close()

    wv.Bind(wx.html2.EVT_WEBVIEW_LOADED, after_load)
    # Hard timeout
    wx.CallLater(25000, lambda: frame.Close())

    app.MainLoop()

    import shutil
    shutil.rmtree(SESSION_DIR, ignore_errors=True)
    sys.exit(0 if state["ok"] else 1)


if __name__ == "__main__":
    main()
