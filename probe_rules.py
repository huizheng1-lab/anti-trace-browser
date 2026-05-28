"""Verify the rule agent on the prompts the user actually tried."""
import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from main import RuleAgent

CASES = [
    "open msft rewards dashboard",
    "open you tube",
    "open youtube",
    "search for python pyqt6 tutorial",
    "new tab to en.wikipedia.org",
    "bookmark this",
    "close tab",
    "google python tutorial",
    "go to rewards.microsoft.com",
    "wipe session",
    "back",
    "home",
    "github.com",
]
for c in CASES:
    print(f"{c!r:50s} -> {RuleAgent.parse(c)}")
