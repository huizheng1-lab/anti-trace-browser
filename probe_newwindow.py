"""End-to-end test: a page using window.open() must spawn a new tab."""
import os
import sys
import tempfile

# Re-create env exactly like main.py.
SESSION_DIR = tempfile.mkdtemp(prefix="atb_probe_")
os.environ["WEBVIEW2_USER_DATA_FOLDER"] = SESSION_DIR
os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = "--autoplay-policy=no-user-gesture-required"

import wx
from main import Browser  # noqa: E402

PAGE = """data:text/html;base64,""" + __import__("base64").b64encode(b"""
<!doctype html><html><body>
<h2>NewWindow test</h2>
<a id="lnk" href="https://example.com/" target="_blank">open in new tab</a>
<script>
  // Auto-click after a brief delay. WebView2 generally honours target=_blank
  // even without strict user activation when the page itself initiates it.
  setTimeout(function(){
    document.getElementById('lnk').click();
  }, 400);
</script>
</body></html>
""").decode()


def main():
    app = wx.App(False)
    frame = Browser()
    frame.Show()

    # Active tab loads the test page.
    wv = frame.get_active_webview()
    wv.LoadURL(PAGE)

    initial = frame.notebook.GetPageCount()
    print(f"[probe] initial tabs: {initial}")

    result = {"opened": False, "count_after": initial}

    def check():
        result["count_after"] = frame.notebook.GetPageCount()
        result["opened"] = result["count_after"] > initial
        if result["opened"]:
            urls = []
            for i in range(frame.notebook.GetPageCount()):
                page = frame.notebook.GetPage(i)
                urls.append(f"  tab {i}: {page.GetCurrentURL()!r}")
            print("[probe] new tab opened. tabs now:")
            print("\n".join(urls))
        else:
            print(f"[probe] FAIL: still {result['count_after']} tab(s); new-window event did not fire.")
        frame.Close()

    wx.CallLater(3500, check)
    app.MainLoop()

    import shutil
    shutil.rmtree(SESSION_DIR, ignore_errors=True)
    sys.exit(0 if result["opened"] else 1)


if __name__ == "__main__":
    main()
