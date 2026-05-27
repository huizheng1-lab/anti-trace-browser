# Anti-Trace Browser

A lightweight, zero-trace privacy browser for Windows. Built on Microsoft Edge
WebView2 (full Chromium engine — proprietary codecs and Widevine DRM), wrapped
in a wxPython Chrome-style UI.

## Why

Most "private" modes still leave traces on disk and let trackers profile you.
This browser does the opposite by default:

- **Ephemeral profile** — WebView2's user-data folder is a per-run temp
  directory, deleted on exit.
- **No cookies, cache, or history survive a session** — they live in memory
  only, and the WebView2 backing folder is `shutil.rmtree`-d on close.
- **Generic User-Agent** to reduce browser fingerprinting.
- **DuckDuckGo** as the default search engine (no query logging or profiling).
- **Wipe Session** button (Ctrl+Shift+W) clears cookies, cache, IndexedDB,
  localStorage, and resets all tabs to the home page on demand.
- **Bookmarks** persist as a single JSON file under `%APPDATA%`, the only
  thing kept between sessions — explicit user choices, not invisible tracking.

## Features

- Chrome-style omnibox (URL + DuckDuckGo search in one bar) with `Ctrl+Enter`
  to wrap as `www.X.com`, `Shift+Enter` for `.net`.
- Tabbed browsing (`Ctrl+T` / `Ctrl+W`) with `target="_blank"` and
  `window.open()` handled.
- Bookmarks bar (`Ctrl+Shift+B` to toggle) and Bookmark Manager
  (`Ctrl+Shift+O`) with JSON / Netscape-HTML import & export.
- Find-in-page (`Ctrl+F`), Fullscreen (`F11`), HTML5 video fullscreen, autoplay
  unlocked, Widevine-protected streams play.
- Wipe Session (`Ctrl+Shift+W`) — nuke cookies, cache, storage on demand.

## Requirements

- Windows 10/11 with WebView2 runtime (preinstalled on Windows 11; on Win 10
  install the [Evergreen runtime](https://developer.microsoft.com/microsoft-edge/webview2/)).
- Python 3.10+.

## Install

```powershell
py -m pip install wxPython
```

## Run

```powershell
py main.py
```

Or double-click `launch.bat`.

## Keyboard shortcuts

| Keys | Action |
|---|---|
| `Ctrl+L` / `F6` | Focus address bar (select all) |
| `Ctrl+K` / `Ctrl+E` | Focus search |
| `Enter` | Navigate / search |
| `Ctrl+Enter` | Wrap text as `www.<x>.com` |
| `Shift+Enter` | Wrap text as `www.<x>.net` |
| `Alt+←` / `Alt+→` | Back / Forward |
| `Ctrl+R` / `F5` | Reload |
| `Esc` | Stop loading |
| `Alt+Home` | Home page |
| `Ctrl+T` / `Ctrl+W` | New / close tab |
| `Ctrl+D` | Toggle bookmark for current page |
| `Ctrl+Shift+B` | Toggle bookmarks bar |
| `Ctrl+Shift+O` | Bookmark manager |
| `Ctrl+F` | Find in page |
| `F11` | Toggle fullscreen |
| `Ctrl+Shift+W` | Wipe session |
| `Ctrl+Q` | Quit |

## Files

- `main.py` — the browser frame, omnibox, bookmarks UI, accelerator wiring.
- `privacy_engine.py` — earlier Qt WebEngine privacy profile (kept for
  reference; no longer imported by `main.py`).
- `launch.bat` — one-click launcher (uses `pyw.exe` so no console flashes).
- `probe_*.py` — small standalone tests (codecs, fullscreen, new-window
  handling, real-site smoke tests).
- `logo*.{png,ico}` — application icon assets.

## License

Personal project, no warranty. Use at your own risk.
