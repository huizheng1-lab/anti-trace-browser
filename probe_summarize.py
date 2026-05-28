import io, os, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from main import _load_minimax_key, MinimaxClient, AgentPanel

c = MinimaxClient(_load_minimax_key(),
    region=os.environ.get("MINIMAX_REGION","global"),
    model=os.environ.get("MINIMAX_MODEL","MiniMax-M2"))

CTX = """[tabs (active: 0):
  0: 'Trump drops lawsuit against IRS over tax records - Yahoo' @ https://yahoo.com/news/trump-irs-lawsuit
]
[page text — use a reply action to answer using this content:
TITLE: Trump drops lawsuit against IRS over tax records

Former President Donald Trump has voluntarily withdrawn his long-running lawsuit against the Internal Revenue Service that sought to block the agency from releasing his tax returns to a congressional committee. Voluntarily withdrawing the lawsuit meant the judge assigned to the case, U.S. District Judge Kathleen Williams, did not rule on the case's merits — nor did the judge weigh in on the settlement that plaintiffs reached with Acting Attorney General Todd Blanche, Trump's former personal attorney.

The settlement awards $1.76 billion to a 'weaponization' fund. 'The purported settlement that the parties never placed before this Court raises profound questions about the parties' candor toward the Court and manipulation of the judicial system, which threatens to undermine confidence in the rule of law,' wrote one watchdog group in a critical statement.

Critics argue this resolution sets a troubling precedent for how high-profile officials can quietly resolve legal disputes outside public scrutiny. Supporters counter that voluntary settlements are common in civil cases. The IRS has not commented publicly on whether the tax records in question will now be sealed.
]"""

CASES = [
    "summarize this page",
    "what is this page about",
    "give me the key points in 3 bullets",
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
    for a in acts:
        kind = a.get("action")
        if kind == "reply":
            print(f"  REPLY:\n{a.get('text','')}")
        else:
            print(f"  {a}")
