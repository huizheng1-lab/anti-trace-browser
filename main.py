"""Anti-trace browser — wxPython + Edge WebView2 edition.

Real Chromium (full codecs + Widevine) hosted inside a native wx.Frame
so we get back a proper toolbar with an address bar, while still
playing every video.

Privacy posture:
  * WebView2 user-data folder lives in a per-run temp dir, wiped on exit
  * Cookies, cache, history, downloads all die with the process
  * Generic UA to reduce fingerprinting
  * Wipe Session button clears WebView2 browsing data on demand
"""

import atexit
import json
import os
import shutil
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote_plus, urlparse

# WebView2 reads these BEFORE wx.html2.WebView is constructed.
SESSION_DIR = tempfile.mkdtemp(prefix="atb_session_")
os.environ["WEBVIEW2_USER_DATA_FOLDER"] = SESSION_DIR
os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = (
    "--autoplay-policy=no-user-gesture-required "
    "--disable-features=AutofillServerCommunication,OptimizationHints"
)

import wx
import wx.html2
import wx.aui


# Chrome-ish palette.
CHROME_BG       = wx.Colour(0xDD, 0xE1, 0xE6)   # toolbar background
OMNIBOX_BG      = wx.Colour(0xF1, 0xF3, 0xF4)   # address bar pill background
OMNIBOX_BG_HOT  = wx.Colour(0xE8, 0xEA, 0xED)   # hover/focused background
OMNIBOX_BORDER  = wx.Colour(0xCB, 0xCE, 0xD1)
OMNIBOX_TEXT    = wx.Colour(0x20, 0x21, 0x24)
OMNIBOX_HINT    = wx.Colour(0x5F, 0x63, 0x68)


