import io, os, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from main import _load_minimax_key, MinimaxClient, AgentPanel

c = MinimaxClient(_load_minimax_key(),
    region=os.environ.get("MINIMAX_REGION","global"),
    model=os.environ.get("MINIMAX_MODEL","MiniMax-M2"))

CTX = """[tabs (active: 0):
  0: 'Mariana Trench depth - Search' @ https://www.bing.com/search?q=Mariana+Trench+depth
]"""

CASES = [
    "do 30 random searches in bing. recycle the same tab. do not open new ones",
    "do 5 random searches in bing. recycle the same tab",
    "search this page for octopus",
    "do 3 random searches in bing",  # should still use new tabs
]
for p in CASES:
    msgs = [
        {"role":"system","content":AgentPanel.SYSTEM_PROMPT},
        {"role":"user","content": CTX + "\nUser: " + p},
    ]
    try:
        raw = c.chat(msgs, timeout=40)
    except Exception as e:
        print(f"\n{p!r} ERROR: {e}"); continue
    acts = AgentPanel._parse_actions(raw)
    print(f"\nPROMPT: {p}")
    print(f"  {len(acts)} action(s)")
    for a in acts[:6]:
        print(f"    - {a}")
    if len(acts) > 6:
        print(f"    … +{len(acts)-6} more")
