import io, os, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from main import _load_minimax_key, MinimaxClient, AgentPanel

c = MinimaxClient(_load_minimax_key(),
    region=os.environ.get("MINIMAX_REGION","global"),
    model=os.environ.get("MINIMAX_MODEL","MiniMax-M2"))

CASES = [
    "do 3 random searches in bing",
    "open youtube and wikipedia",
    "open 4 cat photo sites",
    "do 2 random searches",
]
for p in CASES:
    msgs = [
        {"role":"system","content":AgentPanel.SYSTEM_PROMPT},
        {"role":"user","content":"[active tab: title='blank' url=about:blank]\nUser: "+p},
    ]
    try:
        raw = c.chat(msgs, timeout=30)
    except Exception as e:
        print(f"\n{p!r} ERROR: {e}"); continue
    acts = AgentPanel._parse_actions(raw)
    print(f"\nPROMPT: {p}")
    print(f"  raw   : {raw[:300]!r}")
    print(f"  parsed: {len(acts)} action(s)")
    for a in acts:
        print(f"    - {a}")
