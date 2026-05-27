# Anti-Trace Browser

A lightweight, zero-trace privacy browser for Windows. Real Chromium under the
hood (Microsoft Edge WebView2 — full proprietary codecs + Widevine DRM), wrapped
in a wxPython Chrome-style UI. The browsing session lives entirely in a
temp folder that is shredded on exit; the only thing that survives is the
bookmarks file you choose to keep.

![python](https://img.shields.io/badge/python-3.10%2B-blue)
![platform](https://img.shields.io/badge/platform-Windows%2010%2F11-lightgrey)
![engine](https://img.shields.io/badge/engine-Edge%20WebView2-brightgreen)

## Why this exists

Most "private" or "incognito" modes still leak traces on disk and let trackers
profile you the moment you log in or accept a cookie. This browser flips the
defaults:

- **Ephemeral profile** — WebView2's user-data folder is a brand-new temp
  directory per run, `shutil.rmtree`-d on exit (and again on `atexit`).
- **No cookies, cache, or history survive the process.** Everything is
  in-memory only.
- **Generic User-Agent** to reduce browser fingerprinting.
- **DuckDuckGo** as the default search engine — no query logging, no
  personal profiling, no tracker-laden ads.
- **Wipe Session** (`Ctrl+Shift+W`) clears cookies, cache, IndexedDB,
  `localStorage`, and resets all tabs on demand, mid-session.
- **Bookmarks** are the *only* persisted state, and they live as a single
  human-readable JSON file at `%APPDATA%\AntiTraceBrowser\bookmarks.json` —
  explicit user choices, not invisible tracking. Export/import any time.

## Screenshots

A Chrome-style omnibox over a real Chromium webview, plus a bookmarks bar:

```
┌─────────────────────────────────────────────────────────────────────┐
│ ← → ↻ ⌂ +   ⎚ Search DuckDuckGo or type a URL — no trace…  ☆ 📚 Wipe│
│ ⭐ DuckDuckGo   ⭐ YouTube   ⭐ Wikipedia   …                         │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│                       [ web page renders here ]                     │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

## Architecture

| Layer | Choice | Why |
|---|---|---|
| Renderer | **Microsoft Edge WebView2** | Real Chromium with H.264/AAC + Widevine, so YouTube, Netflix-style streams, and adult tube sites actually play. |
| UI toolkit | **wxPython** (`wx.html2.WebView`) | Native Win32 chrome — proper toolbar, address bar, tabs (`wx.aui.AuiNotebook`), bookmark dialog. No HTML chrome iframes. |
| Privacy isolation | `WEBVIEW2_USER_DATA_FOLDER` → temp dir + `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS` | The whole profile is a folder we own and delete. |
| Search | DuckDuckGo (`kp=-2&kak=-1`) | No history, no affiliate tags. |
| Bookmark store | Plain JSON in `%APPDATA%` | Trivially backed up, exported, or moved across machines. |

There's also an earlier `privacy_engine.py` (PyQt6 / QtWebEngine profile-based
implementation) kept in the tree for reference — the project moved to WebView2
because the PyPI Qt wheels ship without proprietary codecs, breaking video.

## Features

### Browsing

- Chrome-style **omnibox** (URL + search in one pill-shaped bar) with a
  magnifier/lock icon that swaps based on context.
- `Ctrl+Enter` → wrap text as `www.<text>.com`; `Shift+Enter` → `.net`.
- **Tabs** (`wx.aui.AuiNotebook`): `Ctrl+T` new, `Ctrl+W` close, drag to
  reorder, middle-click closes, `window.open()` and `target="_blank"` honored.
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

### Privacy controls

- **Wipe Session** (`Ctrl+Shift+W`) — closes all extra tabs, JS-clears
  cookies/localStorage/sessionStorage/Cache API/IndexedDB for the current
  origin, then calls WebView2's `ClearAllBrowsingData()` to nuke everything
  across origins, then resets to home.
- On window close: the WebView2 profile folder is deleted (twice — at
  `app.MainLoop()` return and via `atexit`).

## What about the bookmarks?

They are the *only* persistent state. If you want true zero-state — no file
on disk between sessions — you can:

1. Delete `%APPDATA%\AntiTraceBrowser\bookmarks.json` after each run, or
2. Patch `BookmarkStore.save()` to be a no-op (see `main.py`), or
3. Just not bookmark anything — without `Ctrl+D` the file is never created.

The file is plain JSON; back it up to wherever you want.

## Requirements

- Windows 10 or 11. WebView2 runtime is preinstalled on Win 11; on Win 10
  install the [Evergreen runtime](https://developer.microsoft.com/microsoft-edge/webview2/).
- Python **3.10+**.
- `wxPython` 4.2+.

## Install

```powershell
py -m pip install wxPython
```

## Run

```powershell
py main.py
```

Or double-click `launch.bat` (uses `pyw.exe` so no console window flashes).

A desktop shortcut with the app's globe icon can be created with PowerShell —
see `launch.bat` for the target/working-directory pattern.

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
| `Ctrl+Shift+W` | Wipe session |
| `Ctrl+Q` | Quit |

## Project layout

```
anti-trace-browser/
├── main.py              # Browser frame, omnibox, tabs, bookmarks, accelerators
├── privacy_engine.py    # Legacy PyQt6/QtWebEngine privacy profile (reference)
├── launch.bat           # One-click launcher (uses pyw.exe, no console)
├── probe_codecs.py      # canPlayType() probe — what codecs does this build have
├── probe_youtube.py     # Real-site test: does YouTube actually play
├── probe_fullscreen.py  # Confirms document.fullscreenEnabled
├── probe_newwindow.py   # window.open / target=_blank → new tab handler test
├── probe_kuaishou.py    # Live-site smoke test (clicks the 直播 button)
├── logo*.{png,ico}      # Application icon assets
└── README.md
```

## Known limitations

- **Windows only.** WebView2 is a Windows runtime; `wx.html2.WebView` falls back
  to other engines on macOS/Linux but with different privacy and codec
  trade-offs.
- **DRM is best-effort.** Widevine ships with WebView2 but some streaming sites
  refuse non-mainstream browsers regardless.
- **Account-linked tracking still works** if you sign into Google/Facebook/etc.
  Privacy software can't unlink an account you authenticate to.
- **Bookmarks file is plaintext.** If your threat model includes someone with
  filesystem access to `%APPDATA%`, encrypt the file or use full-disk encryption.

## License

Personal project, no warranty. Use at your own risk.
