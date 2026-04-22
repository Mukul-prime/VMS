import threading


_lock = threading.Lock()
_active_rtsp_urls = set()


def _normalize(url):
    return (url or "").strip().lower()


def register_rtsp(url):
    """
    Returns True if URL was registered, False if already active.
    """
    key = _normalize(url)
    if not key:
        return False
    with _lock:
        if key in _active_rtsp_urls:
            return False
        _active_rtsp_urls.add(key)
        return True


def unregister_rtsp(url):
    key = _normalize(url)
    if not key:
        return
    with _lock:
        _active_rtsp_urls.discard(key)


def is_rtsp_active(url):
    key = _normalize(url)
    if not key:
        return False
    with _lock:
        return key in _active_rtsp_urls
