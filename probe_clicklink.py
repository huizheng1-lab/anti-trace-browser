import io, os, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from main import _load_minimax_key, MinimaxClient, AgentPanel

c = MinimaxClient(_load_minimax_key(),
    region=os.environ.get("MINIMAX_REGION","global"),
    model=os.environ.get("MINIMAX_MODEL","MiniMax-M2"))

# Pretend the user is on a Yahoo search results page for "deep sea creatures"
CTX = """[tabs (active: 1):
  0: 'DuckDuckGo' @ https://duckduckgo.com/
  1: 'deep sea creatures - Yahoo Search' @ https://search.yahoo.com/search?p=deep+sea+creatures
]
[links on active page — pick one of these URLs and use navigate:
  0: 'Sponsored: shop deep sea decor' -> https://ads.example.com/decor
  1: 'Deep-sea creature - Wikipedia' -> https://en.wikipedia.org/wiki/Deep-sea_creature
  2: '15 Bizarre Deep Sea Creatures | National Geographic' -> https://www.nationalgeographic.com/animals/article/deep-sea-creatures
  3: 'Deep Sea Creatures | Smithsonian Ocean' -> https://ocean.si.edu/ocean-life/fish/deep-sea-creatures
  4: 'Top 10 Weirdest Deep Sea Animals' -> https://www.livescience.com/deep-sea-weird
]
"""

CASES = [
    "click the first result",
    "click the wikipedia link",
    "open the smithsonian one",
    "open the second and third results in new tabs",
]
for p in CASES:
    msgs = [
        {"role":"system","content":AgentPanel.SYSTEM_PROMPT},
        {"role":"user","content": CTX + "User: " + p},
    ]
    try:
        raw = c.chat(msgs, timeout=30)
    except Exception as e:
        print(f"\n{p!r} ERROR: {e}"); continue
    acts = AgentPanel._parse_actions(raw)
    print(f"\nPROMPT: {p}")
    print(f"  raw   : {raw[:280]!r}")
    for a in acts:
        print(f"    - {a}")
