"""End-to-end multi-page browsing test using a REAL localhost HTTP server
(data: URLs can't be navigated to by click — browsers block that). The agent
must click a link that navigates to /story, then click Recommend there."""
import io, json, os, sys, tempfile, shutil, threading, time
from http.server import BaseHTTPRequestHandler, HTTPServer
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

SESSION_DIR = tempfile.mkdtemp(prefix="atb_browse_")
os.environ["WEBVIEW2_USER_DATA_FOLDER"] = SESSION_DIR
os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = "--autoplay-policy=no-user-gesture-required"

HOME = """<!doctype html><html><head><title>Daily News</title></head>
<body style="font-family:sans-serif;padding:24px">
<nav><a href="/about">About</a> | <a href="/contact">Contact</a></nav>
<a href="https://ads.example.com/buy" style="color:gray">Sponsored: buy cheap widgets now</a>
<h2>Top Stories</h2>
<ul>
  <li><a href="/story">Breaking: City Council approves new riverside park</a></li>
  <li><a href="/weather">Weekend weather: sunny with light winds</a></li>
  <li><a href="/sports">Local team wins championship final</a></li>
</ul></body></html>"""

STORY = """<!doctype html><html><head><title>STORY PAGE</title></head>
<body style="font-family:sans-serif;padding:24px">
<h1 id="marker">Breaking: City Council approves new riverside park</h1>
<p>The council voted 7-2 in favour of the riverside park proposal...</p>
<button id="rec" onclick="window.__recommended=true;this.innerText='Recommended!'">Recommend this article</button>
</body></html>"""

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        body = STORY if self.path.startswith("/story") else HOME
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode())

srv = HTTPServer(("127.0.0.1", 0), H)
PORT = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{PORT}/"

import wx
from main import Browser, _load_minimax_key
if not _load_minimax_key():
    print("NO MINIMAX KEY"); sys.exit(2)

RESULTS = {}

def main():
    app = wx.App(False)
    frame = Browser(); frame.Show()
    frame.set_autoskip(False)
    frame._toggle_assistant()
    panel = frame._assistant_panel
    frame.get_active_webview().LoadURL(BASE)

    def fire():
        goal = "open the breaking news story about the new park, then recommend the article"
        print(f"=== goal: {goal}\n=== server: {BASE}")
        panel.input.SetValue(goal); panel._send()
        wx.CallLater(60000, check)

    def check():
        st = {}
        try:
            ok, raw = frame.get_active_webview().RunScript(
                "JSON.stringify({url:location.pathname,title:document.title,"
                "recommended:!!window.__recommended})")
            st = json.loads(raw)
        except Exception as e:
            print("read err", e)
        print("  final state:", st)
        RESULTS["nav"] = st.get("title") == "STORY PAGE"
        RESULTS["act"] = bool(st.get("recommended"))
        print(f"  navigated to story page: {'PASS' if RESULTS['nav'] else 'FAIL'}")
        print(f"  recommended on new page:  {'PASS' if RESULTS['act'] else 'FAIL'}")
        # dump last transcript lines for insight
        try:
            lines = panel.transcript.GetValue().strip().splitlines()
            print("  --- agent transcript (tail) ---")
            for ln in lines[-12:]:
                print("   ", ln)
        except Exception:
            pass
        panel.cancel_loop(); frame.Close()

    wx.CallLater(2000, fire)
    wx.CallLater(75000, frame.Close)
    app.MainLoop()
    srv.shutdown()
    shutil.rmtree(SESSION_DIR, ignore_errors=True)
    ok = RESULTS.get("nav") and RESULTS.get("act")
    print(f"\n=== RESULT: {'PASS' if ok else 'FAIL'}")
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    main()
