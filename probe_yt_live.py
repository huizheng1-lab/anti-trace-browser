"""Drive an actual YouTube video, watch the DOM for ad markers, then dump
diagnostic info about every Skip-like element so we can fix selectors precisely
if real YouTube uses a class we don't know about."""
import io, json, os, sys, tempfile, shutil, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

SESSION_DIR = tempfile.mkdtemp(prefix="atb_yt_")
os.environ["WEBVIEW2_USER_DATA_FOLDER"] = SESSION_DIR
os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = "--autoplay-policy=no-user-gesture-required"

import wx
from main import Browser, RuleAgent

# Pick a video likely to have a pre-roll ad. Iran video the user had open.
URL = "https://www.youtube.com/watch?v=WauW6cGcjzU"

DIAGNOSE_JS = r"""
(function(){
  function isVisible(el){
    if (!el) return false;
    var r = el.getBoundingClientRect();
    if (r.width <= 1 || r.height <= 1) return false;
    var cs = window.getComputedStyle(el);
    return cs.display !== 'none' && cs.visibility !== 'hidden' && parseFloat(cs.opacity||'1') > 0.05;
  }
  function describeHidden(el){
    if (!el) return null;
    var r = el.getBoundingClientRect();
    var cs = window.getComputedStyle(el);
    // Walk up to find which ancestor is killing visibility.
    var killer = null;
    var p = el;
    while (p && p !== document.body) {
      var pcs = window.getComputedStyle(p);
      if (pcs.display === 'none') { killer = 'display:none@' + (p.tagName + (p.id ? '#'+p.id : '')); break; }
      if (pcs.visibility === 'hidden') { killer = 'visibility:hidden@' + (p.tagName + (p.id ? '#'+p.id : '')); break; }
      if (parseFloat(pcs.opacity||'1') < 0.05) { killer = 'opacity:0@' + (p.tagName + (p.id ? '#'+p.id : '')); break; }
      p = p.parentElement;
    }
    return {
      rect: {w: r.width, h: r.height, t: r.top, l: r.left},
      display: cs.display, visibility: cs.visibility, opacity: cs.opacity,
      pointerEvents: cs.pointerEvents, killer: killer,
    };
  }
  function path(el){
    var p = [];
    while (el && el.nodeType === 1 && p.length < 8) {
      var s = el.tagName.toLowerCase();
      if (el.id) s += '#' + el.id;
      if (el.className && typeof el.className === 'string') {
        s += '.' + el.className.split(/\s+/).filter(Boolean).slice(0, 4).join('.');
      }
      p.unshift(s);
      el = el.parentElement;
    }
    return p.join(' > ');
  }
  var hits = [];
  // 1) Known selectors
  var selectors = [
    '.ytp-ad-skip-button-modern', '.ytp-skip-ad-button', '.ytp-ad-skip-button',
    '.ytp-ad-skip-button-container button', '.videoAdUiSkipButton',
    '#skip-button button', "[id*='skip-button'] button",
    "button[class*='skip-ad-button']", "button[class*='ytp-ad-skip']",
  ];
  selectors.forEach(function(sel){
    try {
      document.querySelectorAll(sel).forEach(function(el){
        hits.push({how: 'sel', sel: sel, vis: isVisible(el),
                   text: (el.innerText || el.getAttribute('aria-label') || '').slice(0,60),
                   path: path(el)});
      });
    } catch(_) {}
  });
  // 2) Any button with "skip" in text or aria-label
  document.querySelectorAll('button, [role="button"]').forEach(function(el){
    var t = ((el.innerText || '') + ' ' + (el.getAttribute('aria-label') || '')).toLowerCase();
    if (/\bskip\b/.test(t)) {
      hits.push({how: 'text', vis: isVisible(el),
                 text: (el.innerText || el.getAttribute('aria-label') || '').slice(0,60),
                 path: path(el)});
    }
  });
  // 3) Ad indicators
  var adMarkers = {
    'ad-showing': !!document.querySelector('.ad-showing'),
    'html5-video-player.ad-showing': !!document.querySelector('.html5-video-player.ad-showing'),
    'ytp-ad-player-overlay': !!document.querySelector('.ytp-ad-player-overlay'),
    'ytp-ad-preview-text': document.querySelector('.ytp-ad-preview-text') ? document.querySelector('.ytp-ad-preview-text').innerText : null,
  };
  return JSON.stringify({adMarkers: adMarkers, hits: hits.slice(0, 30)}, null, 2);
})();
"""


def main():
    app = wx.App(False)
    frame = Browser(); frame.Show()
    wv = frame.get_active_webview(); wv.LoadURL(URL)
    t0 = time.time()
    print(f"[t=0] loading {URL}")

    def poll(rounds):
        wv2 = frame.get_active_webview()
        ok, raw = wv2.RunScript(DIAGNOSE_JS)
        ts = int(time.time() - t0)
        try:
            obj = json.loads(raw)
        except Exception:
            print(f"[t={ts}s] parse err — raw len={len(raw or '')}")
            obj = None
        if obj:
            ads = obj.get("adMarkers", {})
            hits = obj.get("hits", [])
            print(f"\n[t={ts}s] adMarkers: {ads}")
            interesting = [h for h in hits if h.get("how") == "sel" or "skip nav" not in (h.get("text") or "").lower()]
            print(f"[t={ts}s] {len(interesting)} skip-like elements (interesting):")
            for h in interesting[:6]:
                vis = "VIS" if h.get("vis") else "HID"
                line = f"  {vis} how={h.get('how')} text={h.get('text')!r}"
                if h.get("sel"): line += f" sel={h.get('sel')!r}"
                print(line)
                if h.get("why_hidden"):
                    wh = h["why_hidden"]
                    print(f"      hidden by: {wh.get('killer')}  display={wh.get('display')} visibility={wh.get('visibility')} opacity={wh.get('opacity')} rect={wh.get('rect')}")

            # Fire the rule immediately on ad detection — it polls internally
            # using OS-level click for trusted events.
            if ads.get("ad-showing") and not state.fired:
                print(f"\n[t={ts}s] >>> firing 'skip ad' rule (trusted OS click)")
                act, _ = RuleAgent.parse("skip ad", prefer_llm=False)
                desc = frame._execute_agent_action(act)
                print(f"     dispatch: {desc}")
                state.fired = True
                wx.CallLater(25000, re_check)  # wait for visible + click to land
                return
        if rounds < 20:
            wx.CallLater(2500, lambda: poll(rounds + 1))
        else:
            print(f"\n[t={ts}s] giving up — no visible skip button materialised in {ts}s")
            frame.Close()

    class state: fired = False
    def re_check(_rounds=None):
        wv2 = frame.get_active_webview()
        ok, raw = wv2.RunScript(DIAGNOSE_JS)
        try:
            obj = json.loads(raw)
            ads = obj.get("adMarkers", {})
            still_ad = ads.get("ad-showing") or ads.get("html5-video-player.ad-showing")
            print(f"\n[t={int(time.time()-t0)}s] post-click adMarkers: {ads}")
            print(f"  still in ad? {still_ad}")
        except Exception as e:
            print(f"re-check err {e}")
        frame.Close()

    wx.CallLater(5000, lambda: poll(0))   # start polling after initial load
    wx.CallLater(60000, frame.Close)      # hard 60s ceiling
    app.MainLoop()
    shutil.rmtree(SESSION_DIR, ignore_errors=True)


if __name__ == "__main__":
    main()
