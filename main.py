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
ID_BACK, ID_FWD, ID_RELOAD, ID_STOP, ID_HOME, ID_GO, ID_WIPE, ID_NEW_TAB, ID_CLOSE_TAB, ID_STAR, ID_TOGGLE_BMBAR, ID_BM_MGR = (wx.NewIdRef() for _ in range(12))


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

        self._build_toolbar()

        # Bookmarks bar lives between toolbar and notebook.
        self.bm_bar = BookmarksBar(self, self.bookmarks, self._navigate_active)

        # Create AuiNotebook container for multi-tab support
        self.notebook = wx.aui.AuiNotebook(
            self,
            style=(
                wx.aui.AUI_NB_DEFAULT_STYLE | 
                wx.aui.AUI_NB_CLOSE_ON_ALL_TABS | 
                wx.aui.AUI_NB_TAB_MOVE |
                wx.aui.AUI_NB_WINDOWLIST_BUTTON
            )
        )
        self.notebook.Bind(wx.aui.EVT_AUINOTEBOOK_PAGE_CHANGED, self._on_tab_changed)
        self.notebook.Bind(wx.aui.EVT_AUINOTEBOOK_PAGE_CLOSE, self._on_tab_close)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.toolbar, 0, wx.EXPAND)
        sizer.Add(self.bm_bar, 0, wx.EXPAND)
        sizer.Add(self.notebook, 1, wx.EXPAND)
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
        sizer.Add(self.btn_bm_mgr, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
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
        self.btn_wipe.Bind(wx.EVT_BUTTON, self._on_wipe)

    # ---------- API / Helper Methods ----------
    def add_new_tab(self, url: str = HOME_URL, select: bool = True) -> wx.html2.WebView:
        webview = wx.html2.WebView.New(
            self.notebook,
            backend=wx.html2.WebViewBackendEdge,
            url=url,
        )
        webview.SetUserAgent(GENERIC_USER_AGENT)
        
        webview.Bind(wx.html2.EVT_WEBVIEW_NAVIGATED, self._on_navigated)
        webview.Bind(wx.html2.EVT_WEBVIEW_LOADED, self._on_loaded)
        webview.Bind(wx.html2.EVT_WEBVIEW_TITLE_CHANGED, self._on_title)
        webview.Bind(wx.html2.EVT_WEBVIEW_FULLSCREEN_CHANGED, self._on_fullscreen)
        webview.Bind(wx.html2.EVT_WEBVIEW_NEWWINDOW, self._on_new_window)
        
        self.notebook.AddPage(webview, "New Tab", select)
        return webview

    def get_active_webview(self) -> wx.html2.WebView:
        if not hasattr(self, "notebook"):
            return None
        idx = self.notebook.GetSelection()
        if idx != wx.NOT_FOUND:
            return self.notebook.GetPage(idx)
        return None

    # ---------- tab events ----------
    def _on_tab_changed(self, evt: wx.aui.AuiNotebookEvent):
        webview = self.get_active_webview()
        if webview:
            self.address.SetValue(webview.GetCurrentURL())
            self._update_nav_state()
            title = webview.GetCurrentTitle()
            if title:
                self.SetTitle(f"{title} — Anti-Trace Browser")
            else:
                self.SetTitle("Anti-Trace Browser")
        evt.Skip()

    def _on_tab_close(self, evt: wx.aui.AuiNotebookEvent):
        if self.notebook.GetPageCount() <= 1:
            evt.Veto()
            webview = self.get_active_webview()
            if webview:
                webview.LoadURL(HOME_URL)
        else:
            evt.Skip()

    def _on_close_tab_menu(self, _evt):
        idx = self.notebook.GetSelection()
        if idx != wx.NOT_FOUND:
            if self.notebook.GetPageCount() <= 1:
                webview = self.get_active_webview()
                if webview:
                    webview.LoadURL(HOME_URL)
            else:
                self.notebook.DeletePage(idx)

    # ---------- events ----------
    def _on_omnibox_submit(self, text: str):
        webview = self.get_active_webview()
        if webview:
            webview.LoadURL(resolve(text))

    def _on_navigated(self, evt: wx.html2.WebViewEvent):
        webview = evt.GetEventObject()
        idx = self.notebook.GetPageIndex(webview)
        if idx != wx.NOT_FOUND:
            url = evt.GetURL()
            if "://" in url:
                domain = url.split("://", 1)[1].split("/", 1)[0]
            else:
                domain = url
            # Only set page text to domain if title hasn't loaded yet
            if not webview.GetCurrentTitle():
                self.notebook.SetPageText(idx, domain[:25])
                
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
        idx = self.notebook.GetPageIndex(webview)
        if idx != wx.NOT_FOUND and title:
            self.notebook.SetPageText(idx, title[:25])
        if webview == self.get_active_webview():
            if title:
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

    def _on_wipe(self, _evt):
        # Best-effort multi-layer wipe.
        # 1) Close all tabs except the first one.
        while self.notebook.GetPageCount() > 1:
            self.notebook.DeletePage(1)
            
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
