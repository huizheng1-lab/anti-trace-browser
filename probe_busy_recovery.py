"""Verify the busy-gate hardening:
1) An exception inside action execution during the agentic loop must NOT
   leave _busy stuck true forever (this was the actual bug: the assistant
   would silently stop responding to every future message).
2) While genuinely busy, _send() must give visible feedback instead of
   silently no-oping.
3) If _busy is somehow stuck past the watchdog threshold, the next _send()
   must self-heal and process the message instead of dropping it forever.
"""
import io, sys, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import os, tempfile, shutil
SESSION_DIR = tempfile.mkdtemp(prefix="atb_busy_")
os.environ["WEBVIEW2_USER_DATA_FOLDER"] = SESSION_DIR
os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = "--autoplay-policy=no-user-gesture-required"

import wx
from main import Browser

RESULTS = {}

def main():
    app = wx.App(False)
    frame = Browser(); frame.Show()
    frame.set_autoskip(False)
    frame._toggle_assistant()
    panel = frame._assistant_panel

    def transcript_tail(n=6):
        return panel.transcript.GetValue().strip().splitlines()[-n:]

    # ---- Test 1: exception inside _agent_after_llm's action loop must not
    # leave _busy stuck. Simulate exactly what happens when the LLM/JS layer
    # throws mid-action.
    def test1():
        print("=== Test 1: exception during action dispatch must clear _busy ===")
        panel._busy = True
        panel._busy_since = time.time()
        panel._loop_cancel = False
        panel._loop_last_sig = None
        # Simulate what _agent_after_llm does when _execute_agent_action raises.
        raw = '{"action":"click_element","index":9999}'  # index that doesn't exist -> should be handled gracefully anyway
        # Force an actual crash by monkeypatching _execute_agent_action temporarily.
        orig = frame._execute_agent_action
        def boom(action):
            raise RuntimeError("simulated JS/action failure")
        frame._execute_agent_action = boom
        try:
            panel._agent_after_llm(raw)
        finally:
            frame._execute_agent_action = orig
        print(f"  _busy after simulated exception: {panel._busy} (expect False)")
        print(f"  transcript tail: {transcript_tail(2)}")
        RESULTS["test1_busy_cleared"] = (panel._busy == False)
        wx.CallLater(300, test2)

    # ---- Test 2: while genuinely busy, _send() must give feedback, not silently no-op.
    def test2():
        print("\n=== Test 2: _send() while genuinely busy gives visible feedback ===")
        panel._busy = True
        panel._busy_since = time.time()  # fresh -> NOT stale
        before = len(panel.transcript.GetValue())
        panel.input.SetValue("are you still there")
        panel._send()
        after = len(panel.transcript.GetValue())
        got_feedback = after > before and "still working" in panel.transcript.GetValue()[-300:]
        print(f"  transcript grew: {after > before}, mentions 'still working': {got_feedback}")
        print(f"  tail: {transcript_tail(2)}")
        RESULTS["test2_feedback_shown"] = got_feedback
        panel._busy = False
        wx.CallLater(300, test3)

    # ---- Test 3: stuck (stale) busy must self-heal on next _send().
    def test3():
        print("\n=== Test 3: stale/stuck _busy self-heals on next _send() ===")
        panel._busy = True
        panel._busy_since = time.time() - (panel.BUSY_STUCK_SECONDS + 5)  # force staleness
        panel.input.SetValue("hello are you there")
        panel._send()
        # RuleAgent should match "hello are you there"? probably not a rule -> goes to
        # interaction/minimax path, but regardless _busy handling + recovery message
        # should have printed BEFORE the new message processing.
        tail = transcript_tail(6)
        print(f"  transcript tail after recovery: {tail}")
        recovered = any("recovered from a stuck state" in ln for ln in tail)
        processed_new_msg = any("hello are you there" in ln for ln in tail)
        print(f"  recovery message shown: {recovered}")
        print(f"  new message actually got processed (echoed in transcript): {processed_new_msg}")
        RESULTS["test3_recovered"] = recovered
        RESULTS["test3_processed"] = processed_new_msg
        finish()

    def finish():
        print("\n=== RESULTS ===")
        for k, v in RESULTS.items():
            print(f"  {k}: {'PASS' if v else 'FAIL'}")
        frame.Close()

    wx.CallLater(1000, test1)
    wx.CallLater(15000, frame.Close)
    app.MainLoop()
    shutil.rmtree(SESSION_DIR, ignore_errors=True)
    ok = all(RESULTS.values()) and len(RESULTS) == 4
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    main()
