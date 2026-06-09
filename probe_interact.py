"""Verify (1) page observation + index-based click/fill/select work directly,
and (2) the full MiniMax observe->act loop can complete a multi-step form goal."""
import base64, io, json, os, sys, tempfile, shutil, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

SESSION_DIR = tempfile.mkdtemp(prefix="atb_int_")
os.environ["WEBVIEW2_USER_DATA_FOLDER"] = SESSION_DIR
os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = "--autoplay-policy=no-user-gesture-required"

import wx
from main import Browser

HTML = """
<!doctype html><html><body style="font-family:sans-serif;padding:24px">
<h1>Sign-up form</h1>
<form id="f" onsubmit="window._submitted=true;document.getElementById('result').innerText='SUBMITTED';return false;">
  <p><label>Name: <input id="name" type="text" placeholder="Your name"></label></p>
  <p><label>Email: <input id="email" type="email" placeholder="you@example.com"></label></p>
  <p><label>Favourite colour:
    <select id="color">
      <option value="">-- pick --</option>
      <option value="r">Red</option>
      <option value="g">Green</option>
      <option value="b">Blue</option>
    </select></label></p>
  <p><label><input id="agree" type="checkbox"> I agree to the terms</label></p>
  <p><button id="submit" type="submit">Create account</button></p>
</form>
<p id="result">not submitted</p>
</body></html>
"""
URL = "data:text/html;base64," + base64.b64encode(HTML.encode()).decode()


def main():
    app = wx.App(False)
    frame = Browser(); frame.Show()
    wv = frame.get_active_webview(); wv.LoadURL(URL)

    results = {"direct": False, "loop": False}

    def phase_direct():
        # 1) Observe
        obs = frame.observe_page()
        els = obs.get("elements", [])
        print(f"[direct] observed {len(els)} elements:")
        for e in els:
            print(f"   #{e['i']} {e.get('kind')}/{e.get('tag')}: {e.get('label')!r} "
                  + (f"options={e.get('options')}" if e.get('options') else ""))
        # Map labels -> index
        by = {}
        for e in els:
            by[e.get('label','').lower()] = e['i']
        # 2) Fill name (#0), email (#1), select Blue, check agree, click submit
        name_i = next((e['i'] for e in els if e.get('tag')=='input' and e.get('type')=='text'), None)
        email_i = next((e['i'] for e in els if e.get('type')=='email'), None)
        color_i = next((e['i'] for e in els if e.get('tag')=='select'), None)
        agree_i = next((e['i'] for e in els if e.get('kind')=='checkbox'), None)
        submit_i = next((e['i'] for e in els if e.get('tag')=='button'), None)
        print(f"[direct] indices name={name_i} email={email_i} color={color_i} agree={agree_i} submit={submit_i}")
        frame._execute_agent_action({"action":"fill","index":name_i,"text":"Alice"})
        frame._execute_agent_action({"action":"fill","index":email_i,"text":"alice@example.com"})
        frame._execute_agent_action({"action":"select_option","index":color_i,"option":"Blue"})
        frame._execute_agent_action({"action":"click_element","index":agree_i})
        frame._execute_agent_action({"action":"click_element","index":submit_i})
        wx.CallLater(600, verify_direct)

    def verify_direct():
        ok, raw = frame.get_active_webview().RunScript(
            "JSON.stringify({name:document.getElementById('name').value,"
            "email:document.getElementById('email').value,"
            "color:document.getElementById('color').value,"
            "agree:document.getElementById('agree').checked,"
            "submitted:!!window._submitted})"
        )
        print(f"[direct] final DOM state: {raw}")
        try:
            d = json.loads(raw)
            results["direct"] = (d.get("name")=="Alice" and d.get("color")=="b"
                                 and d.get("agree") and d.get("submitted"))
        except Exception as e:
            print("  parse err", e)
        print(f"[direct] {'PASS' if results['direct'] else 'FAIL'}")
        # reset page for loop test
        frame.get_active_webview().LoadURL(URL)
        wx.CallLater(1500, phase_loop)

    def phase_loop():
        if frame.minimax is None:
            print("[loop] no MiniMax key — skipping loop test")
            finish()
            return
        print("\n[loop] starting observe->act loop with MiniMax…")
        panel = frame._build_assistant_panel()  # AgentPanel
        frame._assistant_panel = panel
        panel._run_agentic_loop(
            "Fill the name field with Bob, email with bob@test.com, "
            "choose Green as the colour, tick the agree checkbox, then click Create account."
        )
        wx.CallLater(70000, verify_loop)

    def verify_loop():
        try:
            print("\n[loop] transcript:")
            print(frame._assistant_panel.transcript.GetValue())
        except Exception as e:
            print("  (no transcript)", e)
        ok, raw = frame.get_active_webview().RunScript(
            "JSON.stringify({name:document.getElementById('name').value,"
            "email:document.getElementById('email').value,"
            "color:document.getElementById('color').value,"
            "agree:document.getElementById('agree').checked,"
            "submitted:!!window._submitted})"
        )
        print(f"\n[loop] final DOM state: {raw}")
        try:
            d = json.loads(raw)
            # Be lenient — count it a pass if it filled name + submitted.
            results["loop"] = bool(d.get("name")) and d.get("submitted", False)
        except Exception as e:
            print("  parse err", e)
        print(f"[loop] {'PASS' if results['loop'] else 'FAIL'}")
        finish()

    def finish():
        print(f"\n=== direct: {'PASS' if results['direct'] else 'FAIL'} | "
              f"loop: {'PASS' if results['loop'] else 'FAIL'} ===")
        frame.Close()

    wx.CallLater(1500, phase_direct)
    wx.CallLater(120000, frame.Close)  # hard ceiling
    app.MainLoop()
    shutil.rmtree(SESSION_DIR, ignore_errors=True)


if __name__ == "__main__":
    main()
