"""Verify the agent handles the prompts from the user's screenshot."""
import io, json, os, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from main import _load_minimax_key, MinimaxClient, AgentPanel, RuleAgent

key = _load_minimax_key()
if not key:
    print("no key"); sys.exit(2)

client = MinimaxClient(key,
    region=os.environ.get("MINIMAX_REGION", "global"),
    model=os.environ.get("MINIMAX_MODEL", "MiniMax-M2"))

CASES = [
    "do a random keyword search",
    "do a random keyword search again",
    "open a link in this page",
    "do a random search in bing",
    "open the msft rewards dashboard",   # should match rules — no API
    "search a random word",
    "summarize this page",
    "take me somewhere interesting",
]

ok = 0
for prompt in CASES:
    rule_action, matched = RuleAgent.parse(prompt, prefer_llm=True)
    print(f"\nPROMPT: {prompt}")
    if matched:
        print(f"  RULES (no API): {rule_action}")
        ok += 1
        continue
    msgs = [
        {"role": "system", "content": AgentPanel.SYSTEM_PROMPT},
        {"role": "user",   "content": "[active tab: title='Random Word Generator' url=https://duckduckgo.com/?q=a+random+word]\nUser: " + prompt},
    ]
    try:
        reply = client.chat(msgs, timeout=30)
    except Exception as e:
        print(f"  MINIMAX ERROR: {e}"); continue
    action = AgentPanel._parse_action(reply)
    print(f"  MINIMAX raw   : {reply[:200]!r}")
    print(f"  MINIMAX parsed: {action}")
    if action and action.get("action") in {"navigate","new_tab","search","close_tab","bookmark","reply","home","back","forward","wipe"}:
        ok += 1

print(f"\n--- {ok}/{len(CASES)} produced a valid action ---")
sys.exit(0 if ok == len(CASES) else 1)
