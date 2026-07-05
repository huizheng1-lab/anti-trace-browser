"""End-to-end: the agent must play a multi-turn game — clicking the SAME
'Roll Dice' button turn after turn (the board state changes each time even
though the button doesn't) — without the oscillation guard mistaking that
for being stuck, and without hitting the old 8-step cap. It should keep
going until the page itself announces Game Over.

This directly reproduces the user's real complaint: 'told it to play a game,
it only did one step.' The synthetic game is deterministic so we can assert
exact pass/fail instead of depending on a real multiplayer app's timing.
"""
import io, json, os, sys, tempfile, shutil, threading, time
from http.server import BaseHTTPRequestHandler, HTTPServer
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

SESSION_DIR = tempfile.mkdtemp(prefix="atb_game_")
os.environ["WEBVIEW2_USER_DATA_FOLDER"] = SESSION_DIR
os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = "--autoplay-policy=no-user-gesture-required"

PAGE = """<!doctype html><html><head><title>Dice Quest</title></head>
<body style="font-family:sans-serif;padding:24px">
<h2 id="status">Turn 1 of 5 — roll to move!</h2>
<p id="score">Score: 0</p>
<button id="roll" onclick="roll()">Roll Dice</button>
<script>
  window.__turn = 1;
  window.__score = 0;
  var MAX_TURNS = 5;
  function roll(){
    if (window.__turn > MAX_TURNS) return;
    var d = 1 + Math.floor(Math.random()*6);
    window.__score += d;
    document.getElementById('score').innerText = 'Score: ' + window.__score + ' (rolled ' + d + ')';
    window.__turn++;
    if (window.__turn > MAX_TURNS) {
      document.getElementById('status').innerText = 'GAME OVER — final score ' + window.__score;
      document.getElementById('roll').disabled = true;
      document.getElementById('roll').innerText = 'Game Over';
      window.__gameOver = true;
    } else {
      document.getElementById('status').innerText = 'Turn ' + window.__turn + ' of ' + MAX_TURNS + ' — roll to move!';
    }
  }
</script>
</body></html>"""

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(PAGE.encode())

srv = HTTPServer(("127.0.0.1", 0), H)
PORT = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{PORT}/"

import wx
from main import Browser, _load_minimax_key, AgentPanel

if not _load_minimax_key():
    print("NO MINIMAX KEY"); sys.exit(2)

RESULTS = {}

def main():
    app = wx.App(False)
    frame = Browser(); frame.Show()
    frame.set_autoskip(False)
    frame._toggle_assistant()
    panel = frame._assistant_panel
    frame.get_active_webview().LoadURL(URL)

    # Sanity: confirm the classifier + step cap before even running the LLM.
    goal = "play a game — keep rolling the dice until the game ends"
    print(f"_is_ongoing_goal({goal!r}) = {AgentPanel._is_ongoing_goal(goal)}")
    assert AgentPanel._is_ongoing_goal(goal), "classifier should flag this as ongoing"

    def fire():
        print(f"=== goal: {goal}\n=== server: {URL}")
        panel.input.SetValue(goal); panel._send()
        # Poll every 3s for up to ~90s, tracking turn progress.
        poll(0)

    max_polls = 30
    def poll(n):
        wv = frame.get_active_webview()
        try:
            ok, raw = wv.RunScript("JSON.stringify({turn:window.__turn, score:window.__score, over:!!window.__gameOver})")
            st = json.loads(raw)
        except Exception as e:
            st = {"error": str(e)}
        print(f"  [poll {n}] game state: {st}  (agent busy={panel._busy})")
        if st.get("over") or n >= max_polls:
            finish(st)
            return
        wx.CallLater(3000, lambda: poll(n + 1))

    def finish(final_state):
        turn = final_state.get("turn", 1)
        over = bool(final_state.get("over"))
        print(f"\nfinal turn reached: {turn}  game_over: {over}")
        # The bug reproduced: stops after turn 1 (turn stays 1 or 2). The fix:
        # progresses through multiple turns and reaches game over.
        RESULTS["progressed_past_one_turn"] = turn > 2
        RESULTS["reached_game_over"] = over
        tail = panel.transcript.GetValue().strip().splitlines()[-16:]
        print("--- transcript tail ---")
        for ln in tail:
            print("  ", ln)
        print("\n=== RESULTS ===")
        for k, v in RESULTS.items():
            print(f"  {k}: {'PASS' if v else 'FAIL'}")
        panel.cancel_loop()
        frame.Close()

    wx.CallLater(1500, fire)
    wx.CallLater(120000, frame.Close)
    app.MainLoop()
    srv.shutdown()
    shutil.rmtree(SESSION_DIR, ignore_errors=True)
    ok = RESULTS.get("progressed_past_one_turn") and RESULTS.get("reached_game_over")
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    main()
