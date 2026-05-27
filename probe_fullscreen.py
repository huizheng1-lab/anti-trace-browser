import os, sys
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--autoplay-policy=no-user-gesture-required")

from PySide6.QtCore import QUrl, QTimer
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEnginePage
from privacy_engine import build_ephemeral_profile

def main():
    app = QApplication(sys.argv)
    view = QWebEngineView()
    profile = build_ephemeral_profile(view)
    page = QWebEnginePage(profile, view)
    view.setPage(page)

    page.fullScreenRequested.connect(lambda req: (print("FS REQ fired, on=", req.toggleOn()), req.accept()))

    HTML = """<!doctype html><html><body><script>
      document.title = JSON.stringify({
        fullscreenEnabled: document.fullscreenEnabled,
        webkitFullscreenEnabled: document.webkitFullscreenEnabled,
        hasRequestFs: !!document.documentElement.requestFullscreen,
      });
    </script></body></html>"""

    def after_load(_):
        print("PROBE:", page.title())
        # Try requesting fullscreen programmatically
        page.runJavaScript(
            "document.documentElement.requestFullscreen().then(()=>'ok').catch(e=>'err:'+e.message)",
            0,
            lambda r: (print("requestFullscreen result:", r), QTimer.singleShot(500, app.quit))
        )

    page.loadFinished.connect(after_load)
    view.resize(800, 600)
    view.show()
    view.setHtml(HTML)
    QTimer.singleShot(8000, app.quit)
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
