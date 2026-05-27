from PySide6.QtCore import QUrl
from PySide6.QtWebEngineCore import (
    QWebEngineProfile,
    QWebEngineUrlRequestInterceptor,
    QWebEngineSettings,
)


GENERIC_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

BLOCKED_DOMAINS = (
    "google-analytics.com",
    "googletagmanager.com",
    "googletagservices.com",
    "doubleclick.net",
    "googlesyndication.com",
    "googleadservices.com",
    "adservice.google.com",
    "facebook.net",
    "connect.facebook.net",
    "scorecardresearch.com",
    "quantserve.com",
    "hotjar.com",
    "mixpanel.com",
    "segment.io",
    "amplitude.com",
    "branch.io",
    "criteo.com",
    "taboola.com",
    "outbrain.com",
    "adnxs.com",
    "moatads.com",
    "chartbeat.com",
    "fullstory.com",
    "newrelic.com",
)

# Hosts we must NEVER block even if a substring appears tracker-ish, because they
# carry actual page/video content (YouTube CDN, etc.).
ALLOWED_HOSTS_SUFFIXES = (
    "youtube.com",
    "youtu.be",
    "ytimg.com",
    "googlevideo.com",
    "ggpht.com",
    "gstatic.com",
)


class TrackerBlocker(QWebEngineUrlRequestInterceptor):
    def interceptRequest(self, info):
        host = info.requestUrl().host().lower()
        for safe in ALLOWED_HOSTS_SUFFIXES:
            if host == safe or host.endswith("." + safe):
                return
        for needle in BLOCKED_DOMAINS:
            if needle in host:
                info.block(True)
                return


def build_ephemeral_profile(parent) -> QWebEngineProfile:
    # Empty storage name => off-the-record / in-memory profile.
    profile = QWebEngineProfile("", parent)

    profile.setPersistentCookiesPolicy(
        QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies
    )
    profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.MemoryHttpCache)
    profile.setHttpUserAgent(GENERIC_USER_AGENT)
    profile.setHttpCacheMaximumSize(0)

    # Wipe any cookies that may have been seeded during construction.
    profile.cookieStore().deleteAllCookies()

    interceptor = TrackerBlocker(profile)
    profile.setUrlRequestInterceptor(interceptor)
    profile._interceptor = interceptor

    settings = profile.settings()
    settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard, False)
    settings.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, False)
    settings.setAttribute(QWebEngineSettings.WebAttribute.PluginsEnabled, True)
    settings.setAttribute(QWebEngineSettings.WebAttribute.ScreenCaptureEnabled, False)
    settings.setAttribute(QWebEngineSettings.WebAttribute.AllowGeolocationOnInsecureOrigins, False)
    settings.setAttribute(QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, False)
    settings.setAttribute(QWebEngineSettings.WebAttribute.FullScreenSupportEnabled, True)

    return profile


def wipe_profile(profile: QWebEngineProfile) -> None:
    profile.cookieStore().deleteAllCookies()
    profile.clearHttpCache()
    profile.clearAllVisitedLinks()
