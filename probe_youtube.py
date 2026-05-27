"""Load a real YouTube video with the privacy profile and report what fails."""
import os
import sys

os.environ.setdefault(
    "QTWEBENGINE_CHROMIUM_FLAGS",
    "--autoplay-policy=no-user-gesture-required",
)

from PySide6.QtCore import QUrl, QTimer
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEnginePage

from privacy_engine import build_ephemeral_profile

VIDEO = "https://www.youtube.com/watch?v=aqz-KE-bpKQ"  # Big Buck Bunny – CC, VP9

class LoggingPage(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, msg, line, src):
        print(f"[JS {level}] {msg}  ({src}:{line})")

def main():
    app = QApplication(sys.argv)
    view = QWebEngineView()
    profile = build_ephemeral_profile(view)
    page = LoggingPage(profile, view)
    view.setPage(page)
    view.resize(1024, 700)
    view.show()
    view.setUrl(QUrl(VIDEO))

    def inspect():
        js = r"""
        (function(){
          const v = document.querySelector('video');
          if (!v) return 'NO_VIDEO_ELEMENT';
          return JSON.stringify({
            src: v.src ? v.src.slice(0,80) : null,
            currentSrc: v.currentSrc ? v.currentSrc.slice(0,80) : null,
            readyState: v.readyState,
            networkState: v.networkState,
            paused: v.paused,
            currentTime: v.currentTime,
            duration: v.duration,
            error: v.error ? {code: v.error.code, msg: v.error.message} : null,
            bodyText: document.body.innerText.slice(0,400),
          });
        })()
        """
        def got(result):
            print("VIDEO STATE:", result)
            QTimer.singleShot(200, app.quit)
        page.runJavaScript(js, 0, got)

    QTimer.singleShot(8000, inspect)
    QTimer.singleShot(15000, app.quit)
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
