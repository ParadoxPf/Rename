import requests
from config import Config

def shorten(full_url: str) -> str:
    """
    Uses your custom shortener API.
    Expects Config.SHORTENER_URL to accept (api, url) (common pattern).
    If your API differs, adapt the payload below.
    Returns shortened URL on success, otherwise original URL.
    """
    try:
        payload = {
            "api": Config.SHORTENER_API,
            "url": full_url
        }
        # If your API expects POST JSON, change requests.post(Config.SHORTENER_URL, json=payload)
        r = requests.get(Config.SHORTENER_URL, params=payload, timeout=12)
        r.raise_for_status()
        data = r.json()
        # Try common fields
        for key in ("short","shortenedUrl","short_url","result","url"):
            if isinstance(data, dict) and key in data:
                return data[key]
        # if API returns direct string
        if isinstance(data, str) and data.startswith("http"):
            return data
    except Exception:
        pass
    return full_url
