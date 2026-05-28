import io, os, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from main import _load_minimax_key, MinimaxClient, AgentPanel

c = MinimaxClient(_load_minimax_key(),
    region=os.environ.get("MINIMAX_REGION","global"),
    model=os.environ.get("MINIMAX_MODEL","MiniMax-M2"))

TABS_CTX = """[tabs (active: 1):
  0: 'DuckDuckGo - Protection. Privacy. Peace of mind.' @ https://duckduckgo.com/?kp=-2&kak=-1
  1: 'Mariana Trench depth - Search' @ https://www.bing.com/search?q=Mariana+Trench+depth
  2: 'ancient Greek philosophy - Search' @ https://www.bing.com/search?q=ancient+Greek+philosophy
  3: 'Voyager 1 location - Search' @ https://www.bing.com/search?q=Voyager+1+location
]"""

CASES = [
    "clean up the tabs you opened",
    "close the voyager tab",
    "switch to the first tab",
    "close all bing tabs",
]
for p in CASES:
    msgs = [
        {"role":"system","content":AgentPanel.SYSTEM_PROMPT},
        {"role":"user","content": TABS_CTX + "\nUser: " + p},
    ]
    try:
        raw = c.chat(msgs, timeout=30)
    except Exception as e:
        print(f"\n{p!r} ERROR: {e}"); continue
    acts = AgentPanel._parse_actions(raw)
    print(f"\nPROMPT: {p}")
    print(f"  raw   : {raw[:280]!r}")
    print(f"  parsed: {len(acts)} action(s)")
    for a in acts:
        print(f"    - {a}")
