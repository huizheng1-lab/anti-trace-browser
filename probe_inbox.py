"""Synthetic webmail inbox: verify the agent can select ONLY the promotional
rows by their row context and move them to Trash (recoverable)."""
import base64, io, json, os, sys, tempfile, shutil
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

SESSION_DIR = tempfile.mkdtemp(prefix="atb_inbox_")
os.environ["WEBVIEW2_USER_DATA_FOLDER"] = SESSION_DIR
os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = "--autoplay-policy=no-user-gesture-required"

import wx
from main import Browser

# 6 emails: 3 clearly promotional, 3 personal/work. Each row has a checkbox.
ROWS = [
    ("0", "Mom", "Call me when you land", False),
    ("1", "MEGA SALE", "50% OFF everything this weekend only!", True),
    ("2", "GitHub", "[PR] Fix null check in parser", False),
    ("3", "Nike Store", "Your exclusive promo code inside", True),
    ("4", "Dr. Lee's office", "Appointment reminder for Tuesday", False),
    ("5", "Newsletter Weekly", "Unsubscribe? New deals & coupons await", True),
]
rows_html = ""
for rid, sender, subj, promo in ROWS:
    rows_html += (
        f'<tr id="row{rid}"><td><input type="checkbox" id="cb{rid}" '
        f'aria-label="select email from {sender}"></td>'
        f'<td><b>{sender}</b></td><td>{subj}</td></tr>'
    )

HTML = f"""
<!doctype html><html><body style="font-family:sans-serif;padding:16px">
<h2>Inbox</h2>
<button id="trash" onclick="
  var moved=[];
  document.querySelectorAll('tbody input[type=checkbox]').forEach(function(cb){{
    if(cb.checked){{ var tr=cb.closest('tr'); moved.push(tr.id); tr.style.display='none'; cb.checked=false; }}
  }});
  window._trashed=(window._trashed||[]).concat(moved);
  document.getElementById('status').innerText='Moved to Trash: '+(window._trashed.join(', ')||'none');
">Move to Trash</button>
<p id="status">nothing trashed</p>
<table border=1 cellpadding=6><tbody>
{rows_html}
</tbody></table>
</body></html>
"""
URL = "data:text/html;base64," + base64.b64encode(HTML.encode()).decode()

# Expected: rows 1,3,5 are promos.
EXPECTED = {"row1", "row3", "row5"}


def main():
    app = wx.App(False)
    frame = Browser(); frame.Show()
    wv = frame.get_active_webview(); wv.LoadURL(URL)

    state = {"ok": False}

    def show_observation():
        obs = frame.observe_page()
        print("[observe] elements with row context:")
        for e in obs.get("elements", []):
            print(f"  #{e['i']} {e.get('kind')}/{e.get('tag')} label={e.get('label')!r} "
                  f"ctx={e.get('context')!r}")
        start_loop()

    def start_loop():
        if frame.minimax is None:
            print("[loop] no MiniMax key — skipping"); finish(); return
        print("\n[loop] goal: move all promotional emails to trash")
        panel = frame._build_assistant_panel()
        frame._assistant_panel = panel
        panel._run_agentic_loop(
            "Select all the promotional / marketing / newsletter emails "
            "(sales, coupons, discount codes, unsubscribe spam) and move them to "
            "Trash. Leave personal and work emails untouched."
        )
        wx.CallLater(75000, verify)

    def verify():
        try:
            print("\n[loop] transcript:")
            print(frame._assistant_panel.transcript.GetValue())
        except Exception:
            pass
        ok, raw = frame.get_active_webview().RunScript("JSON.stringify(window._trashed||[])")
        print(f"\n[result] trashed rows: {raw}")
        try:
            trashed = set(json.loads(raw))
            state["ok"] = (trashed == EXPECTED)
            if not state["ok"]:
                print(f"  expected {sorted(EXPECTED)}, got {sorted(trashed)}")
        except Exception as e:
            print("  parse err", e)
        print(f"[result] {'PASS' if state['ok'] else 'FAIL'}")
        finish()

    def finish():
        frame.Close()

    wx.CallLater(1500, show_observation)
    wx.CallLater(120000, frame.Close)
    app.MainLoop()
    shutil.rmtree(SESSION_DIR, ignore_errors=True)
    sys.exit(0 if state["ok"] else 1)


if __name__ == "__main__":
    main()
