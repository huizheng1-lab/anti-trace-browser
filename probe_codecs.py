"""Headlessly load a tiny HTML page and ask the engine what it can play."""
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

HTML = """
<!doctype html><html><body>
<script>
  const v = document.createElement('video');
  const codecs = {
    h264_baseline: v.canPlayType('video/mp4; codecs="avc1.42E01E"'),
    h264_high:     v.canPlayType('video/mp4; codecs="avc1.640028"'),
    aac:           v.canPlayType('audio/mp4; codecs="mp4a.40.2"'),
    vp9:           v.canPlayType('video/webm; codecs="vp9"'),
    opus:          v.canPlayType('audio/webm; codecs="opus"'),
    vp8:           v.canPlayType('video/webm; codecs="vp8, vorbis"'),
    av1:           v.canPlayType('video/mp4; codecs="av01.0.05M.08"'),
  };
  window._probeResult = codecs;
  document.title = JSON.stringify(codecs);
</script>
</body></html>
"""

def main():
    app = QApplication(sys.argv)
    view = QWebEngineView()
    page = view.page()

    print("Chromium version:", page.profile().httpUserAgent())

    def run_probe(_ok):
        import json
        title = page.title()
        print("--- canPlayType results ---")
        try:
            data = json.loads(title)
            for k, v in data.items():
                print(f"  {k:>14}: {v!r}")
        except Exception as e:
            print("parse failed:", e, "raw title:", title)
        QTimer.singleShot(50, app.quit)

    page.loadFinished.connect(run_probe)
    view.setHtml(HTML)
    view.resize(400, 200)
    # Don't show — invisible probe.
    QTimer.singleShot(10000, app.quit)  # safety timeout
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
