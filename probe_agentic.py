"""End-to-end test of the Gemini-style observe->act loop driven by real MiniMax.

Two scenarios:
  A) Multi-field form: fill name + email, pick a dropdown, tick a checkbox, submit.
  B) Row-aware list: select only the promotional rows' checkboxes, click Trash.

We drive the actual AgentPanel loop (observe_page -> MiniMax -> index actions)
and assert the final DOM state matches the goal.
"""
import base64, io, json, os, sys, tempfile, shutil, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

SESSION_DIR = tempfile.mkdtemp(prefix="atb_agentic_")
os.environ["WEBVIEW2_USER_DATA_FOLDER"] = SESSION_DIR
os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = "--autoplay-policy=no-user-gesture-required"

import wx
from main import Browser, _load_minimax_key

if not _load_minimax_key():
    print("NO MINIMAX KEY — cannot run agentic test"); sys.exit(2)

FORM_HTML = """
<!doctype html><html><body style="font-family:sans-serif;padding:24px;max-width:520px">
<h2>Create account</h2>
<form id="f" onsubmit="window._submitted=true;document.getElementById('done').innerText='SUBMITTED';return false;">
  <p>Name: <input id="name" name="name" type="text"></p>
  <p>Email: <input id="email" name="email" type="email"></p>
  <p>Favorite color:
    <select id="color" name="color">
      <option>Choose…</option><option>Red</option><option>Green</option><option>Blue</option>
    </select></p>
  <p><input id="agree" name="agree" type="checkbox"> I agree to the terms</p>
  <button type="submit">Create account</button>
</form>
<p id="done"></p>
</body></html>
"""

LIST_HTML = """
<!doctype html><html><body style="font-family:sans-serif;padding:16px">
<h2>Inbox</h2>
<button id="trash" onclick="doTrash()">Move to Trash</button>
<div id="list"></div>
<p id="status"></p>
<script>
 var rows = [
   {from:'Mom', subj:'Dinner Sunday?'},
   {from:'SuperDeals', subj:'50% OFF everything — promo ends tonight!'},
   {from:'Bank', subj:'Your statement is ready'},
   {from:'NewsletterDaily', subj:'This week in marketing — special offer inside'},
   {from:'Boss', subj:'Q3 report review'},
   {from:'ShopMart Promotions', subj:'Exclusive coupon just for you'},
 ];
 var list = document.getElementById('list');
 rows.forEach(function(r,i){
   var d=document.createElement('div'); d.className='row'; d.style.cssText='padding:6px;border-bottom:1px solid #ddd';
   d.innerHTML = '<input type="checkbox" class="sel" data-i="'+i+'"> <b>'+r.from+'</b> — '+r.subj;
   list.appendChild(d);
 });
 window._trashed = [];
 function doTrash(){
   var checked = Array.prototype.filter.call(document.querySelectorAll('.sel'), function(c){return c.checked;});
   window._trashed = checked.map(function(c){return parseInt(c.getAttribute('data-i'));});
   checked.forEach(function(c){ c.closest('.row').remove(); });
   document.getElementById('status').innerText = 'TRASHED:' + JSON.stringify(window._trashed);
 }
</script>
</body></html>
"""

def url(html): return "data:text/html;base64," + base64.b64encode(html.encode()).decode()

RESULTS = {}

def main():
    app = wx.App(False)
    frame = Browser(); frame.Show()
    frame.set_autoskip(False)  # keep the OS cursor still during this test
    # Open the agent panel so the loop has a transcript to log into.
    frame._toggle_assistant()
    panel = frame._assistant_panel

    wv = frame.get_active_webview()

    def run_scenario_A():
        wv.LoadURL(url(FORM_HTML))
        wx.CallLater(1500, fire_A)

    def fire_A():
        goal = ("fill the form — name Bob Lee, email bob.lee@example.com, "
                "favorite color Green, agree to the terms, then click Create account")
        print(f"\n=== Scenario A: {goal}")
        panel.input.SetValue(goal); panel._send()
        wx.CallLater(45000, check_A)  # generous: several observe->LLM->act rounds

    def check_A():
        ok, raw = frame.get_active_webview().RunScript(
            "JSON.stringify({name:document.getElementById('name').value,"
            "email:document.getElementById('email').value,"
            "color:document.getElementById('color').value,"
            "agree:document.getElementById('agree').checked,"
            "submitted:!!window._submitted})")
        st = json.loads(raw)
        print("  final form state:", st)
        passed = (st["name"]=="Bob Lee" and "bob.lee@example.com" in st["email"]
                  and st["color"]=="Green" and st["agree"] and st["submitted"])
        RESULTS["A"] = passed
        print(f"  Scenario A: {'PASS' if passed else 'FAIL'}")
        # move to B
        panel.cancel_loop()
        run_scenario_B()

    def run_scenario_B():
        wv2 = frame.get_active_webview()
        wv2.LoadURL(url(LIST_HTML))
        wx.CallLater(1500, fire_B)

    def fire_B():
        goal = "select the promotional/marketing emails and move them to trash"
        print(f"\n=== Scenario B: {goal}")
        panel.input.SetValue(goal); panel._send()
        wx.CallLater(55000, check_B)

    def check_B():
        ok, raw = frame.get_active_webview().RunScript(
            "JSON.stringify({trashed:(window._trashed||[]), remaining:document.querySelectorAll('.row').length})")
        st = json.loads(raw)
        print("  trashed indices:", st["trashed"], "| rows remaining:", st["remaining"])
        # Promo rows are indices 1,3,5. Pass if those got trashed and the
        # non-promos (0,2,4 = Mom/Bank/Boss) did NOT.
        trashed = set(st["trashed"])
        promos = {1,3,5}
        passed = trashed == promos
        RESULTS["B"] = passed
        print(f"  Scenario B: {'PASS' if passed else 'FAIL'} (expected promos {promos})")
        finish()

    def finish():
        print("\n=== RESULTS ===")
        for k in ("A","B"):
            print(f"  Scenario {k}: {'PASS' if RESULTS.get(k) else 'FAIL'}")
        frame.Close()

    wx.CallLater(800, run_scenario_A)
    wx.CallLater(130000, frame.Close)  # hard ceiling
    app.MainLoop()
    shutil.rmtree(SESSION_DIR, ignore_errors=True)
    sys.exit(0 if (RESULTS.get("A") and RESULTS.get("B")) else 1)

if __name__ == "__main__":
    main()
