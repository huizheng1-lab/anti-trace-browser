import io, json, os, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from main import _load_minimax_key, MinimaxClient, AgentPanel, RuleAgent

key = _load_minimax_key()
if not key:
    print("NO KEY"); sys.exit(2)

client = MinimaxClient(key,
    region=os.environ.get("MINIMAX_REGION", "global"),
    model=os.environ.get("MINIMAX_MODEL", "MiniMax-M2"))

PROMPT = "search randomly in google for 10 times"

# 1) What does the local rule parser do first (this runs before MiniMax)?
action, matched = RuleAgent.parse(PROMPT, prefer_llm=True)
print(f"RuleAgent.parse(prefer_llm=True) -> matched={matched} action={action}")
print(f"_wants_interaction -> {AgentPanel._wants_interaction(PROMPT)}")
print()

# 2) What would the single-shot MiniMax path actually return?
tabs_block = "[tabs (active: 0):\n  0: 'New Tab' @ about:blank\n]"
messages = [
    {"role": "system", "content": AgentPanel.SYSTEM_PROMPT},
    {"role": "user", "content": f"{tabs_block}\nUser: {PROMPT}"},
]
raw = client.chat(messages, timeout=60)
print("RAW MINIMAX OUTPUT:")
print(raw)
print()
acts = AgentPanel._parse_actions(raw)
print(f"Parsed {len(acts)} action(s):")
for a in acts:
    print(" ", a)
