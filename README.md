# Anti-Trace Browser

A lightweight, zero-trace privacy browser for Windows with a built-in **AI
agent** that can actually drive the browser. Real Chromium under the hood
(Microsoft Edge WebView2 — full proprietary codecs + Widevine DRM), wrapped
in a wxPython Chrome-style UI. The browsing session lives in a temp folder
that is shredded on exit; the only persistent state is the bookmarks you
explicitly star.

![python](https://img.shields.io/badge/python-3.10%2B-blue)
![platform](https://img.shields.io/badge/platform-Windows%2010%2F11-lightgrey)
![engine](https://img.shields.io/badge/engine-Edge%20WebView2-brightgreen)
![agent](https://img.shields.io/badge/agent-MiniMax%20%2B%20rules-purple)

## Why this exists

Most "private" / "incognito" modes still leak traces on disk and let trackers
profile you the moment you log in. This browser flips the defaults:

- **Ephemeral profile** — WebView2's user-data folder is a brand-new temp
  directory per run, `shutil.rmtree`-d on exit (and again on `atexit`).
- **No cookies, cache, or history survive the process** — everything is
  in-memory.
- **Generic User-Agent** to reduce browser fingerprinting.
- **DuckDuckGo** as the default search engine — no query logging, no profiling.
- **Wipe Session** (Ctrl+Shift+W) clears cookies / cache / IndexedDB /
  localStorage / all tabs on demand, mid-session.
- **Bookmarks** are the *only* persisted state, in a plain JSON file at
  `%APPDATA%\AntiTraceBrowser\bookmarks.json` — explicit user choices, not
  invisible tracking.

## What's in the UI

Top-down Chrome-style layout:

```
┌──────────────────────────────────────────────────────────────────────┐
│ ▔ Tab 1 ▔  ▔ Tab 2 ▔  +                              ◄─ tab strip   │
├──────────────────────────────────────────────────────────────────────┤
│ ← → ↻ ⌂ +  ⎚ Search or type a URL — no trace…   ☆ 📚 ✨ Wipe        │
├──────────────────────────────────────────────────────────────────────┤
│ ⭐ DuckDuckGo  ⭐ YouTube  ⭐ Wikipedia          ◄─ bookmarks bar    │
├─────────────────────────────────────┬────────────────────────────────┤
│                                     │  🦆 Duck Agent           ↻ ×  │
│       [ web page content ]          │                                │
│                                     │  You: skip the ad              │
│                                     │  Agent: [click] trusted…       │
│                                     │                                │
│                                     ├────────────────────────────────┤
│                                     │  Ask the agent…   (Enter)  Send│
└─────────────────────────────────────┴────────────────────────────────┘
```

## Features

### Browsing

- **Chrome-style omnibox** (URL + DuckDuckGo search in one pill-shaped bar)
  with magnifier/lock icon that swaps based on context.
- `Ctrl+Enter` → wrap text as `www.<text>.com`; `Shift+Enter` → `.net`.
- **Tabs at the top** (custom `TabStrip` + `wx.Simplebook`): `Ctrl+T` new,
  `Ctrl+W` close, middle-click closes, click `+` for blank, drag to reorder.
  `window.open()` and `target="_blank"` honored and routed to new tabs.
- **Find in page** (`Ctrl+F`), **Fullscreen** (`F11` + page-initiated HTML5
  fullscreen on YouTube etc.).
- Autoplay unblocked (`--autoplay-policy=no-user-gesture-required`).

### Bookmarks

- **Star button** (`Ctrl+D`) toggles a bookmark on the current page.
- **Bookmarks bar** below the toolbar (`Ctrl+Shift+B` to toggle).
- **Bookmark Manager** (`Ctrl+Shift+O`): search/filter, multi-select, rename
  (F2), delete (Delete), and **Import/Export** as JSON or Netscape HTML — the
  same format Chrome and Firefox use, so you can move bookmarks in/out of a
  real browser.

### Duck Agent — the natural-language browser controller

Sidepanel toggled with **`Ctrl+G`** or the ✨ toolbar button. Type plain
English; the agent executes a JSON action. Two layers:

1. **`RuleAgent` (local, instant)** handles unambiguous commands without
   calling any LLM — `open youtube`, `bookmark this`, `back`, `close tab`,
   `wipe`, `skip ad`, bare URLs/domains, plus an alias table for popular
   sites (~25 entries: youtube, gmail, wikipedia, msft rewards, kuaishou…).
2. **`MinimaxClient` (LLM, fuzzy)** picks up everything the rules don't
   match — *"find me a recipe for kung pao chicken"*, *"take me somewhere
   interesting"*, *"open the second result"*, *"summarize this page"*.

The agent has these actions:

| Action | Description |
|---|---|
| `navigate` / `new_tab` | Load URL in active / new tab |
| `search` | DuckDuckGo search in active tab |
| `page_type` | Type into the current page's search input + submit |
| `click` | Click element by CSS selector or visible text (polls for late-appearing elements) |
| `click_element` / `fill` / `select_option` | Act on an **observed** element by index (see below) |
| `scroll` | Scroll the page (`down`/`up`/`top`/`bottom`) to reveal controls |
| `close_tab` / `select_tab` | Manage tabs by index |
| `bookmark` / `home` / `back` / `forward` / `wipe` | Browser actions |
| `reply` / `done` | Plain text answer / finish the task |

### Observe → act loop (Gemini-style page manipulation)

When you ask the agent to *do* something on a page — click a control, fill a
form, tick a box, pick a dropdown option, scroll to find a button — it runs an
**agentic loop** instead of guessing:

1. **Observe** — a JS pass catalogs up to 40 visible interactive elements
   (links, buttons, inputs, selects, checkboxes, role=button/tab/menuitem),
   tagging each with a stable index and reporting its label, current `value`,
   `[CHECKED]` state, and selected dropdown option.
2. **Decide** — that catalog plus the goal goes to MiniMax, which picks the
   single next index-based action (`click_element`, `fill`, `select_option`,
   `scroll`).
3. **Act** — the action runs against the exact element by its index (no fragile
   selector guessing). Form fields are set via the native value setter so React
   sees the change; clicks fire a real pointer-event sequence.
4. **Repeat** — re-observe and continue until the goal is met (the agent emits
   `done`), capped at 8 steps with an oscillation guard that stops as soon as it
   would repeat itself.

Because the observation reports current state (`value=…`, `[CHECKED]`,
`selected=…`), the agent skips sub-tasks that are already done instead of
toggling them back off.

Examples that drive the loop:

```
fill the search box with cats and submit
check the agree box, then click sign up
choose Blue in the colour dropdown and click Create account
scroll down and click "load more"
log in with username alice (then it pauses for you to type the password)
```

**Smart context** — the agent's request to MiniMax includes, as relevant:

- `[tabs (active: N)]` — index, title, URL of every open tab.
- `[interactive elements …]` — the indexed element catalog (for the act loop).
- `[links on active page…]` — extracted when you say "click the Nth link".
- `[page text…]` — Reader-mode cleanup (capped at 8 KB) for "summarize" /
  "what's this page about".

**Multi-step + sequencing** — *"do 5 random searches in bing, recycle the
same tab"* → 5 `page_type` actions sequenced 2.5 s apart so each result is
visible before the next replaces it.

**Auto-skip toggle** — the **⏭ Skip** toolbar button (or `Ctrl+Shift+S`) arms a
persistent watcher that automatically clicks every YouTube skip button as it
appears — across pre-rolls, mid-rolls, and tab switches — with no per-ad prompt.
Turns green when on; click again, press `Ctrl+Shift+S`, or say "stop" to disable.
Runs entirely locally (no API tokens).

**OS-trusted click** — *"skip ad"* on YouTube routes to a `wx.UIActionSimulator`
mouse click at the button's real screen coordinates, because YouTube's player
checks `event.isTrusted` and ignores synthetic JavaScript clicks. The cursor
briefly jumps to the skip button and back; your original cursor position is
restored.

## Requirements

- Windows 10 or 11. WebView2 runtime is preinstalled on Win 11; on Win 10
  install the [Evergreen runtime](https://developer.microsoft.com/microsoft-edge/webview2/).
- Python **3.10+**.
- `wxPython` 4.2+.

## Install

```powershell
py -m pip install wxPython
```

To enable the MiniMax-powered agent fallback (optional — without it, you get
the rule-based agent only):

```powershell
copy .env.example .env
# Edit .env and fill in your MINIMAX_API_KEY (get one at minimax.io)
```

The `.env` file is gitignored. Alternatives in priority order: shell env var
`MINIMAX_API_KEY`, `%APPDATA%\AntiTraceBrowser\minimax_key.txt`, or a
`minimax_key.txt` file next to `main.py`.

## Run

```powershell
py main.py
```

Or double-click `launch.bat` (uses `pyw.exe` so no console window flashes).

## Keyboard shortcuts

| Keys | Action |
|---|---|
| `Ctrl+L` / `F6` | Focus address bar (select all) |
| `Ctrl+K` / `Ctrl+E` | Focus address bar for a search |
| `Enter` | Navigate / search |
| `Ctrl+Enter` | Wrap text as `www.<text>.com` |
| `Shift+Enter` | Wrap text as `www.<text>.net` |
| `Alt+←` / `Alt+→` | Back / Forward |
| `Ctrl+R` / `F5` | Reload |
| `Esc` | Stop loading |
| `Alt+Home` | Home page |
| `Ctrl+T` / `Ctrl+W` | New tab / close tab |
| `Ctrl+D` | Bookmark this page (toggle) |
| `Ctrl+Shift+B` | Toggle bookmarks bar |
| `Ctrl+Shift+O` | Open bookmark manager |
| `Ctrl+F` | Find in page |
| `F11` | Toggle fullscreen |
| **`Ctrl+G`** | **Toggle Duck Agent side panel** |
| **`Ctrl+Shift+S`** | **Toggle auto-skip YouTube ads** (also the ⏭ Skip toolbar button) |
| `↑` / `↓` (in agent input) | Bash-style prompt history |
| `Ctrl+Shift+W` | Wipe session |
| `Ctrl+Q` | Quit |

## Agent prompt cheatsheet

```
open youtube                        # rule, instant
go to github.com                    # rule, instant
search for python pyqt6 tutorial    # rule, instant
new tab to en.wikipedia.org         # rule, instant
bookmark this                       # rule, instant
close tab                           # rule, instant
back / forward / home / wipe        # rule, instant
skip ad                             # rule, OS-trusted click on YouTube

find me a recipe for kung pao chicken     # MiniMax, rewrites the query
take me somewhere interesting             # MiniMax, picks a site
open the first result                     # MiniMax + page-links extraction
click the wikipedia link                  # MiniMax + page-links extraction
summarize this page                       # MiniMax + page-text extraction
what's this page about                    # MiniMax + page-text extraction
do 3 random searches in bing              # MiniMax, 3 new tabs
do 30 random searches in bing,            # MiniMax, 30 page_types in the
   recycle the same tab                   #   same tab, 2.5s apart
close all bing tabs                       # MiniMax + tab list, multi-close

# observe→act loop (looks at the page, then manipulates it)
fill the search box with cats and submit
check the agree box and click sign up
choose Blue in the dropdown, then click Create account
scroll down and click load more
```

## Project layout

```
anti-trace-browser/
├── main.py              # everything — frame, omnibox, tabs, bookmarks,
│                          agent, MiniMax client, click engine
├── launch.bat           # one-click launcher (uses pyw.exe, no console)
├── .env.example         # template for MINIMAX_API_KEY / region / model
├── probe_codecs.py      # canPlayType() probe — what codecs does this build have
├── probe_youtube.py     # real-site test: does YouTube play
├── probe_fullscreen.py  # confirms document.fullscreenEnabled
├── probe_newwindow.py   # target=_blank → new tab handler test
├── probe_kuaishou.py    # Kuaishou 直播 button → new tab test
├── probe_minimax.py     # MiniMax round-trip / valid-JSON-action test
├── probe_rules.py       # local rule parser sanity check
├── probe_multi.py       # multi-action arrays
├── probe_pagetype.py    # page_type + same-tab sequencing
├── probe_clicklink.py   # link extraction + LLM picks the right one
├── probe_click.py       # click selector / text + ad-skip cases
├── probe_skip.py        # polling click against synthetic late-button
├── probe_skip_pointer.py # pointerdown listener verification
├── probe_summarize.py   # page-text extraction + MiniMax summary
├── probe_tabaware.py    # tab list context, multi-close ordering
├── probe_yt_live.py     # real YouTube — diagnose + trusted skip
├── probe_interact.py    # observe + index click/fill/select + observe→act loop
├── privacy_engine.py    # legacy PyQt6/QtWebEngine profile (reference)
└── logo*.{png,ico}      # icon assets
```

## Privacy posture summary

| What | Where | Survives session? |
|---|---|---|
| Cookies | WebView2 in-memory profile | No — temp folder shredded on exit |
| Cache | WebView2 in-memory profile | No |
| IndexedDB / localStorage | WebView2 in-memory profile | No |
| History | Not retained anywhere | No |
| Browser fingerprint | Generic Chrome/Edge UA | n/a |
| Search engine | DuckDuckGo (no logging) | n/a |
| Bookmarks | `%APPDATA%\AntiTraceBrowser\bookmarks.json` | **Yes** (explicit user choice) |
| Agent conversation | RAM only | No |
| Prompt history | RAM only | No |
| MiniMax API key | `.env` file you provide | Local file, gitignored |

## Known limitations

- **Windows only.** WebView2 is a Windows runtime; `wx.html2.WebView` falls
  back to other engines on macOS/Linux with different privacy/codec trade-offs.
- **DRM is best-effort.** Widevine ships with WebView2 but some streaming
  sites refuse non-mainstream browsers regardless.
- **Account-linked tracking still works** if you sign into
  Google/Facebook/etc. Privacy software can't unlink an account you authenticate to.
- **Bookmarks file is plaintext.** Encrypt it / your `%APPDATA%` if your
  threat model includes someone with filesystem access.
- **OS-trusted click** for YouTube ad skip requires the browser window to be
  **visible and not occluded** at the moment of the click. It briefly moves
  the system cursor.
- **MiniMax fallback requires a key.** Without one, only `RuleAgent`
  shortcuts work — still useful for `open X`, `search Y`, `skip ad`, etc.

## License

Personal project, no warranty. Use at your own risk.