class Omnibox(wx.Panel):
    """Chrome-style pill-shaped address/search bar."""

    def __init__(self, parent, on_submit):
        super().__init__(parent)
        self._on_submit = on_submit
        self._hover = False
        self._is_search_icon = True  # show magnifier when nothing entered yet

        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.SetBackgroundColour(CHROME_BG)
        self.SetMinSize(wx.Size(700, 34))

        self.text = wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER | wx.BORDER_NONE)
        self.text.SetBackgroundColour(OMNIBOX_BG)
        self.text.SetForegroundColour(OMNIBOX_TEXT)
        self.text.SetHint("Search DuckDuckGo or type a URL — no trace is kept")
        self.text.SetFont(wx.Font(11, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))

        self.text.Bind(wx.EVT_TEXT_ENTER, self._fire)
        self.text.Bind(wx.EVT_KEY_DOWN, self._on_key)
        self.text.Bind(wx.EVT_SET_FOCUS, self._on_focus)
        self.text.Bind(wx.EVT_KILL_FOCUS, self._on_blur)
        self.text.Bind(wx.EVT_TEXT, lambda e: (self._update_icon(), e.Skip()))

        for w in (self, self.text):
            w.Bind(wx.EVT_ENTER_WINDOW, self._on_enter)
            w.Bind(wx.EVT_LEAVE_WINDOW, self._on_leave)

        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_SIZE, self._on_size)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda e: None)
        self.Bind(wx.EVT_LEFT_DOWN, lambda e: (self.text.SetFocus(), self.text.SelectAll()))

    # ---- public API -------------------------------------------------
    def SetValue(self, s: str):
        self.text.ChangeValue(s)
        self._update_icon()

    def GetValue(self) -> str:
        return self.text.GetValue()

    def SetFocusOnText(self):
        self.text.SetFocus()
        self.text.SelectAll()

    # ---- internals --------------------------------------------------
    def _fire(self, _evt):
        v = self.text.GetValue().strip()
        if v:
            self._on_submit(v)

    def _on_key(self, evt: wx.KeyEvent):
        key = evt.GetKeyCode()
        # Ctrl+Enter -> wrap with www. and .com (Chrome behavior)
        if key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER) and evt.ControlDown():
            v = self.text.GetValue().strip()
            if v and "://" not in v and " " not in v:
                head = v.split("/", 1)[0]
                tail = v[len(head):]
                if not head.startswith("www."):
                    head = "www." + head
                if "." not in head[4:]:
                    head = head + ".com"
                v = head + tail
            if v:
                self._on_submit(v)
            return
        # Shift+Enter -> .net (Chrome behavior)
        if key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER) and evt.ShiftDown():
            v = self.text.GetValue().strip()
            if v and "://" not in v and " " not in v:
                head = v.split("/", 1)[0]
                tail = v[len(head):]
                if not head.startswith("www."):
                    head = "www." + head
                if "." not in head[4:]:
                    head = head + ".net"
                v = head + tail
            if v:
                self._on_submit(v)
            return
        # Esc clears focus / restores current URL
        if key == wx.WXK_ESCAPE:
            self.text.Navigate(wx.NavigationKeyEvent.IsBackward)
            return
        evt.Skip()

    def _on_focus(self, evt):
        self._hover = True
        self.Refresh()
        evt.Skip()

    def _on_blur(self, evt):
        self._hover = False
        self.Refresh()
        evt.Skip()

    def _on_enter(self, _evt):
        self._hover = True
        self.Refresh()

    def _on_leave(self, _evt):
        if not self.text.HasFocus():
            self._hover = False
            self.Refresh()

    def _update_icon(self):
        new_state = not bool(self.text.GetValue().strip())
        if new_state != self._is_search_icon:
            self._is_search_icon = new_state
            self.Refresh()

    def _on_size(self, _evt):
        w, h = self.GetClientSize()
        # Leave room on the left for the icon, right for padding.
        self.text.SetSize(38, (h - 22) // 2, w - 50, 22)
        self.Refresh()

    def _on_paint(self, _evt):
        dc = wx.AutoBufferedPaintDC(self)
        dc.SetBackground(wx.Brush(CHROME_BG))
        dc.Clear()

        gc = wx.GraphicsContext.Create(dc)
        w, h = self.GetClientSize()
        radius = h / 2.0
        bg = OMNIBOX_BG_HOT if self._hover else OMNIBOX_BG

        gc.SetBrush(wx.Brush(bg))
        gc.SetPen(wx.Pen(OMNIBOX_BORDER, 1))
        gc.DrawRoundedRectangle(0.5, 0.5, w - 1, h - 1, radius)

        # Sync the TextCtrl background so it blends seamlessly.
        if self.text.GetBackgroundColour() != bg:
            self.text.SetBackgroundColour(bg)
            self.text.Refresh()

        # Icon: magnifier when empty/typing search, padlock when secure URL.
        gc.SetPen(wx.Pen(OMNIBOX_HINT, 2))
        gc.SetBrush(wx.TRANSPARENT_BRUSH)
        cx, cy = 18, h / 2
        if self._is_search_icon:
            # magnifier
            r = 5.5
            gc.DrawEllipse(cx - r, cy - r - 1, 2 * r, 2 * r)
            path = gc.CreatePath()
            path.MoveToPoint(cx + 4, cy + 3)
            path.AddLineToPoint(cx + 8, cy + 7)
            gc.StrokePath(path)
        else:
            # tiny padlock
            gc.DrawRoundedRectangle(cx - 5, cy - 1, 10, 8, 2)
            arc = gc.CreatePath()
            arc.AddArc(cx, cy - 1, 4, 3.14, 0, False)
            gc.StrokePath(arc)


def _cleanup_session():
    shutil.rmtree(SESSION_DIR, ignore_errors=True)


atexit.register(_cleanup_session)


# ---------- Bookmarks ------------------------------------------------
# Persisted explicitly by the user; not a tracking trace.
BOOKMARKS_DIR = Path(os.environ.get("APPDATA") or os.path.expanduser("~")) / "AntiTraceBrowser"
BOOKMARKS_DIR.mkdir(parents=True, exist_ok=True)
BOOKMARKS_FILE = BOOKMARKS_DIR / "bookmarks.json"


class BookmarkStore:
    def __init__(self):
        self.items: list[dict] = []
        self.load()

    def load(self):
        try:
            if BOOKMARKS_FILE.exists():
                data = json.loads(BOOKMARKS_FILE.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    self.items = [b for b in data if isinstance(b, dict) and b.get("url")]
        except Exception:
            self.items = []

    def save(self):
        try:
            BOOKMARKS_FILE.write_text(
                json.dumps(self.items, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except Exception:
            pass

    def has(self, url: str) -> bool:
        return any(b["url"] == url for b in self.items)

    def add(self, url: str, title: str):
        if not url or self.has(url):
            return
        self.items.append({"title": (title or url).strip()[:80], "url": url})
        self.save()

    def remove(self, url: str):
        self.items = [b for b in self.items if b["url"] != url]
        self.save()

    def rename(self, url: str, new_title: str):
        for b in self.items:
            if b["url"] == url:
                b["title"] = new_title.strip()[:80] or url
        self.save()


class BookmarksBar(wx.Panel):
    """Chrome-style strip of bookmark chips below the toolbar."""

    def __init__(self, parent, store: "BookmarkStore", on_navigate):
        super().__init__(parent)
        self.SetBackgroundColour(CHROME_BG)
        self.store = store
        self.on_navigate = on_navigate
        self.SetMinSize(wx.Size(-1, 30))
        self._sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.SetSizer(self._sizer)
        self.rebuild()

    def rebuild(self):
        self._sizer.Clear(True)
        self._sizer.AddSpacer(8)
        if not self.store.items:
            lbl = wx.StaticText(
                self,
                label="No bookmarks yet — click ☆ in the toolbar to bookmark this page.  Ctrl+Shift+B hides this bar.",
            )
            lbl.SetForegroundColour(OMNIBOX_HINT)
            lbl.SetFont(wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_ITALIC, wx.FONTWEIGHT_NORMAL))
            self._sizer.Add(lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 4)
        else:
            for b in self.store.items:
                self._sizer.Add(self._make_chip(b), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 2)
        self.Layout()
        self.Refresh()

    def _make_chip(self, bookmark: dict) -> wx.Button:
        title = bookmark["title"]
        label = title if len(title) <= 22 else title[:21] + "…"
        host = urlparse(bookmark["url"]).hostname or ""
        btn = wx.Button(self, label=label, style=wx.BORDER_NONE | wx.BU_EXACTFIT)
        btn.SetBackgroundColour(CHROME_BG)
        btn.SetForegroundColour(OMNIBOX_TEXT)
        btn.SetFont(wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        btn.SetToolTip(f"{title}\n{bookmark['url']}")
        btn.Bind(wx.EVT_BUTTON, lambda e, url=bookmark["url"]: self.on_navigate(url))
        btn.Bind(wx.EVT_RIGHT_DOWN, lambda e, b=bookmark: self._show_context(e, b))
        return btn

    def _show_context(self, _evt, bookmark: dict):
        menu = wx.Menu()
        open_it = menu.Append(wx.ID_ANY, "Open")
        rename_it = menu.Append(wx.ID_ANY, "Rename…")
        remove_it = menu.Append(wx.ID_ANY, "Remove bookmark")

        def do_rename(_):
            dlg = wx.TextEntryDialog(self, "New name:", "Rename bookmark", bookmark["title"])
            if dlg.ShowModal() == wx.ID_OK:
                self.store.rename(bookmark["url"], dlg.GetValue() or bookmark["title"])
                self.rebuild()
            dlg.Destroy()

        self.Bind(wx.EVT_MENU, lambda e: self.on_navigate(bookmark["url"]), open_it)
        self.Bind(wx.EVT_MENU, do_rename, rename_it)
        self.Bind(wx.EVT_MENU, lambda e: (self.store.remove(bookmark["url"]), self.rebuild()), remove_it)
        self.PopupMenu(menu)
        menu.Destroy()


SEARCH_URL = "https://duckduckgo.com/?q={q}&kp=-2&kak=-1"
HOME_URL = "https://duckduckgo.com/?kp=-2&kak=-1"

GENERIC_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/132.0.0.0 Safari/537.36 Edg/132.0.0.0"
)


def looks_like_url(text: str) -> bool:
    if "://" in text:
        return True
    if " " in text:
        return False
    if text.startswith(("about:", "javascript:", "data:")):
        return True
    head = text.split("/", 1)[0]
    if head == "localhost" or head.startswith("localhost:"):
        return True
    return "." in head and not head.endswith(".")


def resolve(text: str) -> str:
    text = text.strip()
    if not text:
        return HOME_URL
    if looks_like_url(text):
        if "://" not in text and not text.startswith(("about:", "javascript:", "data:")):
            text = "https://" + text
        return text
    return SEARCH_URL.format(q=quote_plus(text))


# Tool IDs
ID_BACK, ID_FWD, ID_RELOAD, ID_STOP, ID_HOME, ID_GO, ID_WIPE, ID_NEW_TAB, ID_CLOSE_TAB, ID_STAR, ID_TOGGLE_BMBAR, ID_BM_MGR, ID_GEMINI = (wx.NewIdRef() for _ in range(13))

GEMINI_URL = "https://gemini.google.com/"
DUCKAI_URL = "https://duck.ai/"

# --- duck.ai underlying chat API (reverse-engineered, no auth) ---
DUCKAI_API_STATUS = "https://duckduckgo.com/duckchat/v1/status"
DUCKAI_API_CHAT   = "https://duckduckgo.com/duckchat/v1/chat"
DUCKAI_MODEL      = "gpt-4o-mini"   # also: claude-3-haiku-20240307, mistralai/Mistral-Small-24B-Instruct-2501


class DuckAIClient:
    """Minimal client for duck.ai's underlying chat endpoint."""

    def __init__(self):
        self.vqd: str | None = None
        self.messages: list[dict] = []
        self._lock = threading.Lock()

    def reset(self):
        with self._lock:
            self.vqd = None
            self.messages = []

    def _refresh_vqd(self):
        req = urllib.request.Request(
            DUCKAI_API_STATUS,
            headers={
                "x-vqd-accept": "1",
                "User-Agent": GENERIC_USER_AGENT,
                "Accept": "*/*",
                "Cache-Control": "no-store",
                "Origin": "https://duckduckgo.com",
                "Referer": "https://duckduckgo.com/",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            self.vqd = (resp.headers.get("x-vqd-4")
                        or resp.headers.get("x-vqd-hash-1")
                        or resp.headers.get("x-vqd-hash"))

    def chat(self, user_text: str) -> str:
        with self._lock:
            self.messages.append({"role": "user", "content": user_text})
            if not self.vqd:
                self._refresh_vqd()

            body = json.dumps({
                "model": DUCKAI_MODEL,
                "messages": self.messages,
            }).encode("utf-8")
            headers = {
                "x-vqd-4": self.vqd or "",
                "Content-Type": "application/json",
                "User-Agent": GENERIC_USER_AGENT,
                "Accept": "text/event-stream",
                "Origin": "https://duckduckgo.com",
                "Referer": "https://duckduckgo.com/",
            }
            req = urllib.request.Request(DUCKAI_API_CHAT, data=body, method="POST", headers=headers)
            try:
                resp = urllib.request.urlopen(req, timeout=45)
            except urllib.error.HTTPError as e:
                if e.code in (400, 401, 403, 418, 429):
                    self._refresh_vqd()
                    headers["x-vqd-4"] = self.vqd or ""
                    req = urllib.request.Request(DUCKAI_API_CHAT, data=body, method="POST", headers=headers)
                    resp = urllib.request.urlopen(req, timeout=45)
                else:
                    raise

            new_vqd = resp.headers.get("x-vqd-4")
            if new_vqd:
                self.vqd = new_vqd

            parts: list[str] = []
            for raw in resp:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    obj = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                chunk = obj.get("message") or obj.get("content") or ""
                if chunk:
                    parts.append(chunk)
            text = "".join(parts).strip()
            self.messages.append({"role": "assistant", "content": text})
            return text


# Default AI assistant — duck.ai is anonymous (no login, no tracking) so it

# Default AI assistant — duck.ai is anonymous (no login, no tracking) so it
# matches the rest of the browser's privacy posture; switch to GEMINI_URL if
# you'd rather have Gemini.
ASSISTANT_URL = DUCKAI_URL

# Domains the assistant view is allowed to navigate within. Anything else gets
# intercepted and opened in a normal browser tab.
ASSISTANT_DOMAINS = (
    "duck.ai", "duckduckgo.com",
    "gemini.google.com", "accounts.google.com", "google.com",
    "ssl.gstatic.com", "www.gstatic.com",
)

# Side panel mode: "agent" = JSON-driven browser controller via duck.ai API.
#                  "chat"  = plain duck.ai webview (no actions).
ASSISTANT_MODE = "agent"


# ---------- MiniMax client (uses API key from env or local key file) ----------
MINIMAX_ENDPOINTS = {
    "global": "https://api.minimax.io/v1/text/chatcompletion_v2",
    "china":  "https://api.minimaxi.com/v1/text/chatcompletion_v2",
}
MINIMAX_DEFAULT_MODEL = "MiniMax-M2"


def _load_dotenv():
    """Load KEY=VALUE pairs from a `.env` file next to main.py into os.environ.

    Existing env vars are NOT overwritten — real shell env wins. Supports:
      KEY=value
      KEY="value with spaces"
      KEY='value'
      # comments
    """
    path = Path(__file__).parent / ".env"
    if not path.exists():
        return
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.lower().startswith("export "):
                line = line[7:].lstrip()
            if "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip()
            # Strip surrounding quotes if matched.
            if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
                val = val[1:-1]
            os.environ.setdefault(key, val)
    except Exception:
        pass


_load_dotenv()


def _load_minimax_key() -> str | None:
    """Get the MiniMax key without ever putting it in source.

    Order: env var MINIMAX_API_KEY → `%APPDATA%\\AntiTraceBrowser\\minimax_key.txt`
    → `minimax_key.txt` next to main.py.
    """
    k = os.environ.get("MINIMAX_API_KEY")
    if k:
        return k.strip()
    for path in (BOOKMARKS_DIR / "minimax_key.txt",
                 Path(__file__).parent / "minimax_key.txt"):
        try:
            if path.exists():
                return path.read_text(encoding="utf-8").strip() or None
        except Exception:
            pass
    return None


class MinimaxClient:
    """Thin wrapper around MiniMax's chat-completions endpoint."""

    def __init__(self, api_key: str, region: str = "global", model: str = MINIMAX_DEFAULT_MODEL):
        self.api_key = api_key
        self.endpoint = MINIMAX_ENDPOINTS.get(region, MINIMAX_ENDPOINTS["global"])
        self.model = model

    def chat(self, messages: list[dict], timeout: float = 30.0) -> str:
        body = json.dumps({
            "model": self.model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": 2000,
        }).encode("utf-8")
        req = urllib.request.Request(
            self.endpoint,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"MiniMax returned non-JSON: {raw[:200]}") from e
        # Standard OpenAI-style shape: choices[0].message.content
        try:
            return obj["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError):
            # MiniMax sometimes returns {"reply":"..."} or {"data": {"text": "..."}}
            for path in (("reply",), ("data", "text")):
                v = obj
                ok = True
                for k in path:
                    if isinstance(v, dict) and k in v:
                        v = v[k]
                    else:
                        ok = False; break
                if ok and isinstance(v, str):
                    return v.strip()
            # Surface server error if present.
            err = obj.get("base_resp") or obj.get("error") or obj
            raise RuntimeError(f"MiniMax response unrecognised: {err}")


class RuleAgent:
    """Deterministic natural-language → browser action parser.

    Covers the verbs that don't need an LLM: open / go to / navigate / new tab /
    search / close tab / bookmark / wipe / home / back / forward. Plus a small
    alias table for popular sites so `open youtube` knows the URL.
    """

    SITE_ALIASES = {
        "youtube":   "https://www.youtube.com/",
        "yt":        "https://www.youtube.com/",
        "google":    "https://www.google.com/",
        "gmail":     "https://mail.google.com/",
        "wikipedia": "https://en.wikipedia.org/",
        "wiki":      "https://en.wikipedia.org/",
        "github":    "https://github.com/",
        "twitter":   "https://twitter.com/",
        "x":         "https://x.com/",
        "reddit":    "https://www.reddit.com/",
        "duckduckgo":"https://duckduckgo.com/",
        "ddg":       "https://duckduckgo.com/",
        "amazon":    "https://www.amazon.com/",
        "ebay":      "https://www.ebay.com/",
        "yahoo":     "https://www.yahoo.com/",
        "bing":      "https://www.bing.com/",
        "you tube":  "https://www.youtube.com/",
        "msft rewards": "https://rewards.microsoft.com/",
        "microsoft rewards": "https://rewards.microsoft.com/",
        "rewards":   "https://rewards.microsoft.com/",
        "kuaishou":  "https://www.kuaishou.com/",
        "tiktok":    "https://www.tiktok.com/",
        "netflix":   "https://www.netflix.com/",
        "chatgpt":   "https://chat.openai.com/",
        "claude":    "https://claude.ai/",
        "gemini":    "https://gemini.google.com/",
        "duck ai":   "https://duck.ai/",
        "duckai":    "https://duck.ai/",
    }

    @classmethod
    def _alias_lookup(cls, target: str) -> str | None:
        low = target.lower().rstrip(" .!,?")
        for alias in sorted(cls.SITE_ALIASES, key=len, reverse=True):
            if low == alias or low.startswith(alias + " "):
                return cls.SITE_ALIASES[alias]
        return None

    @classmethod
    def parse(cls, text: str, prefer_llm: bool = False) -> tuple[dict, bool]:
        """Returns (action, matched). When prefer_llm=True, only the highest-
        confidence rules fire (so an LLM can handle fuzzy intents instead)."""
        s = text.strip()
        if not s:
            return ({"action": "reply", "text": "(empty)"}, True)
        low = s.lower()

        # STOP / CANCEL pending polls — no LLM needed.
        if low in {"stop", "cancel", "abort", "cancel pending",
                   "stop agent", "cancel agent", "kill",
                   "stop skipping", "stop auto skip", "stop autoskip",
                   "no more skipping", "no more auto skip"}:
            return ({"action": "cancel"}, True)
        # AUTO-SKIP — keep watching for every skip button on this/future ads.
        if low in {"auto skip", "auto skip ad", "auto skip ads", "autoskip",
                   "skip all ads", "always skip ads", "always skip",
                   "block ads", "block all ads", "skip every ad"}:
            return ({"action": "auto_skip"}, True)
        # SKIP YOUTUBE AD — built-in shortcut, no LLM needed.
        if low in {"skip ad", "skip the ad", "skip ads", "skip this ad",
                   "skipad", "skip"}:
            return ({
                "action": "click",
                # Comma-separated selector list — first visible match wins.
                "selector": (
                    "button.ytp-ad-skip-button-modern, "
                    ".ytp-ad-skip-button-modern, "
                    "button.ytp-skip-ad-button, "
                    ".ytp-skip-ad-button, "
                    "button.ytp-ad-skip-button, "
                    ".ytp-ad-skip-button, "
                    ".ytp-ad-skip-button-container button, "
                    ".videoAdUiSkipButton, "
                    "#skip-button button, "
                    "[id*='skip-button'] button, "
                    "button[class*='skip-ad-button'], "
                    "button[class*='ytp-ad-skip']"
                ),
                "wait_ms": 25000,    # some YouTube ads reveal skip 15+s in
                "trusted": True,     # YouTube ignores synthetic isTrusted=false
            }, True)
        if low in {"close", "close tab", "close this", "close this tab", "x"}:
            return ({"action": "close_tab"}, True)
        if low in {"bookmark", "bookmark this", "save", "save bookmark",
                   "save this", "star this", "star"}:
            return ({"action": "bookmark"}, True)
        if low in {"wipe", "wipe session", "clear", "clear session",
                   "clear cookies", "incognito reset"}:
            return ({"action": "wipe"}, True)
        if low in {"home", "go home"}:
            return ({"action": "home"}, True)
        if low in {"back", "go back", "previous"}:
            return ({"action": "back"}, True)
        if low in {"forward", "go forward", "next"}:
            return ({"action": "forward"}, True)

        # NEW TAB
        for verb in ("new tab to ", "new tab ", "open new tab to ",
                     "open new tab ", "open in new tab "):
            if low.startswith(verb):
                target = s[len(verb):].strip()
                alias = cls._alias_lookup(target)
                if alias:
                    return ({"action": "new_tab", "url": alias}, True)
                if looks_like_url(target):
                    return ({"action": "new_tab", "url": target if "://" in target else "https://" + target}, True)
                if prefer_llm:
                    break  # let LLM resolve fuzzy targets
                return (cls._resolve_target("new_tab", target), True)

        # OPEN / GO TO — only exact alias or URL is confident.
        for verb in ("open ", "go to ", "goto ", "navigate to ", "visit ",
                     "take me to ", "load "):
            if low.startswith(verb):
                target = s[len(verb):].strip()
                alias = cls._alias_lookup(target)
                if alias:
                    return ({"action": "navigate", "url": alias}, True)
                if looks_like_url(target):
                    return ({"action": "navigate", "url": target if "://" in target else "https://" + target}, True)
                if prefer_llm:
                    break
                return (cls._resolve_target("navigate", target), True)

        # SEARCH — only when no LLM available (LLM rewrites sloppy queries).
        if not prefer_llm:
            for verb in ("search for ", "search ", "find ", "look up ",
                         "google ", "ddg ", "duckduckgo "):
                if low.startswith(verb):
                    q = s[len(verb):].strip()
                    if q:
                        return ({"action": "search", "query": q}, True)

        # Bare URL or domain — always confident.
        if looks_like_url(s):
            return ({"action": "navigate", "url": s if "://" in s else "https://" + s}, True)

        # Not recognised. With an LLM, defer; without, fall back to literal search.
        if prefer_llm:
            return ({"action": "reply", "text": "asking minimax…"}, False)
        return ({"action": "search", "query": s}, False)

    @classmethod
    def _resolve_target(cls, action: str, target: str) -> dict:
        if not target:
            return {"action": "reply", "text": f"What should I {action.replace('_',' ')}?"}
        t = target
        for art in ("the ", "a ", "an "):
            if t.lower().startswith(art):
                t = t[len(art):]
        low = t.lower().rstrip(" .!,?")
        for alias in sorted(cls.SITE_ALIASES, key=len, reverse=True):
            if low == alias or low.startswith(alias + " "):
                return {"action": action, "url": cls.SITE_ALIASES[alias]}
        if looks_like_url(t):
            return {"action": action, "url": t if "://" in t else "https://" + t}
        if " " not in t and "." not in t and len(t) <= 30:
            return {"action": action, "url": f"https://{t}.com/"}
        return {"action": "search", "query": t}


class _DuckWebviewClient:
    """Drives the duck.ai web UI inside a hidden WebView2 to issue prompts.

    duck.ai's REST API now requires JS-computed anti-bot tokens, so we route
    requests through the actual page just like a human would.
    """

    INIT_URL = "https://duckduckgo.com/?q=DuckDuckGo+AI+Chat&ia=chat&duckai=1"

    # Robust DOM ops — duck.ai's CSS classes change, so we query by role/type.
    JS_TYPE_AND_SEND = r"""
    (function(text){
      function findInput(){
        var el = document.querySelector('textarea[name="user-prompt"]')
              || document.querySelector('textarea[placeholder]')
              || document.querySelector('textarea');
        return el;
      }
      function findSend(){
        var bs = document.querySelectorAll('button');
        for (var i=0;i<bs.length;i++){
          var b = bs[i];
          var lbl = (b.getAttribute('aria-label') || b.innerText || b.title || '').toLowerCase();
          if (/send/.test(lbl)) return b;
          if (b.type === 'submit') return b;
        }
        return null;
      }
      var ta = findInput();
      if (!ta) return 'NO_INPUT';
      var setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
      setter.call(ta, text);
      ta.dispatchEvent(new Event('input', {bubbles:true}));
      var btn = findSend();
      if (btn) { btn.click(); return 'SENT_BUTTON'; }
      ta.dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', bubbles:true, cancelable:true}));
      return 'SENT_ENTER';
    })(%s);
    """

    JS_READ_LAST_REPLY = r"""
    (function(){
      // Each chat turn lives in an article element with role 'group' or 'article'.
      var nodes = document.querySelectorAll('article, [role="article"], [data-testid="message"]');
      if (!nodes || nodes.length === 0) {
        // fallback: prose blocks
        nodes = document.querySelectorAll('main div[class*="prose"], main p');
      }
      if (!nodes || nodes.length === 0) return JSON.stringify({status:'EMPTY', text:''});
      var last = nodes[nodes.length - 1];
      var text = (last.innerText || '').trim();
      // Heuristic: 'still typing' is usually indicated by an animated cursor span.
      var stillTyping = !!last.querySelector('[class*="cursor"], [class*="typing"], [class*="loading"]');
      return JSON.stringify({status: stillTyping ? 'TYPING' : 'DONE', text: text});
    })();
    """

    def __init__(self, host_panel: wx.Panel):
        self.view = wx.html2.WebView.New(
            host_panel, backend=wx.html2.WebViewBackendEdge, url=self.INIT_URL,
        )
        self.view.SetUserAgent(GENERIC_USER_AGENT)
        self.view.Bind(wx.html2.EVT_WEBVIEW_NEWWINDOW, lambda e: None)  # swallow popups
        self._ready = False
        self._loaded_once = False
        self.view.Bind(wx.html2.EVT_WEBVIEW_LOADED, self._on_loaded)
        self._pending_baseline_text: str | None = None

    def _on_loaded(self, _evt):
        self._loaded_once = True

    def send(self, prompt: str, on_reply, on_error):
        """Submit `prompt`, poll until duck.ai's UI shows a steady reply, then
        invoke on_reply(text). All callbacks run on the main thread."""
        if not self._loaded_once:
            wx.CallLater(800, lambda: self.send(prompt, on_reply, on_error))
            return

        # Snapshot the current last-reply text so we can detect when a *new* one appears.
        def snap_then_send(baseline_text: str):
            self._pending_baseline_text = baseline_text
            js_payload = self.JS_TYPE_AND_SEND % json.dumps(prompt)
            self.view.RunScript(js_payload)
            wx.CallLater(1200, lambda: self._poll(time_left=45.0, on_reply=on_reply, on_error=on_error))

        # Read current "last reply" text first.
        def got_baseline(success, raw):
            if not success:
                snap_then_send("")
                return
            try:
                obj = json.loads(raw or "{}")
                snap_then_send(obj.get("text", "") or "")
            except Exception:
                snap_then_send("")

        self._run_and_get(self.JS_READ_LAST_REPLY, got_baseline)

    # ---- polling / JS helpers ----
    def _poll(self, time_left: float, on_reply, on_error, stable_count: list[int] | None = None,
              last_text: list[str] | None = None):
        if stable_count is None: stable_count = [0]
        if last_text is None:    last_text = [""]

        if time_left <= 0:
            on_error("timed out waiting for duck.ai reply")
            return

        def got(success, raw):
            if not success:
                wx.CallLater(800, lambda: self._poll(time_left - 0.8, on_reply, on_error, stable_count, last_text))
                return
            try:
                obj = json.loads(raw or "{}")
            except Exception:
                wx.CallLater(800, lambda: self._poll(time_left - 0.8, on_reply, on_error, stable_count, last_text))
                return
            txt = (obj.get("text") or "").strip()
            status = obj.get("status")
            baseline = self._pending_baseline_text or ""
            # Brand-new reply must differ from baseline AND not be the user's echo.
            is_new = (txt and txt != baseline and not txt.startswith(self._user_echo_prefix(txt)))
            if status == "DONE" and is_new and txt == last_text[0]:
                stable_count[0] += 1
                if stable_count[0] >= 2:  # text unchanged across two polls → done
                    on_reply(txt)
                    return
            elif status == "DONE" and is_new:
                last_text[0] = txt
                stable_count[0] = 0
            wx.CallLater(900, lambda: self._poll(time_left - 0.9, on_reply, on_error, stable_count, last_text))

        self._run_and_get(self.JS_READ_LAST_REPLY, got)

    @staticmethod
    def _user_echo_prefix(_t: str) -> str:
        # We don't know which DOM node is the user's; this is just a hook.
        return "\x00\x00\x00"

    def _run_and_get(self, script: str, cb):
        # wx.html2 has no portable "runScript with return value"; use the
        # 2-arg RunScript form that returns (success, output) via reference.
        try:
            ok, out = self.view.RunScript(script)
            cb(bool(ok), out or "")
        except Exception:
            cb(False, "")


class _AgentPrompt:
    """Mixin holding the agent's system prompt (kept separate for readability)."""

    SYSTEM_PROMPT = (
        "You control a privacy-focused web browser. Your ONLY output is JSON — "
        "either a single action object on one line, OR a JSON array of action "
        "objects when the user asked for multiple steps. No prose, no markdown, "
        "no code fences, no leading text.\n\n"
        "The user message includes a [tabs (active: N)] list with the URL and "
        "title of EVERY open tab indexed from 0. Use those indices when the "
        "user refers to other tabs ('close the youtube tab', 'switch to the "
        "first one', 'close all the tabs you opened').\n\n"
        "ACTIONS (pick exactly one):\n"
        '  {"action":"navigate","url":"https://..."}   load URL in the ACTIVE tab\n'
        '  {"action":"new_tab","url":"https://..."}    open URL in a NEW tab\n'
        '  {"action":"search","query":"..."}           DuckDuckGo search in active tab\n'
        '  {"action":"close_tab","index":N}            close tab at index N (omit index for active tab)\n'
        '  {"action":"select_tab","index":N}           switch to tab N\n'
        '  {"action":"page_type","text":"..."}         type into the active page\'s search input and submit\n'
        '                                              (use this when the user is already ON a search site\n'
        '                                              like bing.com and just wants to issue a query without\n'
        '                                              reloading the URL)\n'
        '  {"action":"click","selector":"...","wait_ms":N}   click first element matching CSS selector.\n'
        '                                                    Polls up to wait_ms (default 8000) until the element\n'
        '                                                    appears, so late-loading buttons like YouTube\'s\n'
        '                                                    skip-ad work (skip button appears after ~5s).\n'
        '  {"action":"click","text":"...","wait_ms":N}       same but match by visible text / aria-label.\n'
        '  {"action":"click_element","index":N}        click the observed element #N (see [interactive elements]).\n'
        '  {"action":"fill","index":N,"text":"..."}    type text into observed field #N.\n'
        '  {"action":"select_option","index":N,"option":"..."}  pick a dropdown option on observed select #N.\n'
        '  {"action":"scroll","direction":"down|up|top|bottom","amount":700}  scroll the page.\n'
        '  {"action":"bookmark"}                       bookmark active page\n'
        '  {"action":"home"} / {"action":"back"} / {"action":"forward"} / {"action":"wipe"}\n'
        '  {"action":"reply","text":"..."}             ONLY when no action fits\n\n'
        "PREFER index-based actions (click_element / fill / select_option) when an\n"
        "[interactive elements] block is present — it lists exactly what is on the\n"
        "page with stable indices, so they are far more reliable than guessing a\n"
        "selector or text. Use scroll to reveal elements that are out of view.\n\n"
        "RULES:\n"
        "1. ENGINE-SPECIFIC SEARCH: construct the URL and use navigate.\n"
        "   • 'search bing X'   → navigate https://www.bing.com/search?q=X\n"
        "   • 'search google X' → navigate https://www.google.com/search?q=X\n"
        "   • 'search yahoo X'  → navigate https://search.yahoo.com/search?p=X\n"
        "   Use the {search} action only for the default DuckDuckGo.\n"
        "2. RANDOM / SURPRISE: if user says 'random', 'something interesting',\n"
        "   'anything', 'surprise me', INVENT a concrete query yourself (e.g.\n"
        "   'history of the saxophone', 'octopus intelligence'). Never pass the\n"
        "   literal word 'random' as the query.\n"
        "3. PAGE INTERACTION:\n"
        "   • [links on active page…] block → pick a URL and navigate.\n"
        "   • [page text…] block → answer with reply using that content.\n"
        "   • Clicking buttons / skipping ads / dismissing popups → use the\n"
        "     click action with either a 'text' matcher (preferred) or a CSS\n"
        "     'selector'. Known cases:\n"
        "       YouTube skip-ad button:\n"
        "         selector \".ytp-skip-ad-button, .ytp-ad-skip-button-modern, .ytp-ad-skip-button, .videoAdUiSkipButton\"\n"
        "         (try those FIRST before falling back to text:'Skip').\n"
        "       Cookie banners → text:'Accept' or text:'Reject'.\n"
        "       Newsletter popups → text:'Close' or text:'No thanks'.\n"
        "   • Filling forms / clicking specific controls → use the\n"
        "     [interactive elements] block + click_element/fill/select_option.\n"
        "   • Scroll with the scroll action to reach off-screen elements.\n"
        "4. CLEAN UP sloppy queries. 'find me a recipe for kung pao chicken' →\n"
        "   query 'kung pao chicken recipe', NOT 'me a recipe for…'.\n"
        "5. NEW vs ACTIVE: use new_tab only if user explicitly says 'new tab',\n"
        "   or when fulfilling step 6 below (multiple results).\n"
        "6. MULTIPLE STEPS: if the user asks for N of something ('do 3 random\n"
        "   searches', 'open 4 cat photo sites'), return a JSON ARRAY of action\n"
        "   objects — one per step. Use new_tab for each so results land in\n"
        "   their own tabs. If user says 'same tab' or 'recycle the tab' or\n"
        "   'don't open new ones', use page_type (when on a search site) or\n"
        "   navigate (otherwise) — they'll be sequenced with a delay so each\n"
        "   one is visible. Cap at 20 actions per response.\n\n"
        "EXAMPLES:\n"
        "User: do a random keyword search\n"
        '→ {"action":"search","query":"deep sea hydrothermal vents"}\n'
        "User: do a random search in bing\n"
        '→ {"action":"navigate","url":"https://www.bing.com/search?q=deep sea hydrothermal vents"}\n'
        "User: do 3 random searches in bing\n"
        '→ [{"action":"new_tab","url":"https://www.bing.com/search?q=Mariana+Trench+depth"},'
        '{"action":"new_tab","url":"https://www.bing.com/search?q=ancient+Greek+philosophy"},'
        '{"action":"new_tab","url":"https://www.bing.com/search?q=Voyager+1+location"}]\n'
        "User: open youtube and wikipedia in new tabs\n"
        '→ [{"action":"new_tab","url":"https://www.youtube.com/"},'
        '{"action":"new_tab","url":"https://en.wikipedia.org/"}]\n'
        "User: open a link on this page\n"
        '→ {"action":"reply","text":"I can\'t click links on the page yet — only navigate the browser. Tell me a URL or topic and I\'ll open it."}\n'
        "User: take me somewhere to read tech news\n"
        '→ {"action":"navigate","url":"https://techcrunch.com"}\n'
        "User: summarize this page (with a [page text…] block provided)\n"
        '→ {"action":"reply","text":"<2-4 sentence summary of the provided page text>"}\n'
        "User: close all the tabs you opened (when tabs list shows 0=blank, 1..3=just-opened bings)\n"
        '→ [{"action":"close_tab","index":3},{"action":"close_tab","index":2},{"action":"close_tab","index":1}]\n'
        "User: close the youtube tab (tab 2 is youtube)\n"
        '→ {"action":"close_tab","index":2}\n'
        "User: click the first result (with a [links on active page…] block provided)\n"
        "  SKIP links whose text contains 'sponsored', 'ad', 'advertisement', or whose\n"
        "  domain looks like an ad network (e.g. ads.*, *.doubleclick.net). When the\n"
        "  user says 'first result' they mean the first ORGANIC result, not the first\n"
        "  sponsored slot. Then emit navigate with the chosen href.\n"
        '  → {"action":"navigate","url":"<href of first organic result>"}\n'
        "User: search this page for cats (active tab is bing.com)\n"
        '→ {"action":"page_type","text":"cats"}\n'
        "User: skip the ad (active tab is youtube.com)\n"
        '→ {"action":"click","selector":".ytp-skip-ad-button, .ytp-ad-skip-button-modern, .ytp-ad-skip-button, .videoAdUiSkipButton"}\n'
        "User: dismiss this cookie banner\n"
        '→ {"action":"click","text":"Accept"}\n'
        "User: fill the name with Bob and tick agree (with [interactive elements] showing "
        "#0 field 'Name', #3 checkbox 'I agree' [unchecked])\n"
        '→ {"action":"fill","index":0,"text":"Bob"}   (then next step: '
        '{"action":"click_element","index":3})\n'
        "User: choose Blue in the colour dropdown (#2 select selected='-- pick --')\n"
        '→ {"action":"select_option","index":2,"option":"Blue"}\n'
        "User: do 5 random searches in bing, recycle the same tab (active tab is bing.com)\n"
        '→ [{"action":"page_type","text":"deep sea hydrothermal vents"},'
        '{"action":"page_type","text":"history of the saxophone"},'
        '{"action":"page_type","text":"monarch butterfly migration"},'
        '{"action":"page_type","text":"Andean cloud forests"},'
        '{"action":"page_type","text":"octopus intelligence"}]\n'
    )

# Static JS template for the click action — single triple-quoted string so we
# don't fight Python escaping. Three %s placeholders, filled in via % formatting:
#   1) selector (JSON-encoded string or 'null')
#   2) text matcher (JSON-encoded string or 'null')
#   3) wait_ms (integer)
_CLICK_JS_TEMPLATE = r"""
(function(sel, txt, waitMs){
  function isVisible(el){
    if (!el || !el.getBoundingClientRect) return false;
    var r = el.getBoundingClientRect();
    if (r.width <= 1 || r.height <= 1) return false;
    var cs = window.getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') return false;
    if (parseFloat(cs.opacity || '1') < 0.05) return false;
    return true;
  }
  function wordMatch(haystack, needle){
    if (!haystack) return false;
    var h = haystack.toLowerCase();
    var n = needle.toLowerCase();
    if (h === n) return true;
    var idx = h.indexOf(n);
    if (idx < 0) return false;
    var before = idx === 0 ? '' : h[idx - 1];
    var after  = (idx + n.length) >= h.length ? '' : h[idx + n.length];
    function isWordCh(c){ return c && /[a-z0-9]/.test(c); }
    return !isWordCh(before) && !isWordCh(after);
  }
  function findEl(){
    if (sel) {
      try {
        var all = document.querySelectorAll(sel);
        for (var i = 0; i < all.length; i++) if (isVisible(all[i])) return all[i];
        // NOTE: no invisible fallback. YouTube creates the skip-ad button
        // hidden and reveals it ~5s in; we must keep polling until visible.
      } catch(_) {}
    }
    if (txt) {
      var needle = String(txt).trim();
      var cands = document.querySelectorAll(
        'button, a, [role="button"], input[type="button"], input[type="submit"], div[onclick], span[onclick]'
      );
      // Pass 1: visible + word-boundary match
      for (var i = 0; i < cands.length; i++) {
        var t = (cands[i].innerText || cands[i].value || cands[i].getAttribute('aria-label') || '').trim();
        if (isVisible(cands[i]) && wordMatch(t, needle)) return cands[i];
      }
      // Pass 2: visible + substring match
      for (var i = 0; i < cands.length; i++) {
        var t = (cands[i].innerText || cands[i].value || cands[i].getAttribute('aria-label') || '').trim();
        if (isVisible(cands[i]) && t.toLowerCase().indexOf(needle.toLowerCase()) !== -1) return cands[i];
      }
    }
    return null;
  }
  function fire(el, type, Ctor, cx, cy){
    try {
      var ev = new Ctor(type, {
        bubbles: true, cancelable: true, composed: true,
        view: window, clientX: cx, clientY: cy,
        button: 0, buttons: 1, pointerType: 'mouse', isPrimary: true
      });
      el.dispatchEvent(ev);
    } catch(_) {}
  }
  function realClick(el){
    try { el.scrollIntoView({block:'center'}); } catch(_) {}
    var r = el.getBoundingClientRect();
    var cx = r.left + r.width/2, cy = r.top + r.height/2;
    var PE = window.PointerEvent || MouseEvent;
    fire(el, 'pointerover', PE, cx, cy);
    fire(el, 'mouseover',   MouseEvent, cx, cy);
    fire(el, 'pointerdown', PE, cx, cy);
    fire(el, 'mousedown',   MouseEvent, cx, cy);
    fire(el, 'pointerup',   PE, cx, cy);
    fire(el, 'mouseup',     MouseEvent, cx, cy);
    fire(el, 'click',       MouseEvent, cx, cy);
    try { el.click(); } catch(_) {}
  }
  function label(el){
    return (el.innerText || el.value || el.getAttribute('aria-label') || el.tagName || '').toString().slice(0, 80);
  }
  var el = findEl();
  if (el) { realClick(el); return 'CLICKED:' + label(el); }
  if (waitMs <= 0) return 'NOT_FOUND';
  var deadline = Date.now() + waitMs;
  var iv = setInterval(function(){
    if (Date.now() > deadline) { clearInterval(iv); return; }
    var e = findEl();
    if (e) { clearInterval(iv); realClick(e); }
  }, 300);
  return 'POLLING:' + waitMs + 'ms';
})(%s, %s, %s);
"""


# Act on an element previously tagged with data-atb-idx by the observe step.
# %s placeholders: 1) index (int)  2) op JSON ('click'|'fill'|'select')
#                  3) value JSON (string for fill/select, else 'null')
_ACT_ON_INDEX_JS = r"""
(function(idx, op, value){
  var el = document.querySelector('[data-atb-idx="' + idx + '"]');
  if (!el) return 'NO_SUCH_INDEX';
  try { el.scrollIntoView({block:'center', inline:'center'}); } catch(_){}
  var label = (el.innerText || el.value || el.getAttribute('aria-label') ||
               el.getAttribute('placeholder') || el.tagName || '').toString().slice(0,60);
  function setNativeValue(input, v){
    var proto = input.tagName === 'TEXTAREA'
      ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
    var setter = Object.getOwnPropertyDescriptor(proto, 'value');
    if (setter && setter.set) { setter.set.call(input, v); } else { input.value = v; }
    input.dispatchEvent(new Event('input', {bubbles:true}));
    input.dispatchEvent(new Event('change', {bubbles:true}));
  }
  if (op === 'fill') {
    if (el.getAttribute('contenteditable') === 'true') {
      el.focus(); el.textContent = value;
      el.dispatchEvent(new Event('input', {bubbles:true}));
    } else {
      el.focus(); setNativeValue(el, value);
    }
    return 'FILLED:' + label;
  }
  if (op === 'select') {
    if (el.tagName.toLowerCase() === 'select') {
      var want = String(value).toLowerCase().trim();
      for (var i = 0; i < el.options.length; i++) {
        var o = el.options[i];
        if ((o.text || '').toLowerCase().trim().indexOf(want) !== -1 ||
            (o.value || '').toLowerCase().trim() === want) {
          el.selectedIndex = i;
          el.dispatchEvent(new Event('change', {bubbles:true}));
          return 'SELECTED:' + o.text;
        }
      }
      return 'NO_OPTION';
    }
    return 'NOT_A_SELECT';
  }
  // default: click — full trusted-ish pointer sequence
  var r = el.getBoundingClientRect();
  var cx = r.left + r.width/2, cy = r.top + r.height/2;
  var PE = window.PointerEvent || MouseEvent;
  function fire(type, Ctor){
    try {
      el.dispatchEvent(new Ctor(type, {
        bubbles:true, cancelable:true, composed:true, view:window,
        clientX:cx, clientY:cy, button:0, buttons:1, pointerType:'mouse', isPrimary:true
      }));
    } catch(_){}
  }
  // Pointer/mouse down+up for sites that track them, then a single native
  // activation via el.click(). We deliberately do NOT dispatch a synthetic
  // 'click' event because that would double-toggle checkboxes/radios.
  fire('pointerover', PE); fire('mouseover', MouseEvent);
  fire('pointerdown', PE); fire('mousedown', MouseEvent);
  fire('pointerup', PE);   fire('mouseup', MouseEvent);
  try { el.click(); } catch(_){}
  return 'CLICKED:' + label;
})(%s, %s, %s);
"""


class AgentPanel(_AgentPrompt, wx.Panel):
    """Chat UI that asks duck.ai / MiniMax for a JSON action, then runs it."""

    HINTS = (
        "Try: 'open YouTube'  |  'search for python pyqt6 tutorial'  |  "
        "'bookmark this'  |  'click the first result'  |  'fill the search box "
        "with cats and submit'  |  'check the agree box and click sign up'  |  "
        "'scroll down and click load more'  |  'summarize this page'"
    )

    # JS that returns the most useful clickable links on the active page.
    _EXTRACT_LINKS_JS = r"""
    (function(){
      var out = [];
      var seen = new Set();
      var nodes = document.querySelectorAll('a[href]');
      for (var i = 0; i < nodes.length && out.length < 25; i++) {
        var a = nodes[i];
        var href = a.href || '';
        if (!href || href.startsWith('javascript:') || href.startsWith('#')) continue;
        if (seen.has(href)) continue;
        var text = (a.innerText || a.getAttribute('aria-label') || a.title || '').trim().replace(/\s+/g, ' ');
        if (text.length < 3 || text.length > 200) continue;
        // Skip nav/footer chrome links (very short text inside header/footer/nav).
        var p = a;
        var inChrome = false;
        for (var d = 0; d < 6 && p && p !== document.body; d++) {
          var tag = (p.tagName || '').toLowerCase();
          if (tag === 'nav' || tag === 'header' || tag === 'footer') { inChrome = true; break; }
          p = p.parentNode;
        }
        if (inChrome && text.length < 30) continue;
        seen.add(href);
        out.push({ text: text.slice(0, 140), href: href });
      }
      return JSON.stringify(out);
    })();
    """

    # Regex-ish heuristic: when user wants to "click" something on the page,
    # we pre-extract links so MiniMax can pick one.
    @staticmethod
    def _wants_page_links(text: str) -> bool:
        low = text.lower()
        return any(needle in low for needle in (
            "click", "open one", "open the first", "open the second",
            "pick a link", "pick one", "pick the", "follow the",
            "first result", "second result", "third result",
            "open a result", "open one of",
        ))

    # Strip the active page down to its main text body for summarisation /
    # question answering.
    _EXTRACT_TEXT_JS = r"""
    (function(){
      var root = document.querySelector('main')
              || document.querySelector('article')
              || document.querySelector('[role="main"]')
              || document.body;
      if (!root) return '';
      var clone = root.cloneNode(true);
      var drop = ['nav','footer','header','aside','script','style','noscript','iframe',
                  'svg','form','button','input','textarea'];
      drop.forEach(function(tag){
        clone.querySelectorAll(tag).forEach(function(e){ e.remove(); });
      });
      // Heuristic ad/cookie/banner pruning by class/id substring.
      var bad = /(ad-|advert|cookie|banner|popup|promo|newsletter|subscribe|recommend|related|share|sidebar|toolbar)/i;
      clone.querySelectorAll('*').forEach(function(e){
        var s = (e.className || '') + ' ' + (e.id || '');
        if (typeof s === 'string' && bad.test(s)) e.remove();
      });
      var title = (document.title || '').trim();
      var text = (clone.innerText || '').replace(/[ \t]+/g, ' ').replace(/\n{3,}/g, '\n\n').trim();
      // Cap to a reasonable token budget.
      if (text.length > 8000) text = text.slice(0, 8000) + ' …[truncated]';
      return JSON.stringify({ title: title, text: text });
    })();
    """

    @staticmethod
    def _wants_page_text(text: str) -> bool:
        low = text.lower()
        return any(needle in low for needle in (
            "summarize", "summarise", "summary", "tl;dr", "tldr",
            "what does this say", "what does this page say",
            "what's this page about", "what is this page about",
            "what's this about", "what is this about",
            "explain this page", "explain the page", "explain this article",
            "read this", "read the page", "read this page",
            "key points", "main points", "main idea",
        ))

    # Indexed map of every visible interactive element. Each element gets a
    # temporary data-atb-idx attribute so later click_element/fill actions hit
    # exactly the element the model chose — no re-deriving selectors.
    _EXTRACT_INTERACTIVE_JS = r"""
    (function(){
      function isVisible(el){
        if (!el || !el.getBoundingClientRect) return false;
        var r = el.getBoundingClientRect();
        if (r.width <= 2 || r.height <= 2) return false;
        var cs = window.getComputedStyle(el);
        return cs.display !== 'none' && cs.visibility !== 'hidden' && parseFloat(cs.opacity||'1') > 0.05;
      }
      // Clear stale indices from a previous observation.
      document.querySelectorAll('[data-atb-idx]').forEach(function(e){ e.removeAttribute('data-atb-idx'); });
      var out = [];
      var nodes = document.querySelectorAll(
        'a[href], button, input, select, textarea, [role="button"], [role="link"], ' +
        '[role="checkbox"], [role="tab"], [role="menuitem"], [onclick], [contenteditable="true"]'
      );
      var vh = window.innerHeight;
      for (var i = 0; i < nodes.length && out.length < 40; i++) {
        var el = nodes[i];
        if (!isVisible(el)) continue;
        var tag = el.tagName.toLowerCase();
        var type = (el.getAttribute('type') || '').toLowerCase();
        if (tag === 'input' && type === 'hidden') continue;
        // Find a human label: aria-label, associated <label>, placeholder,
        // text content, then value as a last resort.
        var assocLabel = '';
        try {
          if (el.labels && el.labels.length) assocLabel = el.labels[0].innerText || '';
        } catch(_){}
        var label = (el.getAttribute('aria-label') || assocLabel || el.innerText ||
                     el.getAttribute('placeholder') || el.title ||
                     (type === 'checkbox' || type === 'radio' ? '' : el.value) || ''
                    ).trim().replace(/\s+/g, ' ').slice(0, 80);
        if (!label && tag === 'a') continue;  // unlabeled links are useless to the model
        var idx = out.length;
        el.setAttribute('data-atb-idx', String(idx));
        var r = el.getBoundingClientRect();
        var item = {
          i: idx, tag: tag, label: label,
          inView: r.top < vh && r.bottom > 0,
        };
        // Row context: the text of the nearest list-row / table-row / list-item
        // ancestor, so the model can tell WHICH item a control (e.g. a checkbox)
        // belongs to — essential for "select the promo emails" style tasks.
        var ctx = '';
        try {
          var p = el.parentElement, hops = 0;
          while (p && p !== document.body && hops < 8) {
            var role = (p.getAttribute && p.getAttribute('role')) || '';
            var ptag = p.tagName.toLowerCase();
            if (ptag === 'tr' || ptag === 'li' || role === 'row' || role === 'listitem' ||
                role === 'article' || ptag === 'article') {
              ctx = (p.innerText || '').trim().replace(/\s+/g, ' ').slice(0, 140);
              break;
            }
            p = p.parentElement; hops++;
          }
          if (!ctx && el.parentElement) {
            var t = (el.parentElement.innerText || '').trim().replace(/\s+/g, ' ');
            if (t && t.length <= 160) ctx = t.slice(0, 140);
          }
        } catch(_){}
        if (ctx && ctx !== label) item.context = ctx;
        if (type === 'checkbox' || type === 'radio') {
          item.kind = type;
          item.checked = !!el.checked;
        } else if (tag === 'input' || tag === 'textarea' || el.getAttribute('contenteditable') === 'true') {
          item.kind = 'field';
          if (type) item.type = type;
          if (el.value) item.value = String(el.value).slice(0, 40);
        } else if (tag === 'select') {
          item.kind = 'select';
          item.options = Array.prototype.slice.call(el.options, 0, 12).map(function(o){ return o.text.slice(0, 40); });
          item.selected = (el.selectedIndex >= 0 && el.options[el.selectedIndex])
                          ? el.options[el.selectedIndex].text.slice(0, 40) : '';
        } else {
          item.kind = 'click';
          if (tag === 'a' && el.href) item.href = el.href.slice(0, 120);
        }
        out.push(item);
      }
      return JSON.stringify({
        url: location.href.slice(0, 150),
        title: (document.title || '').slice(0, 100),
        scrollY: Math.round(window.scrollY),
        scrollMax: Math.round(Math.max(0, document.documentElement.scrollHeight - vh)),
        elements: out,
      });
    })();
    """

    @staticmethod
    def _wants_interaction(text: str) -> bool:
        low = text.lower()
        return any(needle in low for needle in (
            "click", "press", "fill", "type", "enter", "input", "select",
            "choose", "check", "tick", "submit", "login", "log in", "sign in",
            "sign up", "form", "button", "dropdown", "checkbox", "scroll",
            "accept", "dismiss", "close the", "play", "pause", "expand",
            "show more", "load more", "next page", "previous page",
        ))

    def __init__(self, parent, browser):
        super().__init__(parent)
        self.browser = browser
        self._busy = False
        self._history: list[str] = []
        self._history_idx: int | None = None  # None = not browsing

        self.SetBackgroundColour(CHROME_BG)

        # Header
        header = wx.Panel(self)
        header.SetBackgroundColour(CHROME_BG)
        title = wx.StaticText(header, label="🦆 Duck Agent")
        title.SetFont(wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        title.SetForegroundColour(OMNIBOX_TEXT)
        stop_btn = wx.Button(header, label="■", size=wx.Size(26, 26), style=wx.BORDER_NONE)
        stop_btn.SetBackgroundColour(CHROME_BG)
        stop_btn.SetForegroundColour(wx.Colour(0xC0, 0x39, 0x2B))
        stop_btn.SetToolTip("Cancel all pending agent jobs")
        reset_btn = wx.Button(header, label="↻", size=wx.Size(26, 26), style=wx.BORDER_NONE)
        reset_btn.SetBackgroundColour(CHROME_BG)
        reset_btn.SetToolTip("Reset conversation")
        close_btn = wx.Button(header, label="×", size=wx.Size(26, 26), style=wx.BORDER_NONE)
        close_btn.SetBackgroundColour(CHROME_BG)
        close_btn.SetFont(wx.Font(13, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        close_btn.SetToolTip("Hide panel (Ctrl+G)")
        h = wx.BoxSizer(wx.HORIZONTAL)
        h.Add(title, 1, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 10)
        h.Add(stop_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 2)
        h.Add(reset_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 2)
        h.Add(close_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        header.SetSizer(h)
        header.SetMinSize(wx.Size(-1, 34))

        # Transcript
        self.transcript = wx.TextCtrl(
            self,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2 | wx.BORDER_NONE,
        )
        self.transcript.SetBackgroundColour(wx.Colour(0xFA, 0xFB, 0xFC))
        self.transcript.SetFont(wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        self._append_styled("Hint", self.HINTS, wx.Colour(0x5F, 0x63, 0x68))

        # Input row
        input_row = wx.Panel(self)
        input_row.SetBackgroundColour(CHROME_BG)
        self.input = wx.TextCtrl(input_row, style=wx.TE_PROCESS_ENTER)
        self.input.SetHint("Ask the agent…  (Enter = send, ↑/↓ = history)")
        self.input.Bind(wx.EVT_KEY_DOWN, self._on_input_key)
        send_btn = wx.Button(input_row, label="Send", size=wx.Size(60, 28), style=wx.BORDER_NONE)
        send_btn.SetBackgroundColour(wx.Colour(0x1A, 0x73, 0xE8))
        send_btn.SetForegroundColour(wx.WHITE)
        send_btn.SetFont(wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        ih = wx.BoxSizer(wx.HORIZONTAL)
        ih.Add(self.input, 1, wx.EXPAND | wx.ALL, 4)
        ih.Add(send_btn, 0, wx.ALL, 4)
        input_row.SetSizer(ih)
        input_row.SetMinSize(wx.Size(-1, 40))

        # Hidden 1x1 webview that drives duck.ai for us.
        hidden_host = wx.Panel(self, size=(1, 1))
        hidden_host.SetMinSize(wx.Size(1, 1))
        hidden_host.SetMaxSize(wx.Size(1, 1))
        self._client = _DuckWebviewClient(hidden_host)

        # Layout
        v = wx.BoxSizer(wx.VERTICAL)
        v.Add(header, 0, wx.EXPAND)
        v.Add(self.transcript, 1, wx.EXPAND)
        v.Add(input_row, 0, wx.EXPAND)
        v.Add(hidden_host, 0, wx.EXPAND)
        self.SetSizer(v)

        # Bindings
        self.input.Bind(wx.EVT_TEXT_ENTER, lambda e: self._send())
        send_btn.Bind(wx.EVT_BUTTON, lambda e: self._send())
        close_btn.Bind(wx.EVT_BUTTON, lambda e: self.browser._toggle_assistant())
        reset_btn.Bind(wx.EVT_BUTTON, lambda e: self._reset())
        stop_btn.Bind(wx.EVT_BUTTON, lambda e: self._stop_pending())

    def _stop_pending(self):
        n = self.browser.cancel_pending_polls()
        self.cancel_loop()  # also halt any agentic observe→act loop
        self._busy = False  # also free up the LLM gate if it was set
        self._append_styled("Agent", f"cancelled {n} pending job(s) + any agent loop",
                            wx.Colour(0xC0, 0x39, 0x2B))

    def _reset(self):
        # Reload the hidden duck.ai page to drop conversation context.
        try:
            self._client.view.LoadURL(_DuckWebviewClient.INIT_URL)
            self._client._loaded_once = False
        except Exception:
            pass
        self.transcript.Clear()
        self._append_styled("Hint", "Conversation reset.  " + self.HINTS, wx.Colour(0x5F, 0x63, 0x68))

    def _append_styled(self, who: str, msg: str, color: wx.Colour):
        self.transcript.SetDefaultStyle(wx.TextAttr(color))
        self.transcript.AppendText(f"{who}: {msg}\n\n")

    def focus_input(self):
        self.input.SetFocus()

    def _on_input_key(self, evt: wx.KeyEvent):
        key = evt.GetKeyCode()
        if key == wx.WXK_UP:
            if not self._history:
                return  # nothing to recall
            if self._history_idx is None:
                self._history_idx = len(self._history) - 1
            elif self._history_idx > 0:
                self._history_idx -= 1
            self.input.ChangeValue(self._history[self._history_idx])
            self.input.SetInsertionPointEnd()
            return
        if key == wx.WXK_DOWN:
            if self._history_idx is None:
                return
            if self._history_idx < len(self._history) - 1:
                self._history_idx += 1
                self.input.ChangeValue(self._history[self._history_idx])
                self.input.SetInsertionPointEnd()
            else:
                self._history_idx = None
                self.input.ChangeValue("")
            return
        # Any other key cancels history browsing.
        self._history_idx = None
        evt.Skip()

    def _send(self):
        if self._busy:
            return
        text = self.input.GetValue().strip()
        if not text:
            return
        # Remember (dedup consecutive duplicates).
        if not self._history or self._history[-1] != text:
            self._history.append(text)
        self._history_idx = None
        self.input.Clear()
        self._append_styled("You", text, wx.Colour(0x20, 0x21, 0x24))

        # Fast path: local rules. When MiniMax is available, only the most
        # confident rule cases fire; fuzzy intent goes to the LLM.
        client = self.browser.minimax  # may be None
        action, matched = RuleAgent.parse(text, prefer_llm=bool(client))
        if matched or client is None:
            self._dispatch(action)
            return

        # Interaction goals (click / fill / scroll / multi-step "do X on this
        # page") go through the Gemini-style observe→act loop, which looks at
        # the page's interactive elements before each move.
        if self._wants_interaction(text) and not self._wants_page_text(text):
            self._run_agentic_loop(text)
            return

        # Fall through to single-shot MiniMax for other fuzzy intents.
        self._append_styled("Agent", "thinking (MiniMax)…", wx.Colour(0x5F, 0x63, 0x68))
        self._busy = True
        # Full tab list for context.
        active_idx = self.browser.book.GetSelection()
        tabs_lines = []
        for i, w in enumerate(self.browser._webviews):
            t = (w.GetCurrentTitle() or "").strip()
            u = (w.GetCurrentURL() or "").strip()
            tabs_lines.append(f"  {i}: {t!r} @ {u}")
        tabs_block = f"[tabs (active: {active_idx}):\n" + "\n".join(tabs_lines) + "\n]"

        # If the user wants to click/pick a link, pre-extract them from the active page.
        links_block = ""
        if self._wants_page_links(text):
            wv = self.browser.get_active_webview()
            if wv is not None:
                try:
                    ok, raw = wv.RunScript(self._EXTRACT_LINKS_JS)
                    if ok and raw:
                        items = json.loads(raw)
                        if isinstance(items, list) and items:
                            lines = [f"  {i}: {it.get('text','')[:100]!r} -> {it.get('href','')}"
                                     for i, it in enumerate(items[:20])]
                            links_block = ("[links on active page — pick one of these URLs and use navigate:\n"
                                           + "\n".join(lines) + "\n]\n")
                except Exception:
                    pass

        # If the user wants the page summarised / explained, pull the main text.
        page_block = ""
        if self._wants_page_text(text):
            wv = self.browser.get_active_webview()
            if wv is not None:
                try:
                    ok, raw = wv.RunScript(self._EXTRACT_TEXT_JS)
                    if ok and raw:
                        try:
                            data = json.loads(raw)
                        except json.JSONDecodeError:
                            data = None
                        if isinstance(data, dict):
                            t = (data.get("title") or "").strip()
                            body = (data.get("text") or "").strip()
                            if body:
                                page_block = (
                                    "[page text — use a reply action to answer using this content:\n"
                                    f"TITLE: {t}\n\n{body}\n]\n"
                                )
                except Exception:
                    pass

        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": f"{tabs_block}\n{links_block}{page_block}User: {text}"},
        ]

        def worker():
            try:
                raw = client.chat(messages)
                acts = self._parse_actions(raw) or [{"action": "reply", "text": raw}]
            except Exception as e:
                acts = [{"action": "reply", "text": f"MiniMax error: {e}"}]
            wx.CallAfter(self._finish_async, acts)

        threading.Thread(target=worker, daemon=True).start()

    def _finish_async(self, actions):
        self._busy = False
        if isinstance(actions, dict):
            actions = [actions]
        actions = list(actions or [])
        # When opening multiple new tabs, focus only the first; rest run as
        # background tabs so the user can see results without losing context.
        if sum(1 for a in actions if a.get("action") == "new_tab") > 1:
            seen = 0
            for a in actions:
                if a.get("action") == "new_tab":
                    a["_select"] = (seen == 0)
                    seen += 1
        # Run close_tab actions in descending index order so earlier closes
        # don't shift the indices of later ones.
        non_close = [a for a in actions if a.get("action") != "close_tab"]
        closes = [a for a in actions if a.get("action") == "close_tab"]
        closes.sort(key=lambda a: a.get("index", -1), reverse=True)
        ordered = non_close + closes

        # If the agent issued multiple same-tab steps (page_type / navigate /
        # search), space them out so each one is actually visible before the
        # next replaces it. Otherwise they all race and only the last sticks.
        same_tab_kinds = {"page_type", "navigate", "search"}
        same_tab_count = sum(1 for a in ordered if a.get("action") in same_tab_kinds)
        if same_tab_count > 1:
            delay_ms = 0
            for a in ordered:
                if a.get("action") in same_tab_kinds:
                    wx.CallLater(delay_ms, lambda act=a: self._dispatch(act))
                    delay_ms += 2500  # 2.5s between each — enough to see the page
                else:
                    wx.CallLater(delay_ms, lambda act=a: self._dispatch(act))
            return

        for a in ordered:
            self._dispatch(a)

    def _dispatch(self, action: dict):
        kind = action.get("action", "?")
        desc = self.browser._execute_agent_action(action)
        self._append_styled("Agent", f"[{kind}] {desc}", wx.Colour(0x1A, 0x73, 0xE8))

    # ---------- Gemini-style observe → act loop ----------
    MAX_AGENT_STEPS = 8
    MAX_AGENT_STEPS_BATCH = 24  # higher budget for "select all the X and ..." tasks

    @staticmethod
    def _is_batch_goal(goal: str) -> bool:
        low = goal.lower()
        return any(w in low for w in (
            "all the", "all ", "every", "each", "promo", "promotion",
            "newsletter", "select the", "delete the", "trash the",
            "archive the", "unsubscribe", "mark as read",
        ))

    def _run_agentic_loop(self, goal: str):
        self._busy = True
        self._loop_cancel = False
        self._agent_goal = goal
        self._agent_steps = 0
        self._loop_last_sig = None
        self._agent_messages = [{"role": "system", "content": self.SYSTEM_PROMPT}]
        self._append_styled("Agent", f"working on: {goal}", wx.Colour(0x5F, 0x63, 0x68))
        self._agent_step()

    @staticmethod
    def _action_sig(a: dict) -> str:
        kind = (a.get("action") or "").lower()
        # Same control re-filled with different text is NOT a repeat.
        if kind == "fill":
            return f"fill:{a.get('index')}:{a.get('text')}"
        if kind in ("click_element", "select_option", "select_value"):
            return f"{kind}:{a.get('index')}:{a.get('option') or a.get('value') or ''}"
        if kind in ("click",):
            return f"click:{a.get('selector') or a.get('text')}"
        if kind in ("navigate", "new_tab"):
            return f"{kind}:{a.get('url')}"
        if kind == "scroll":
            return f"scroll:{a.get('direction')}"
        return kind

    def cancel_loop(self):
        self._loop_cancel = True
        self._busy = False

    def _format_observation(self, obs: dict) -> str:
        if obs.get("error"):
            return f"[page observation error: {obs['error']}]"
        els = obs.get("elements", [])
        lines = []
        for e in els:
            label = (e.get("label") or "").strip()
            extra = ""
            if e.get("type"):
                extra += f" type={e['type']}"
            if e.get("value"):
                extra += f" value={e['value']!r}"
            if "checked" in e:
                extra += " [CHECKED]" if e["checked"] else " [unchecked]"
            if e.get("options"):
                extra += f" options={e['options']}"
            if e.get("selected"):
                extra += f" selected={e['selected']!r}"
            if e.get("context"):
                extra += f" ctx={e['context']!r}"
            if e.get("inView") is False:
                extra += " (off-screen — scroll to reach)"
            lines.append(f"  #{e.get('i')} {e.get('kind','')}/{e.get('tag','')}: {label!r}{extra}")
        head = (f"[interactive elements on {obs.get('url','')} "
                f"(scroll {obs.get('scrollY')}/{obs.get('scrollMax')}):\n")
        body = "\n".join(lines) if lines else "  (no interactive elements found)"
        return head + body + "\n]"

    def _agent_step(self):
        if getattr(self, "_loop_cancel", False):
            return
        step_cap = (self.MAX_AGENT_STEPS_BATCH
                    if self._is_batch_goal(self._agent_goal) else self.MAX_AGENT_STEPS)
        if self._agent_steps >= step_cap:
            self._append_styled("Agent", "(reached step limit — stopping)",
                                wx.Colour(0x99, 0x99, 0x99))
            self._busy = False
            return
        self._agent_steps += 1
        client = self.browser.minimax
        if client is None:
            self._busy = False
            return

        # Observe the active page (UI thread).
        obs = self.browser.observe_page()
        obs_block = self._format_observation(obs)

        # Tab context.
        active_idx = self.browser.book.GetSelection()
        tabs_lines = []
        for i, w in enumerate(self.browser._webviews):
            tabs_lines.append(f"  {i}: {(w.GetCurrentTitle() or '').strip()!r} @ {(w.GetCurrentURL() or '').strip()}")
        tabs_block = f"[tabs (active: {active_idx}):\n" + "\n".join(tabs_lines) + "\n]"

        user_turn = (
            f"GOAL: {self._agent_goal}\n(step {self._agent_steps}/{self.MAX_AGENT_STEPS})\n\n"
            f"{tabs_block}\n{obs_block}\n"
            "Decide the next action(s) to advance the goal, using index-based "
            "actions (click_element/fill/select_option) against the elements above. "
            "Each element may include ctx='…' = the text of its row/list-item; use "
            "it to pick the RIGHT row's control (e.g. for 'select promotional emails', "
            "click_element the checkbox of each row whose ctx looks like a promo / "
            "newsletter / marketing message, then click the Trash/Delete button). "
            "For selecting MULTIPLE list items you MAY return a JSON ARRAY of "
            "click_element actions in one response. "
            "Do NOT repeat an action the observation shows is already done: a field "
            "with the right value=…, a checkbox already [CHECKED], or a select already "
            "selected=… is COMPLETE — move on. "
            "If a needed control is off-screen or absent, scroll first. "
            'When every part of the goal is satisfied, respond with '
            '{"action":"done","text":"<short summary of what you did>"}.'
        )
        # Keep the conversation bounded: system + last 4 turns.
        self._agent_messages.append({"role": "user", "content": user_turn})
        convo = [self._agent_messages[0]] + self._agent_messages[-4:]

        def worker():
            try:
                raw = client.chat(convo)
            except Exception as e:
                raw = json.dumps({"action": "reply", "text": f"MiniMax error: {e}"})
            wx.CallAfter(self._agent_after_llm, raw)

        threading.Thread(target=worker, daemon=True).start()

    def _agent_after_llm(self, raw: str):
        if getattr(self, "_loop_cancel", False):
            return
        self._agent_messages.append({"role": "assistant", "content": raw})
        acts = self._parse_actions(raw) or [{"action": "reply", "text": raw}]

        # Oscillation guard: if the model repeats the exact same action it just
        # did, the goal is almost certainly already complete — stop cleanly.
        if acts:
            sig = self._action_sig(acts[0])
            if sig and sig == getattr(self, "_loop_last_sig", None) \
                    and acts[0].get("action") not in ("done", "reply"):
                self._append_styled("Agent",
                                    "✓ done (no further progress — the goal looks complete)",
                                    wx.Colour(0x0F, 0x80, 0x0F))
                self._busy = False
                return
            self._loop_last_sig = sig

        terminal = False
        for a in acts:
            kind = (a.get("action") or "").lower()
            if kind in ("done", "reply"):
                self._append_styled("Agent", a.get("text") or "(done)",
                                    wx.Colour(0x0F, 0x80, 0x0F))
                terminal = True
                break
            desc = self.browser._execute_agent_action(a)
            self._append_styled("Agent", f"[{kind}] {desc}", wx.Colour(0x1A, 0x73, 0xE8))
        if terminal:
            self._busy = False
            return
        # Let the page apply the action, then observe again and continue.
        wx.CallLater(1300, self._agent_step)

    def _handle_reply(self, raw: str):
        self._busy = False
        action = self._parse_action(raw)
        if action is None:
            self._append_styled("Agent", raw.strip() or "(empty reply)", wx.Colour(0x20, 0x21, 0x24))
            return
        kind = action.get("action") or "?"
        desc = self.browser._execute_agent_action(action)
        self._append_styled("Agent", f"[{kind}] {desc}", wx.Colour(0x1A, 0x73, 0xE8))

    @staticmethod
    def _parse_action(raw: str):
        """Back-compat: returns a single dict (or None) — for legacy callers."""
        actions = AgentPanel._parse_actions(raw)
        return actions[0] if actions else None

    @staticmethod
    def _parse_actions(raw: str) -> list[dict]:
        """Parse one action OR an array of actions out of model output."""
        s = (raw or "").strip()
        if s.startswith("```"):
            s = s.strip("`")
            s = s.split("\n", 1)[-1] if "\n" in s else s
            s = s.strip()
        # Try the whole string first.
        try:
            obj = json.loads(s)
        except json.JSONDecodeError:
            obj = None
        if obj is None:
            # Fall back to scanning for array or object substrings.
            for opener, closer in (("[", "]"), ("{", "}")):
                i = s.find(opener)
                j = s.rfind(closer)
                if 0 <= i < j:
                    try:
                        obj = json.loads(s[i:j + 1])
                        break
                    except json.JSONDecodeError:
                        continue
        if isinstance(obj, list):
            return [a for a in obj if isinstance(a, dict) and a.get("action")]
        if isinstance(obj, dict) and obj.get("action"):
            return [obj]
        return []


# ---------- Chrome-style tab strip (custom, sits above the URL bar) ----------
TAB_STRIP_HEIGHT = 36
TAB_HEIGHT       = 32
TAB_MIN_WIDTH    = 110
TAB_MAX_WIDTH    = 220
TAB_ACTIVE_BG    = wx.Colour(0xF1, 0xF3, 0xF4)
TAB_HOVER_BG     = wx.Colour(0xE6, 0xE9, 0xEC)


class TabButton(wx.Panel):
    """One Chrome-style tab with title + close X."""

    def __init__(self, parent, index, title, active, on_click, on_close):
        super().__init__(parent)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.index = index
        self.title = title or "New Tab"
        self.active = active
        self.hover = False
        self.close_hover = False
        self._on_click = on_click
        self._on_close = on_close

        self.SetMinSize(wx.Size(TAB_MIN_WIDTH, TAB_HEIGHT))
        self.SetMaxSize(wx.Size(TAB_MAX_WIDTH, TAB_HEIGHT))

        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda e: None)
        self.Bind(wx.EVT_LEFT_DOWN, self._on_left)
        self.Bind(wx.EVT_MIDDLE_DOWN, lambda e: self._on_close(self.index))
        self.Bind(wx.EVT_MOTION, self._on_motion)
        self.Bind(wx.EVT_ENTER_WINDOW, lambda e: (setattr(self, "hover", True), self.Refresh()))
        self.Bind(wx.EVT_LEAVE_WINDOW, lambda e: (setattr(self, "hover", False),
                                                  setattr(self, "close_hover", False),
                                                  self.Refresh()))

    def set_title(self, title: str):
        title = title or "New Tab"
        if title != self.title:
            self.title = title
            self.Refresh()

    def set_active(self, active: bool):
        if self.active != active:
            self.active = active
            self.Refresh()

    def set_index(self, index: int):
        self.index = index

    def _close_rect(self) -> wx.Rect:
        w, h = self.GetClientSize()
        return wx.Rect(w - 22, (h - 16) // 2, 16, 16)

    def _on_left(self, evt):
        if self._close_rect().Contains(evt.GetPosition()):
            self._on_close(self.index)
        else:
            self._on_click(self.index)

    def _on_motion(self, evt):
        new_close = self._close_rect().Contains(evt.GetPosition())
        if new_close != self.close_hover:
            self.close_hover = new_close
            self.Refresh()

    def _on_paint(self, _evt):
        dc = wx.AutoBufferedPaintDC(self)
        w, h = self.GetClientSize()
        bg = TAB_ACTIVE_BG if self.active else (TAB_HOVER_BG if self.hover else CHROME_BG)
        dc.SetBackground(wx.Brush(CHROME_BG))
        dc.Clear()

        gc = wx.GraphicsContext.Create(dc)
        radius = 8.0
        path = gc.CreatePath()
        path.MoveToPoint(0, h)
        path.AddLineToPoint(0, radius)
        path.AddQuadCurveToPoint(0, 0, radius, 0)
        path.AddLineToPoint(w - radius, 0)
        path.AddQuadCurveToPoint(w, 0, w, radius)
        path.AddLineToPoint(w, h)
        path.CloseSubpath()
        gc.SetBrush(wx.Brush(bg))
        gc.SetPen(wx.TRANSPARENT_PEN)
        gc.FillPath(path)

        # Title
        dc.SetTextForeground(OMNIBOX_TEXT if self.active else wx.Colour(0x3C, 0x40, 0x43))
        dc.SetFont(wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL,
                            wx.FONTWEIGHT_BOLD if self.active else wx.FONTWEIGHT_NORMAL))
        text_avail = max(10, w - 36)
        title = self.title
        if dc.GetTextExtent(title)[0] > text_avail:
            while title and dc.GetTextExtent(title + "…")[0] > text_avail:
                title = title[:-1]
            title = title + "…" if title else self.title[:1]
        ty = (h - dc.GetTextExtent(title)[1]) // 2
        dc.DrawText(title, 10, ty)

        # Close X
        cr = self._close_rect()
        show_close = self.active or self.hover
        if show_close:
            if self.close_hover:
                gc.SetBrush(wx.Brush(wx.Colour(0xD2, 0xD4, 0xD8)))
                gc.SetPen(wx.TRANSPARENT_PEN)
                gc.DrawRoundedRectangle(cr.x, cr.y, cr.width, cr.height, 4)
            dc.SetPen(wx.Pen(wx.Colour(0x5F, 0x63, 0x68), 1))
            pad = 4
            dc.DrawLine(cr.x + pad, cr.y + pad, cr.GetRight() - pad, cr.GetBottom() - pad)
            dc.DrawLine(cr.x + pad, cr.GetBottom() - pad, cr.GetRight() - pad, cr.y + pad)


class TabStrip(wx.Panel):
    """Horizontal strip of Chrome-style tabs + a '+' button."""

    def __init__(self, parent, on_select, on_close, on_new):
        super().__init__(parent)
        self.SetBackgroundColour(CHROME_BG)
        self.SetMinSize(wx.Size(-1, TAB_STRIP_HEIGHT))
        self._on_select = on_select
        self._on_close = on_close
        self._on_new = on_new
        self._tabs: list[TabButton] = []

        self.btn_new = wx.Button(self, label="+",
                                 size=wx.Size(28, TAB_HEIGHT - 4),
                                 style=wx.BORDER_NONE | wx.BU_EXACTFIT)
        self.btn_new.SetBackgroundColour(CHROME_BG)
        self.btn_new.SetFont(wx.Font(13, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        self.btn_new.SetToolTip("New tab (Ctrl+T)")
        self.btn_new.Bind(wx.EVT_BUTTON, lambda e: self._on_new())

        self._sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.SetSizer(self._sizer)
        self._relayout()

    def add_tab(self, title: str, active: bool) -> TabButton:
        idx = len(self._tabs)
        tab = TabButton(self, idx, title, active, self._on_select, self._on_close)
        self._tabs.append(tab)
        if active:
            for i, t in enumerate(self._tabs):
                t.set_active(i == idx)
        self._relayout()
        return tab

    def remove_tab(self, idx: int):
        if 0 <= idx < len(self._tabs):
            tab = self._tabs.pop(idx)
            tab.Destroy()
            for i, t in enumerate(self._tabs):
                t.set_index(i)
            self._relayout()

    def set_active(self, idx: int):
        for i, t in enumerate(self._tabs):
            t.set_active(i == idx)

    def set_title(self, idx: int, title: str):
        if 0 <= idx < len(self._tabs):
            self._tabs[idx].set_title(title)

    def _relayout(self):
        self._sizer.Clear()
        for t in self._tabs:
            self._sizer.Add(t, 1, wx.TOP | wx.LEFT, 4)
        self._sizer.Add(self.btn_new, 0, wx.LEFT | wx.TOP, 4)
        self._sizer.AddStretchSpacer()
        self.Layout()
        self.Refresh()


class BookmarkManagerDialog(wx.Dialog):
    """Bookmark manager: list view + open/rename/delete/export/import."""

    def __init__(self, parent, store: "BookmarkStore", on_navigate):
        super().__init__(
            parent,
            title="Bookmark Manager",
            size=(720, 480),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.store = store
        self.on_navigate = on_navigate

        # --- search box ---
        self.search = wx.SearchCtrl(self, style=wx.TE_PROCESS_ENTER)
        self.search.SetDescriptiveText("Filter by title or URL…")
        self.search.Bind(wx.EVT_TEXT, lambda e: self._refresh())

        # --- list ---
        self.list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_HRULES | wx.BORDER_SUNKEN)
        self.list.InsertColumn(0, "Title", width=260)
        self.list.InsertColumn(1, "URL", width=420)
        self.list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, lambda e: self._open_selected())
        self.list.Bind(wx.EVT_LIST_KEY_DOWN, self._on_list_key)

        # --- buttons ---
        btn_open    = wx.Button(self, label="Open")
        btn_rename  = wx.Button(self, label="Rename…")
        btn_delete  = wx.Button(self, label="Delete")
        btn_export  = wx.Button(self, label="Export…")
        btn_import  = wx.Button(self, label="Import…")
        btn_close   = wx.Button(self, wx.ID_CLOSE, label="Close")

        btn_open.Bind(wx.EVT_BUTTON, lambda e: self._open_selected())
        btn_rename.Bind(wx.EVT_BUTTON, lambda e: self._rename_selected())
        btn_delete.Bind(wx.EVT_BUTTON, lambda e: self._delete_selected())
        btn_export.Bind(wx.EVT_BUTTON, lambda e: self._export())
        btn_import.Bind(wx.EVT_BUTTON, lambda e: self._import())
        btn_close.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CLOSE))

        # --- footer label ---
        path_lbl = wx.StaticText(self, label=f"File: {BOOKMARKS_FILE}")
        path_lbl.SetForegroundColour(wx.Colour(0x5F, 0x63, 0x68))

        # --- layout ---
        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        for b in (btn_open, btn_rename, btn_delete):
            btn_row.Add(b, 0, wx.RIGHT, 4)
        btn_row.AddStretchSpacer()
        for b in (btn_import, btn_export, btn_close):
            btn_row.Add(b, 0, wx.LEFT, 4)

        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(self.search, 0, wx.EXPAND | wx.ALL, 8)
        outer.Add(self.list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        outer.Add(btn_row, 0, wx.EXPAND | wx.ALL, 8)
        outer.Add(path_lbl, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        self.SetSizer(outer)

        self._refresh()
        self.Centre()

    # ---- helpers ----
    def _filtered(self) -> list[dict]:
        q = (self.search.GetValue() or "").lower().strip()
        if not q:
            return list(self.store.items)
        return [b for b in self.store.items
                if q in b.get("title", "").lower() or q in b.get("url", "").lower()]

    def _refresh(self):
        self.list.DeleteAllItems()
        for b in self._filtered():
            i = self.list.InsertItem(self.list.GetItemCount(), b.get("title", ""))
            self.list.SetItem(i, 1, b.get("url", ""))

    def _selected_indices(self) -> list[int]:
        out = []
        i = self.list.GetFirstSelected()
        while i != -1:
            out.append(i)
            i = self.list.GetNextSelected(i)
        return out

    def _selected_bookmarks(self) -> list[dict]:
        flt = self._filtered()
        return [flt[i] for i in self._selected_indices() if 0 <= i < len(flt)]

    def _on_list_key(self, evt: wx.ListEvent):
        kc = evt.GetKeyCode()
        if kc == wx.WXK_DELETE:
            self._delete_selected()
        elif kc == wx.WXK_F2:
            self._rename_selected()
        else:
            evt.Skip()

    # ---- actions ----
    def _open_selected(self):
        items = self._selected_bookmarks()
        if not items:
            return
        self.EndModal(wx.ID_OK)
        for b in items:
            self.on_navigate(b["url"])

    def _rename_selected(self):
        items = self._selected_bookmarks()
        if len(items) != 1:
            return
        b = items[0]
        dlg = wx.TextEntryDialog(self, "New name:", "Rename bookmark", b["title"])
        if dlg.ShowModal() == wx.ID_OK:
            self.store.rename(b["url"], dlg.GetValue() or b["title"])
            self._refresh()
        dlg.Destroy()

    def _delete_selected(self):
        items = self._selected_bookmarks()
        if not items:
            return
        msg = (f"Delete '{items[0]['title']}'?" if len(items) == 1
               else f"Delete {len(items)} bookmarks?")
        if wx.MessageBox(msg, "Confirm delete", wx.YES_NO | wx.ICON_QUESTION, self) != wx.YES:
            return
        for b in items:
            self.store.remove(b["url"])
        self._refresh()

    def _export(self):
        with wx.FileDialog(
            self, "Export bookmarks",
            wildcard="JSON file (*.json)|*.json|Netscape HTML bookmarks (*.html)|*.html",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
            defaultFile="bookmarks.json",
        ) as fd:
            if fd.ShowModal() != wx.ID_OK:
                return
            path = Path(fd.GetPath())
            try:
                if path.suffix.lower() == ".html":
                    path.write_text(self._to_netscape_html(), encoding="utf-8")
                else:
                    path.write_text(
                        json.dumps(self.store.items, indent=2, ensure_ascii=False),
                        encoding="utf-8",
                    )
                wx.MessageBox(f"Exported {len(self.store.items)} bookmarks to:\n{path}",
                              "Export complete", wx.OK | wx.ICON_INFORMATION, self)
            except Exception as e:
                wx.MessageBox(f"Export failed:\n{e}", "Error", wx.OK | wx.ICON_ERROR, self)

    def _import(self):
        with wx.FileDialog(
            self, "Import bookmarks",
            wildcard="Bookmark files (*.json;*.html)|*.json;*.html|All files (*.*)|*.*",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        ) as fd:
            if fd.ShowModal() != wx.ID_OK:
                return
            path = Path(fd.GetPath())
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
                imported = self._parse_import(text, path.suffix.lower())
                added = 0
                for b in imported:
                    if b.get("url") and not self.store.has(b["url"]):
                        self.store.items.append({
                            "title": (b.get("title") or b["url"]).strip()[:80],
                            "url": b["url"],
                        })
                        added += 1
                self.store.save()
                self._refresh()
                wx.MessageBox(f"Imported {added} new bookmarks (skipped {len(imported) - added} duplicates).",
                              "Import complete", wx.OK | wx.ICON_INFORMATION, self)
            except Exception as e:
                wx.MessageBox(f"Import failed:\n{e}", "Error", wx.OK | wx.ICON_ERROR, self)

    def _parse_import(self, text: str, suffix: str) -> list[dict]:
        if suffix == ".json":
            data = json.loads(text)
            if isinstance(data, list):
                return [b for b in data if isinstance(b, dict) and b.get("url")]
            return []
        # Netscape HTML bookmarks (Chrome/Firefox export format)
        import re
        out = []
        for m in re.finditer(r'<A\s+HREF="([^"]+)"[^>]*>(.*?)</A>', text, flags=re.IGNORECASE | re.DOTALL):
            url = m.group(1).strip()
            title = re.sub(r"<[^>]+>", "", m.group(2)).strip()
            out.append({"title": title or url, "url": url})
        return out

    def _to_netscape_html(self) -> str:
        # Format readable by Chrome/Firefox import.
        lines = [
            "<!DOCTYPE NETSCAPE-Bookmark-file-1>",
            "<META HTTP-EQUIV=\"Content-Type\" CONTENT=\"text/html; charset=UTF-8\">",
            "<TITLE>Bookmarks</TITLE>",
            "<H1>Bookmarks</H1>",
            "<DL><p>",
        ]
        for b in self.store.items:
            title = (b.get("title") or "").replace("<", "&lt;").replace(">", "&gt;")
            url = (b.get("url") or "").replace('"', "&quot;")
            lines.append(f'    <DT><A HREF="{url}">{title}</A>')
        lines.append("</DL><p>")
        return "\n".join(lines)


class Browser(wx.Frame):
    def __init__(self):
        super().__init__(None, title="Anti-Trace Browser", size=(1280, 860))
        self.SetBackgroundColour(CHROME_BG)

        # Set frame icon
        logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "globe_logo_v3.ico")
        if not os.path.exists(logo_path):
            logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "globe_logo.ico")
        if not os.path.exists(logo_path):
            logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo.ico")
        if os.path.exists(logo_path):
            self.SetIcon(wx.Icon(logo_path, wx.BITMAP_TYPE_ICO))

        self.bookmarks = BookmarkStore()

        # MiniMax (optional). Loaded from env var or %APPDATA% key file.
        self.minimax: MinimaxClient | None = None
        _mk = _load_minimax_key()
        if _mk:
            region = os.environ.get("MINIMAX_REGION", "global")
            model  = os.environ.get("MINIMAX_MODEL", MINIMAX_DEFAULT_MODEL)
            self.minimax = MinimaxClient(_mk, region=region, model=model)

        # Custom tab strip — sits ABOVE the URL bar like real Chrome.
        self.tab_strip = TabStrip(
            self,
            on_select=self._on_tab_select,
            on_close=self._on_tab_close_btn,
            on_new=lambda: self.add_new_tab(HOME_URL, select=True),
        )

        self._build_toolbar()

        # Bookmarks bar lives between toolbar and content.
        self.bm_bar = BookmarksBar(self, self.bookmarks, self._navigate_active)

        # Content area = splitter [book | Gemini sidepanel].
        self.content_split = wx.SplitterWindow(self, style=wx.SP_LIVE_UPDATE | wx.SP_3DSASH)
        self.content_split.SetMinimumPaneSize(280)
        self.book = wx.Simplebook(self.content_split)
        self._webviews: list[wx.html2.WebView] = []
        self._assistant_panel: wx.Panel | None = None
        self._assistant_view: wx.html2.WebView | None = None
        self.content_split.Initialize(self.book)  # single pane until Gemini is toggled on

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.tab_strip, 0, wx.EXPAND)
        sizer.Add(self.toolbar, 0, wx.EXPAND)
        sizer.Add(self.bm_bar, 0, wx.EXPAND)
        sizer.Add(self.content_split, 1, wx.EXPAND)
        self.SetSizer(sizer)
        self._main_sizer = sizer

        self.CreateStatusBar()
        self.GetStatusBar().SetStatusText("Ready — every session leaves no trace")

        # Global accelerators (Chrome-style)
        ID_FIND = wx.NewIdRef()
        ID_FULLSCREEN = wx.NewIdRef()
        ID_FOCUS_OMNI = wx.NewIdRef()
        ID_QUIT = wx.NewIdRef()
        accel = wx.AcceleratorTable([
            (wx.ACCEL_CTRL,                    ord('L'),       ID_GO),
            (wx.ACCEL_NORMAL,                  wx.WXK_F6,      ID_GO),
            (wx.ACCEL_CTRL,                    ord('K'),       ID_FOCUS_OMNI),
            (wx.ACCEL_CTRL,                    ord('E'),       ID_FOCUS_OMNI),
            (wx.ACCEL_ALT,                     wx.WXK_LEFT,    ID_BACK),
            (wx.ACCEL_ALT,                     wx.WXK_RIGHT,   ID_FWD),
            (wx.ACCEL_CTRL,                    ord('R'),       ID_RELOAD),
            (wx.ACCEL_NORMAL,                  wx.WXK_F5,      ID_RELOAD),
            (wx.ACCEL_NORMAL,                  wx.WXK_ESCAPE,  ID_STOP),
            (wx.ACCEL_ALT,                     wx.WXK_HOME,    ID_HOME),
            (wx.ACCEL_CTRL | wx.ACCEL_SHIFT,   ord('W'),       ID_WIPE),
            (wx.ACCEL_CTRL,                    ord('F'),       ID_FIND),
            (wx.ACCEL_NORMAL,                  wx.WXK_F11,     ID_FULLSCREEN),
            (wx.ACCEL_CTRL,                    ord('Q'),       ID_QUIT),
            (wx.ACCEL_CTRL,                    ord('T'),       ID_NEW_TAB),
            (wx.ACCEL_CTRL,                    ord('W'),       ID_CLOSE_TAB),
            (wx.ACCEL_CTRL,                    ord('D'),       ID_STAR),
            (wx.ACCEL_CTRL | wx.ACCEL_SHIFT,   ord('B'),       ID_TOGGLE_BMBAR),
            (wx.ACCEL_CTRL | wx.ACCEL_SHIFT,   ord('O'),       ID_BM_MGR),
            (wx.ACCEL_CTRL,                    ord('G'),       ID_GEMINI),
        ])
        self.SetAcceleratorTable(accel)
        self.Bind(wx.EVT_MENU, lambda e: self._find_in_page(), id=ID_FIND)
        self.Bind(wx.EVT_MENU, lambda e: self._toggle_fullscreen(), id=ID_FULLSCREEN)
        self.Bind(wx.EVT_MENU, lambda e: self.address.SetFocusOnText(), id=ID_FOCUS_OMNI)
        self.Bind(wx.EVT_MENU, lambda e: self.Close(), id=ID_QUIT)

        self.Bind(wx.EVT_MENU, lambda e: self.get_active_webview().GoBack() if (self.get_active_webview() and self.get_active_webview().CanGoBack()) else None, id=ID_BACK)
        self.Bind(wx.EVT_MENU, lambda e: self.get_active_webview().GoForward() if (self.get_active_webview() and self.get_active_webview().CanGoForward()) else None, id=ID_FWD)
        self.Bind(wx.EVT_MENU, lambda e: self.get_active_webview().Reload() if self.get_active_webview() else None, id=ID_RELOAD)
        self.Bind(wx.EVT_MENU, lambda e: self.get_active_webview().Stop() if self.get_active_webview() else None, id=ID_STOP)
        self.Bind(wx.EVT_MENU, lambda e: self.get_active_webview().LoadURL(HOME_URL) if self.get_active_webview() else None, id=ID_HOME)
        self.Bind(wx.EVT_MENU, lambda e: self.address.SetFocusOnText(), id=ID_GO)
        self.Bind(wx.EVT_MENU, self._on_wipe, id=ID_WIPE)
        self.Bind(wx.EVT_MENU, lambda e: self.add_new_tab(HOME_URL, select=True), id=ID_NEW_TAB)
        self.Bind(wx.EVT_MENU, self._on_close_tab_menu, id=ID_CLOSE_TAB)
        self.Bind(wx.EVT_MENU, lambda e: self._toggle_bookmark(), id=ID_STAR)
        self.Bind(wx.EVT_MENU, lambda e: self._toggle_bookmarks_bar(), id=ID_TOGGLE_BMBAR)
        self.Bind(wx.EVT_MENU, lambda e: self._open_bookmark_manager(), id=ID_BM_MGR)
        self.Bind(wx.EVT_MENU, lambda e: self._toggle_assistant(), id=ID_GEMINI)

        # Open initial tab
        self.add_new_tab(HOME_URL, select=True)

        # Position and size dynamically within the usable desktop working area (excludes taskbar)
        client_rect = wx.GetClientDisplayRect()
        screen_w, screen_h = client_rect.GetWidth(), client_rect.GetHeight()

        # Target a comfortable size: max 1280x860, but scale down if the screen is smaller
        w = min(1280, int(screen_w * 0.9))
        h = min(860, int(screen_h * 0.9))
        self.SetSize(wx.Size(w, h))

        # Center horizontally, and position vertically with at least a 20px padding from the top edge
        x = client_rect.GetLeft() + (screen_w - w) // 2
        y = max(client_rect.GetTop() + 20, client_rect.GetTop() + (screen_h - h) // 2)
        self.SetPosition(wx.Point(x, y))

    # ---------- toolbar (Chrome-style) ----------
    def _build_toolbar(self):
        # A plain panel acts as the chrome bar so we can fully control colors.
        bar = wx.Panel(self)
        bar.SetBackgroundColour(CHROME_BG)
        self.toolbar = bar

        def round_btn(label_id, glyph, tooltip):
            b = wx.Button(bar, id=label_id, label=glyph, size=wx.Size(36, 36),
                          style=wx.BORDER_NONE | wx.BU_EXACTFIT)
            b.SetBackgroundColour(CHROME_BG)
            b.SetForegroundColour(wx.Colour(0x20, 0x21, 0x24))
            b.SetFont(wx.Font(13, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
            b.SetToolTip(tooltip)
            return b

        # Use Unicode glyphs so we don't drag in icon assets.
        self.btn_back   = round_btn(ID_BACK,   "←", "Go back (Alt+Left)")
        self.btn_fwd    = round_btn(ID_FWD,    "→", "Go forward (Alt+Right)")
        self.btn_reload = round_btn(ID_RELOAD, "↻", "Reload page (Ctrl+R)")
        self.btn_home   = round_btn(ID_HOME,   "⌂", "Open home page (Alt+Home)")
        self.btn_new_tab = round_btn(ID_NEW_TAB, "+", "New tab (Ctrl+T)")
        self.btn_star   = round_btn(ID_STAR, "☆", "Bookmark this page (Ctrl+D)")
        self.btn_bm_mgr = round_btn(ID_BM_MGR, "📚", "Bookmark manager (Ctrl+Shift+O)")
        self.btn_gemini = round_btn(ID_GEMINI, "✨", "Toggle AI side panel (Ctrl+G)")
        self.btn_wipe   = wx.Button(bar, id=ID_WIPE, label="Wipe", size=wx.Size(64, 32),
                                    style=wx.BORDER_NONE)
        self.btn_wipe.SetBackgroundColour(wx.Colour(0xC0, 0x39, 0x2B))
        self.btn_wipe.SetForegroundColour(wx.WHITE)
        self.btn_wipe.SetFont(wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        self.btn_wipe.SetToolTip("Erase cookies, cache and history (Ctrl+Shift+W)")

        self.address = Omnibox(bar, on_submit=self._on_omnibox_submit)

        # Layout: [back][fwd][reload][home][new_tab]  [== omnibox ==] [star] [wipe]
        sizer = wx.BoxSizer(wx.HORIZONTAL)
        sizer.AddSpacer(6)
        for b in (self.btn_back, self.btn_fwd, self.btn_reload, self.btn_home, self.btn_new_tab):
            sizer.Add(b, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 2)
        sizer.AddSpacer(8)
        sizer.Add(self.address, 1, wx.ALIGN_CENTER_VERTICAL | wx.TOP | wx.BOTTOM, 7)
        sizer.AddSpacer(4)
        sizer.Add(self.btn_star, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 2)
        sizer.Add(self.btn_bm_mgr, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 2)
        sizer.Add(self.btn_gemini, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        sizer.Add(self.btn_wipe, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        bar.SetSizer(sizer)
        bar.SetMinSize(wx.Size(-1, 48))

        # Button bindings.
        self.btn_back.Bind(wx.EVT_BUTTON, lambda e: self.get_active_webview().GoBack() if (self.get_active_webview() and self.get_active_webview().CanGoBack()) else None)
        self.btn_fwd.Bind(wx.EVT_BUTTON, lambda e: self.get_active_webview().GoForward() if (self.get_active_webview() and self.get_active_webview().CanGoForward()) else None)
        self.btn_reload.Bind(wx.EVT_BUTTON, lambda e: self.get_active_webview().Reload() if self.get_active_webview() else None)
        self.btn_home.Bind(wx.EVT_BUTTON, lambda e: self.get_active_webview().LoadURL(HOME_URL) if self.get_active_webview() else None)
        self.btn_new_tab.Bind(wx.EVT_BUTTON, lambda e: self.add_new_tab(HOME_URL, select=True))
        self.btn_star.Bind(wx.EVT_BUTTON, lambda e: self._toggle_bookmark())
        self.btn_bm_mgr.Bind(wx.EVT_BUTTON, lambda e: self._open_bookmark_manager())
        self.btn_gemini.Bind(wx.EVT_BUTTON, lambda e: self._toggle_assistant())
        self.btn_wipe.Bind(wx.EVT_BUTTON, self._on_wipe)

    # ---------- API / Helper Methods ----------
    def add_new_tab(self, url: str = HOME_URL, select: bool = True) -> wx.html2.WebView:
        webview = wx.html2.WebView.New(
            self.book,
            backend=wx.html2.WebViewBackendEdge,
            url=url,
        )
        webview.SetUserAgent(GENERIC_USER_AGENT)

        webview.Bind(wx.html2.EVT_WEBVIEW_NAVIGATED, self._on_navigated)
        webview.Bind(wx.html2.EVT_WEBVIEW_LOADED, self._on_loaded)
        webview.Bind(wx.html2.EVT_WEBVIEW_TITLE_CHANGED, self._on_title)
        webview.Bind(wx.html2.EVT_WEBVIEW_FULLSCREEN_CHANGED, self._on_fullscreen)
        webview.Bind(wx.html2.EVT_WEBVIEW_NEWWINDOW, self._on_new_window)

        self.book.AddPage(webview, "")
        self._webviews.append(webview)
        new_idx = len(self._webviews) - 1
        self.tab_strip.add_tab("New Tab", active=select)
        if select:
            self._select_tab(new_idx)
        return webview

    def get_active_webview(self):
        if not getattr(self, "_webviews", None):
            return None
        idx = self.book.GetSelection()
        if 0 <= idx < len(self._webviews):
            return self._webviews[idx]
        return None

    def _index_of(self, webview) -> int:
        try:
            return self._webviews.index(webview)
        except (ValueError, AttributeError):
            return -1

    def _select_tab(self, idx: int):
        if not (0 <= idx < len(self._webviews)):
            return
        self.book.SetSelection(idx)
        self.tab_strip.set_active(idx)
        wv = self._webviews[idx]
        self.address.SetValue(wv.GetCurrentURL() or "")
        self._update_nav_state()
        title = wv.GetCurrentTitle()
        self.SetTitle(f"{title} — Anti-Trace Browser" if title else "Anti-Trace Browser")

    # ---------- tab events ----------
    def _on_tab_select(self, idx: int):
        self._select_tab(idx)

    def _on_tab_close_btn(self, idx: int):
        self._close_tab(idx)

    def _close_tab(self, idx: int):
        if not (0 <= idx < len(self._webviews)):
            return
        # If it's the last tab, just reset it to home instead of removing.
        if len(self._webviews) == 1:
            self._webviews[0].LoadURL(HOME_URL)
            return
        was_active = (self.book.GetSelection() == idx)
        # Remove page from book (does not destroy the page widget).
        self.book.RemovePage(idx)
        wv = self._webviews.pop(idx)
        wv.Destroy()
        self.tab_strip.remove_tab(idx)
        if was_active:
            new_idx = min(idx, len(self._webviews) - 1)
            self._select_tab(new_idx)
        else:
            # Keep selection consistent with possibly-shifted indices.
            self.tab_strip.set_active(self.book.GetSelection())

    def _on_close_tab_menu(self, _evt):
        idx = self.book.GetSelection()
        if idx != wx.NOT_FOUND:
            self._close_tab(idx)

    # ---------- events ----------
    def _on_omnibox_submit(self, text: str):
        webview = self.get_active_webview()
        if webview:
            webview.LoadURL(resolve(text))

    def _on_navigated(self, evt: wx.html2.WebViewEvent):
        webview = evt.GetEventObject()
        idx = self._index_of(webview)
        if idx >= 0:
            url = evt.GetURL()
            if not webview.GetCurrentTitle():
                domain = url.split("://", 1)[-1].split("/", 1)[0]
                self.tab_strip.set_title(idx, domain[:30] or "New Tab")
        if webview == self.get_active_webview():
            self.address.SetValue(evt.GetURL())
            self._update_nav_state()

    def _on_loaded(self, evt: wx.html2.WebViewEvent):
        webview = evt.GetEventObject()
        if webview == self.get_active_webview():
            self.GetStatusBar().SetStatusText("Done", 0)
            self._update_nav_state()

    def _on_title(self, evt: wx.html2.WebViewEvent):
        webview = evt.GetEventObject()
        title = evt.GetString()
        idx = self._index_of(webview)
        if idx >= 0 and title:
            self.tab_strip.set_title(idx, title[:60])
        if webview == self.get_active_webview() and title:
            self.SetTitle(f"{title} — Anti-Trace Browser")

    def _on_new_window(self, evt: wx.html2.WebViewEvent):
        """window.open() / target=_blank — open in a new tab instead of being dropped."""
        url = evt.GetURL()
        if url:
            self.add_new_tab(url, select=True)
        # Don't call evt.Skip(); we've consumed the request.

    def _on_fullscreen(self, evt: wx.html2.WebViewEvent):
        webview = evt.GetEventObject()
        if webview == self.get_active_webview():
            entering = bool(evt.GetInt())
            if entering:
                self.toolbar.Hide()
                self.GetStatusBar().Hide()
                self.ShowFullScreen(True)
            else:
                self.ShowFullScreen(False)
                self.toolbar.Show()
                self.GetStatusBar().Show()
            self.Layout()

    # ---------- OS-level trusted click (bypasses isTrusted gate) ----------
    _LOCATE_JS = r"""
    (function(sel, txt){
      function isVisible(el){
        if (!el) return false;
        var r = el.getBoundingClientRect();
        if (r.width <= 1 || r.height <= 1) return false;
        var cs = window.getComputedStyle(el);
        return cs.display !== 'none' && cs.visibility !== 'hidden' && parseFloat(cs.opacity||'1') > 0.05;
      }
      function findEl(){
        if (sel) {
          try {
            var all = document.querySelectorAll(sel);
            for (var i = 0; i < all.length; i++) if (isVisible(all[i])) return all[i];
          } catch(_) {}
        }
        if (txt) {
          var needle = String(txt).toLowerCase().trim();
          var cands = document.querySelectorAll('button, a, [role="button"]');
          for (var i = 0; i < cands.length; i++) {
            var t = (cands[i].innerText || cands[i].getAttribute('aria-label') || '').toLowerCase().trim();
            if (isVisible(cands[i]) && t.indexOf(needle) !== -1) return cands[i];
          }
        }
        return null;
      }
      var el = findEl();
      if (!el) return JSON.stringify({found:false});
      try { el.scrollIntoView({block:'center'}); } catch(_){}
      var r = el.getBoundingClientRect();
      return JSON.stringify({found:true, x: r.left + r.width/2, y: r.top + r.height/2});
    })(%s, %s);
    """

    def cancel_pending_polls(self) -> int:
        """Mark every in-flight polling job as cancelled. Returns count."""
        if not hasattr(self, "_pending_polls"):
            self._pending_polls = []
        count = sum(1 for t in self._pending_polls if not t.get("cancelled"))
        for t in self._pending_polls:
            t["cancelled"] = True
        self._pending_polls = []
        return count

    def _poll_then_os_click(self, webview, sel, txt, wait_ms: int):
        """Poll the page (every 400ms) for the element, then issue an
        OS-level mouse click at its screen coordinates so the event is
        actually trusted. Only one poll runs at a time — firing again
        cancels the previous job."""
        import time
        if not hasattr(self, "_pending_polls"):
            self._pending_polls = []
        # Cancel any earlier polls — one trusted click at a time.
        cancelled = self.cancel_pending_polls()
        if cancelled:
            self._agent_log(f"(cancelled {cancelled} earlier trusted-click job{'s' if cancelled != 1 else ''})",
                            wx.Colour(0x99, 0x99, 0x99))

        token = {"cancelled": False, "label": (sel or txt or "")[:40]}
        self._pending_polls.append(token)
        deadline = time.time() + (wait_ms / 1000.0)
        start = time.time()

        def tick():
            if token["cancelled"]:
                return
            if time.time() > deadline:
                msg = f"⚠ trusted-click timed out — no match for {(sel or txt)!r} within {wait_ms}ms"
                self.GetStatusBar().SetStatusText(msg, 0)
                self._agent_log(msg, wx.Colour(0xC0, 0x39, 0x2B))
                token["cancelled"] = True
                return
            js = self._LOCATE_JS % (
                json.dumps(sel) if sel else "null",
                json.dumps(txt) if txt else "null",
            )
            try:
                ok, raw = webview.RunScript(js)
                data = json.loads(raw) if raw else {}
            except Exception:
                data = {}
            if data.get("found"):
                wv_screen = webview.ClientToScreen(wx.Point(0, 0))
                sx = int(wv_screen.x + data["x"])
                sy = int(wv_screen.y + data["y"])
                self._do_os_click(sx, sy)
                elapsed = int((time.time() - start) * 1000)
                msg = f"✓ trusted-click executed at ({sx},{sy}) after {elapsed}ms"
                self.GetStatusBar().SetStatusText(msg, 0)
                self._agent_log(msg, wx.Colour(0x0F, 0x80, 0x0F))
                token["cancelled"] = True
                return
            wx.CallLater(400, tick)

        wx.CallLater(50, tick)

    # Persistent skip-ad guard — polls indefinitely for YouTube skip buttons
    # across all ads in a video (pre-roll, mid-roll, etc.).
    _AUTOSKIP_SELECTORS = (
        "button.ytp-ad-skip-button-modern, "
        ".ytp-ad-skip-button-modern, "
        "button.ytp-skip-ad-button, "
        ".ytp-skip-ad-button, "
        "button.ytp-ad-skip-button, "
        ".ytp-ad-skip-button, "
        ".ytp-ad-skip-button-container button, "
        ".videoAdUiSkipButton, "
        "#skip-button button, "
        "[id*='skip-button'] button, "
        "button[class*='skip-ad-button'], "
        "button[class*='ytp-ad-skip']"
    )

    def _start_auto_skip(self):
        """Long-running poll: keeps clicking every skip button that appears
        on the *currently active* tab until cancelled."""
        import time
        if not hasattr(self, "_pending_polls"):
            self._pending_polls = []
        self.cancel_pending_polls()
        token = {"cancelled": False, "label": "auto-skip"}
        self._pending_polls.append(token)
        last_click_at = [0.0]
        click_count = [0]
        sel_json = json.dumps(self._AUTOSKIP_SELECTORS)

        def tick():
            if token["cancelled"]:
                return
            wv = self.get_active_webview()  # follow whichever tab is active
            if wv is None:
                wx.CallLater(800, tick)
                return
            try:
                js = self._LOCATE_JS % (sel_json, "null")
                ok, raw = wv.RunScript(js)
                data = json.loads(raw) if raw else {}
            except Exception:
                data = {}
            # Cooldown: don't click again within 2.5s of a previous click
            # (button can linger briefly before being removed).
            if data.get("found") and (time.time() - last_click_at[0]) > 2.5:
                wv_screen = wv.ClientToScreen(wx.Point(0, 0))
                sx = int(wv_screen.x + data["x"])
                sy = int(wv_screen.y + data["y"])
                self._do_os_click(sx, sy)
                last_click_at[0] = time.time()
                click_count[0] += 1
                msg = f"✓ auto-skip #{click_count[0]} clicked at ({sx},{sy})"
                self.GetStatusBar().SetStatusText(msg, 0)
                self._agent_log(msg, wx.Colour(0x0F, 0x80, 0x0F))
            wx.CallLater(600, tick)

        self.GetStatusBar().SetStatusText("🔄 auto-skip active — say 'stop' to disable", 0)
        self._agent_log("🔄 auto-skip armed — will keep watching this tab for skip buttons",
                        wx.Colour(0x1A, 0x73, 0xE8))
        wx.CallLater(50, tick)

    def _agent_log(self, msg: str, color):
        """Append a status line to the Duck Agent transcript if it's open."""
        panel = getattr(self, "_assistant_panel", None)
        if panel is not None and isinstance(panel, AgentPanel):
            wx.CallAfter(panel._append_styled, "Agent", msg, color)

    def _do_os_click(self, sx: int, sy: int):
        """Move the OS cursor to (sx, sy) and click. Restores cursor after."""
        try:
            sim = wx.UIActionSimulator()
        except Exception as e:
            self.GetStatusBar().SetStatusText(f"UIActionSimulator unavailable: {e}", 0)
            return
        orig = wx.GetMousePosition()
        # Move + click + restore. Small delays so Windows processes them in order.
        sim.MouseMove(sx, sy)
        wx.MilliSleep(40)
        sim.MouseDown(wx.MOUSE_BTN_LEFT)
        wx.MilliSleep(40)
        sim.MouseUp(wx.MOUSE_BTN_LEFT)
        wx.MilliSleep(80)
        sim.MouseMove(orig.x, orig.y)

    def _on_wipe(self, _evt):
        # Best-effort multi-layer wipe.
        # 1) Close all tabs except the first one.
        while len(self._webviews) > 1:
            self._close_tab(len(self._webviews) - 1)
            
        webview = self.get_active_webview()
        if not webview:
            return
            
        # 2) JS-side: clear all reachable storage for current origin.
        webview.RunScript("""
            try{localStorage.clear()}catch(e){}
            try{sessionStorage.clear()}catch(e){}
            try{document.cookie.split(';').forEach(c=>{
              var n=c.split('=')[0].trim(); if(!n) return;
              ['/',location.pathname].forEach(p=>{
                document.cookie=n+'=; expires=Thu,01 Jan 1970 00:00:00 GMT; path='+p;
                document.cookie=n+'=; expires=Thu,01 Jan 1970 00:00:00 GMT; path='+p+'; domain='+location.hostname;
              });
            });}catch(e){}
            try{caches&&caches.keys().then(ks=>ks.forEach(k=>caches.delete(k)))}catch(e){}
            try{indexedDB&&indexedDB.databases&&indexedDB.databases().then(ds=>ds.forEach(d=>d&&d.name&&indexedDB.deleteDatabase(d.name)))}catch(e){}
        """)
        # 3) WebView2-side: ClearBrowsingData if exposed. wx 4.2.5 has ClearAllBrowsingData.
        try:
            webview.ClearAllBrowsingData()
        except AttributeError:
            pass
        # 4) Reset remaining tab to home.
        webview.LoadURL(HOME_URL)
        self.GetStatusBar().SetStatusText("Session wiped — cookies, cache, storage cleared. Active tabs reset.", 0)

    def _update_nav_state(self):
        webview = self.get_active_webview()
        if webview:
            self.btn_back.Enable(webview.CanGoBack())
            self.btn_fwd.Enable(webview.CanGoForward())
            url = webview.GetCurrentURL() or ""
            self._refresh_star(url)
        else:
            self.btn_back.Enable(False)
            self.btn_fwd.Enable(False)

    # ---------- bookmarks ----------
    def _navigate_active(self, url: str):
        webview = self.get_active_webview() or self.add_new_tab(url, select=True)
        webview.LoadURL(url)

    def _refresh_star(self, url: str):
        is_marked = bool(url) and self.bookmarks.has(url)
        self.btn_star.SetLabel("★" if is_marked else "☆")
        self.btn_star.SetForegroundColour(
            wx.Colour(0xF5, 0xB6, 0x00) if is_marked else wx.Colour(0x20, 0x21, 0x24)
        )
        self.btn_star.SetToolTip(
            "Remove bookmark (Ctrl+D)" if is_marked else "Bookmark this page (Ctrl+D)"
        )
        self.btn_star.Refresh()

    def _toggle_bookmark(self):
        webview = self.get_active_webview()
        if not webview:
            return
        url = webview.GetCurrentURL() or ""
        if not url or url.startswith(("about:", "data:")):
            self.GetStatusBar().SetStatusText("Nothing to bookmark on this page.", 0)
            return
        if self.bookmarks.has(url):
            self.bookmarks.remove(url)
            self.GetStatusBar().SetStatusText("Bookmark removed.", 0)
        else:
            title = webview.GetCurrentTitle() or url
            self.bookmarks.add(url, title)
            self.GetStatusBar().SetStatusText(f"Bookmarked: {title}", 0)
        self.bm_bar.rebuild()
        self._refresh_star(url)

    def _open_bookmark_manager(self):
        dlg = BookmarkManagerDialog(self, self.bookmarks, self._navigate_active)
        dlg.ShowModal()
        dlg.Destroy()
        self.bm_bar.rebuild()
        wv = self.get_active_webview()
        if wv:
            self._refresh_star(wv.GetCurrentURL() or "")

    # ---------- AI side panel (agent or chat) ----------
    def _execute_agent_action(self, action: dict) -> str:
        kind = (action.get("action") or "").lower()
        if kind == "cancel":
            n = self.cancel_pending_polls()
            panel = getattr(self, "_assistant_panel", None)
            if isinstance(panel, AgentPanel):
                panel.cancel_loop()
            return f"cancelled {n} pending polling job(s) + any agent loop"
        if kind == "auto_skip":
            self._start_auto_skip()
            return "🔄 auto-skip armed — will click every YouTube skip button (say 'stop' to disable)"
        if kind == "home":
            wv = self.get_active_webview() or self.add_new_tab(HOME_URL, select=True)
            wv.LoadURL(HOME_URL)
            return "went home"
        if kind == "back":
            wv = self.get_active_webview()
            if wv and wv.CanGoBack(): wv.GoBack(); return "went back"
            return "nothing to go back to"
        if kind == "forward":
            wv = self.get_active_webview()
            if wv and wv.CanGoForward(): wv.GoForward(); return "went forward"
            return "nothing to go forward to"
        if kind == "wipe":
            self._on_wipe(None)
            return "wiped session"
        if kind == "navigate":
            url = (action.get("url") or "").strip()
            if not url:
                return "no url given"
            if "://" not in url:
                url = "https://" + url
            wv = self.get_active_webview() or self.add_new_tab(url, select=True)
            wv.LoadURL(url)
            return f"loaded {url}"
        if kind == "new_tab":
            url = (action.get("url") or HOME_URL).strip()
            if "://" not in url:
                url = "https://" + url
            select = action.get("_select", True)
            self.add_new_tab(url, select=select)
            return f"opened {'(focused)' if select else '(background)'} new tab → {url}"
        if kind == "search":
            q = (action.get("query") or "").strip()
            if not q:
                return "no query given"
            wv = self.get_active_webview() or self.add_new_tab(HOME_URL, select=True)
            wv.LoadURL(SEARCH_URL.format(q=quote_plus(q)))
            return f"searched DuckDuckGo for: {q}"
        if kind == "close_tab":
            idx = action.get("index")
            if idx is None:
                idx = self.book.GetSelection()
            if not isinstance(idx, int) or not (0 <= idx < len(self._webviews)):
                return f"no tab at index {idx}"
            label = (self._webviews[idx].GetCurrentTitle() or
                     self._webviews[idx].GetCurrentURL() or f"tab {idx}")
            self._close_tab(idx)
            return f"closed tab {idx}: {label[:60]}"
        if kind == "select_tab":
            idx = action.get("index")
            if isinstance(idx, int) and 0 <= idx < len(self._webviews):
                self._select_tab(idx)
                return f"switched to tab {idx}"
            return f"no tab at index {idx}"
        if kind == "click":
            wv = self.get_active_webview()
            if not wv:
                return "no active tab"
            sel = action.get("selector")
            txt = action.get("text")
            if not sel and not txt:
                return "click needs selector or text"
            wait_ms = action.get("wait_ms")
            if not isinstance(wait_ms, int) or wait_ms < 0:
                wait_ms = 8000  # default: poll up to 8s so late-appearing elements work
            # YouTube's player checks event.isTrusted on the skip-ad button and
            # rejects synthetic clicks. When trusted=True, fall back to OS-level
            # mouse input via wx.UIActionSimulator (real input events).
            if action.get("trusted"):
                self._poll_then_os_click(wv, sel, txt, wait_ms)
                short = (sel or txt or "").split(",")[0].strip()[:60]
                return f"watching for '{short}' (≤{wait_ms}ms)…"
            js = _CLICK_JS_TEMPLATE % (
                json.dumps(sel) if sel else "null",
                json.dumps(txt) if txt else "null",
                int(wait_ms),
            )
            try:
                ok, result = wv.RunScript(js)
                rt = (result or "").strip("'\" ")
                if rt == "NOT_FOUND":
                    return f"no element matching {(sel or txt)!r} (and didn't poll)"
                if rt.startswith("CLICK_ERR"):
                    return rt
                if rt.startswith("POLLING:"):
                    return f"watching for {(sel or txt)!r} for up to {wait_ms}ms — will click when it appears"
                return f"clicked: {rt.removeprefix('CLICKED:')}"
            except Exception as e:
                return f"click error: {e}"
        if kind == "page_type":
            wv = self.get_active_webview()
            if not wv:
                return "no active tab"
            text = (action.get("text") or "").strip()
            if not text:
                return "no text to type"
            sel = action.get("selector")
            js = (
                "(function(){"
                "var s = " + (json.dumps(sel) if sel else "null") + ";"
                "var inp = s ? document.querySelector(s) : null;"
                "if (!inp) {"
                "  inp = document.querySelector('input[type=search]')"
                "     || document.querySelector('input[name=q]')"
                "     || document.querySelector('input[name=query]')"
                "     || document.querySelector('input[name=p]')"
                "     || document.querySelector('textarea[name=q]')"
                "     || document.querySelector('input[type=text]')"
                "     || document.querySelector('textarea');"
                "}"
                "if (!inp) return 'NO_INPUT';"
                "var proto = inp.tagName === 'TEXTAREA' ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;"
                "var setter = Object.getOwnPropertyDescriptor(proto,'value').set;"
                "setter.call(inp, " + json.dumps(text) + ");"
                "inp.dispatchEvent(new Event('input',{bubbles:true}));"
                "inp.dispatchEvent(new Event('change',{bubbles:true}));"
                "var form = inp.closest('form');"
                "if (form) { form.submit(); return 'SUBMITTED'; }"
                "inp.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',code:'Enter',keyCode:13,which:13,bubbles:true,cancelable:true}));"
                "inp.dispatchEvent(new KeyboardEvent('keypress',{key:'Enter',code:'Enter',keyCode:13,which:13,bubbles:true,cancelable:true}));"
                "inp.dispatchEvent(new KeyboardEvent('keyup',{key:'Enter',code:'Enter',keyCode:13,which:13,bubbles:true,cancelable:true}));"
                "return 'ENTER';"
                "})();"
            )
            try:
                ok, result = wv.RunScript(js)
                if (result or "").strip("'\" ") == "NO_INPUT":
                    return f"could not find a search input on this page for {text!r}"
                return f"typed in page search box: {text!r}"
            except Exception as e:
                return f"page_type error: {e}"
        if kind in ("click_element", "fill", "select_option", "select_value"):
            wv = self.get_active_webview()
            if not wv:
                return "no active tab"
            idx = action.get("index")
            if not isinstance(idx, int):
                return "needs an integer 'index' from the observed element list"
            if kind == "click_element":
                op, value = "click", "null"
            elif kind == "fill":
                op, value = "fill", json.dumps(str(action.get("text", "")))
            else:
                op, value = "select", json.dumps(str(action.get("option") or action.get("value", "")))
            js = _ACT_ON_INDEX_JS % (int(idx), json.dumps(op), value)
            try:
                ok, result = wv.RunScript(js)
                rt = (result or "").strip("'\" ")
                if rt == "NO_SUCH_INDEX":
                    return f"element #{idx} no longer exists — observe the page again"
                if rt == "NO_OPTION":
                    return f"no matching option for {action.get('option')!r}"
                if rt.startswith(("CLICKED:", "FILLED:", "SELECTED:")):
                    verb, _, lbl = rt.partition(":")
                    return f"{verb.lower()} #{idx}: {lbl}"
                return f"{kind} #{idx}: {rt}"
            except Exception as e:
                return f"{kind} error: {e}"
        if kind == "scroll":
            wv = self.get_active_webview()
            if not wv:
                return "no active tab"
            direction = (action.get("direction") or "down").lower()
            amount = action.get("amount")
            if not isinstance(amount, int):
                amount = 700
            if direction in ("top", "start"):
                js = "window.scrollTo({top:0,behavior:'smooth'}); 'TOP';"
            elif direction in ("bottom", "end"):
                js = "window.scrollTo({top:document.body.scrollHeight,behavior:'smooth'}); 'BOTTOM';"
            elif direction == "up":
                js = f"window.scrollBy({{top:-{int(amount)},behavior:'smooth'}}); 'UP';"
            else:
                js = f"window.scrollBy({{top:{int(amount)},behavior:'smooth'}}); 'DOWN';"
            try:
                wv.RunScript(js)
                return f"scrolled {direction}"
            except Exception as e:
                return f"scroll error: {e}"
        if kind == "observe":
            # Returned to the loop, not the user; handled by the caller.
            return "observed"
        if kind == "bookmark":
            self._toggle_bookmark()
            return "toggled bookmark on active page"
        if kind in ("reply", "done"):
            return action.get("text") or "(done)"
        return f"unknown action '{kind}'"

    # ---------- page observation for the agentic loop ----------
    def observe_page(self) -> dict:
        """Catalog visible interactive elements on the active tab. Tags each
        with data-atb-idx so click_element/fill can act on them by index."""
        wv = self.get_active_webview()
        if wv is None:
            return {"error": "no active tab", "elements": []}
        try:
            ok, raw = wv.RunScript(AgentPanel._EXTRACT_INTERACTIVE_JS)
            if ok and raw:
                return json.loads(raw)
        except Exception as e:
            return {"error": str(e), "elements": []}
        return {"elements": []}

    def _build_assistant_panel(self) -> wx.Panel:
        if ASSISTANT_MODE == "agent":
            return AgentPanel(self.content_split, self)
        # --- chat (webview) fallback ---
        panel = wx.Panel(self.content_split)
        panel.SetBackgroundColour(CHROME_BG)

        header = wx.Panel(panel)
        header.SetBackgroundColour(CHROME_BG)
        label_text = "🦆 Duck AI" if "duck" in ASSISTANT_URL else "✨ Gemini"
        title = wx.StaticText(header, label=label_text)
        title.SetFont(wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        title.SetForegroundColour(OMNIBOX_TEXT)
        reload_btn = wx.Button(header, label="↻", size=wx.Size(26, 26), style=wx.BORDER_NONE)
        reload_btn.SetBackgroundColour(CHROME_BG)
        reload_btn.SetToolTip("Reload Gemini")
        close_btn = wx.Button(header, label="×", size=wx.Size(26, 26), style=wx.BORDER_NONE)
        close_btn.SetBackgroundColour(CHROME_BG)
        close_btn.SetFont(wx.Font(13, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        close_btn.SetToolTip("Hide panel (Ctrl+G)")

        h = wx.BoxSizer(wx.HORIZONTAL)
        h.Add(title, 1, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 10)
        h.Add(reload_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 2)
        h.Add(close_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        header.SetSizer(h)
        header.SetMinSize(wx.Size(-1, 34))

        self._assistant_view = wx.html2.WebView.New(
            panel, backend=wx.html2.WebViewBackendEdge, url=ASSISTANT_URL,
        )
        self._assistant_view.SetUserAgent(GENERIC_USER_AGENT)
        self._assistant_view.Bind(wx.html2.EVT_WEBVIEW_NEWWINDOW, self._on_new_window)
        # Any link in the side panel that points outside the assistant's own
        # domains → open as a real browser tab and stop the in-panel navigation.
        self._assistant_view.Bind(wx.html2.EVT_WEBVIEW_NAVIGATING, self._on_assistant_navigating)

        reload_btn.Bind(wx.EVT_BUTTON, lambda e: self._assistant_view.Reload())
        close_btn.Bind(wx.EVT_BUTTON, lambda e: self._toggle_assistant())

        v = wx.BoxSizer(wx.VERTICAL)
        v.Add(header, 0, wx.EXPAND)
        v.Add(self._assistant_view, 1, wx.EXPAND)
        panel.SetSizer(v)
        return panel

    def _on_assistant_navigating(self, evt: wx.html2.WebViewEvent):
        url = evt.GetURL() or ""
        if not url.startswith(("http://", "https://")):
            return  # let about:, data:, blob: etc. through
        host = url.split("://", 1)[1].split("/", 1)[0].lower()
        if any(host == d or host.endswith("." + d) for d in ASSISTANT_DOMAINS):
            return  # in-panel navigation allowed
        evt.Veto()
        self.add_new_tab(url, select=True)

    def _toggle_assistant(self):
        if self.content_split.IsSplit():
            self.content_split.Unsplit(self._assistant_panel)
            self.GetStatusBar().SetStatusText("AI panel hidden.", 0)
        else:
            if self._assistant_panel is None:
                self._assistant_panel = self._build_assistant_panel()
            width = self.content_split.GetClientSize().GetWidth()
            sash = max(280, width - 440)
            self.content_split.SplitVertically(self.book, self._assistant_panel, sash)
            note = ("Duck Agent open — ask in natural language; it will navigate / search / bookmark for you."
                    if ASSISTANT_MODE == "agent"
                    else "AI chat open.")
            self.GetStatusBar().SetStatusText(note, 0)
            if hasattr(self._assistant_panel, "focus_input"):
                self._assistant_panel.focus_input()

    def _toggle_bookmarks_bar(self):
        showing = self.bm_bar.IsShown()
        self.bm_bar.Show(not showing)
        self._main_sizer.Layout()
        self.GetStatusBar().SetStatusText(
            "Bookmarks bar hidden." if showing else "Bookmarks bar shown.", 0
        )

    def _find_in_page(self):
        webview = self.get_active_webview()
        if not webview:
            return
        dlg = wx.TextEntryDialog(self, "Find on page:", "Find")
        if dlg.ShowModal() == wx.ID_OK:
            needle = dlg.GetValue()
            if needle:
                try:
                    webview.Find(needle, wx.html2.WEBVIEW_FIND_HIGHLIGHT_RESULT)
                except Exception:
                    pass
        dlg.Destroy()

    def _toggle_fullscreen(self):
        going_full = not self.IsFullScreen()
        if going_full:
            self.toolbar.Hide()
            self.GetStatusBar().Hide()
        else:
            self.toolbar.Show()
            self.GetStatusBar().Show()
        self.ShowFullScreen(going_full)
        self.Layout()


def main():
    app = wx.App(False)
    frame = Browser()
    frame.Show()

    if "--selftest" in sys.argv:
        wx.CallLater(2000, frame.Close)

    app.MainLoop()
    _cleanup_session()


if __name__ == "__main__":
    main()
