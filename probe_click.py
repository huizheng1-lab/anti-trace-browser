import io, os, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from main import _load_minimax_key, MinimaxClient, AgentPanel

c = MinimaxClient(_load_minimax_key(),
    region=os.environ.get("MINIMAX_REGION","global"),
    model=os.environ.get("MINIMAX_MODEL","MiniMax-M2"))

YT_CTX = """[tabs (active: 0):
  0: 'Iran leaks peace draft - YouTube' @ https://www.youtube.com/watch?v=WauW6cGcjzU
]"""

COOKIE_CTX = """[tabs (active: 0):
  0: 'Example News' @ https://news.example.com/article/123
]"""

CASES = [
    (YT_CTX, "skip the ad"),
    (YT_CTX, "skip this ad"),
    (YT_CTX, "click play"),
    (COOKIE_CTX, "dismiss the cookie banner"),
    (COOKIE_CTX, "accept the cookies"),
    (COOKIE_CTX, "close this newsletter popup"),
]
for ctx, p in CASES:
    msgs = [
        {"role":"system","content":AgentPanel.SYSTEM_PROMPT},
        {"role":"user","content": ctx + "\nUser: " + p},
    ]
    try:
        raw = c.chat(msgs, timeout=30)
    except Exception as e:
        print(f"\n{p!r} ERROR: {e}"); continue
    acts = AgentPanel._parse_actions(raw)
    print(f"\nPROMPT: {p}")
    print(f"  raw: {raw[:280]!r}")
    for a in acts:
        print(f"    - {a}")
