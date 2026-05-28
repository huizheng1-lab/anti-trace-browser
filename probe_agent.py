"""Smoke test: ask the agent to act, verify JSON action + dispatch logic."""
import io
import json
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from main import DuckAIClient, AgentPanel

PROMPTS = [
    "open YouTube",
    "search for python pyqt6 tutorial",
    "new tab to en.wikipedia.org",
    "bookmark this",
]

def main():
    c = DuckAIClient()
    c.messages = [
        {"role": "user", "content": AgentPanel.SYSTEM_PROMPT},
        {"role": "assistant", "content": "Ready."},
    ]
    ok = 0
    for p in PROMPTS:
        ctx = "[active tab: title='YouTube' url=https://www.youtube.com/]\nUser: " + p
        try:
            reply = c.chat(ctx)
        except Exception as e:
            print(f"[{p!r}]  ERROR: {e}")
            continue
        action = AgentPanel._parse_action(reply)
        print(f"[{p!r}]")
        print(f"  raw:    {reply[:140]!r}")
        print(f"  parsed: {action}")
        if action and action.get("action") in {"navigate","new_tab","search","close_tab","bookmark","reply"}:
            ok += 1
        print()
    print(f"--- {ok}/{len(PROMPTS)} produced valid actions ---")
    sys.exit(0 if ok == len(PROMPTS) else 1)

if __name__ == "__main__":
    main()
