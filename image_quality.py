"""Shared featured-image quality gate for Valuted News.

A URL is eligible only when it serves a decodable, sufficiently large landscape image.
We never upscale a small source file and pretend it has become high resolution.
"""
from io import BytesIO
from urllib.parse import urlparse

import requests
from PIL import Image, UnidentifiedImageError

HEADERS = {"User-Agent": "ValutedNewsImageQuality/1.0"}
MIN_WIDTH = 500
MIN_HEIGHT = 300
MIN_ASPECT = 1.25
MAX_ASPECT = 2.4
MAX_BYTES = 18 * 1024 * 1024


def inspect_image_url(url, timeout=(4, 10)):
    """Return dimensions and quality verdict after downloading and decoding the image."""
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return {"ok": False, "reason": "invalid-url"}
    try:
        response = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        try:
            if not response.ok:
                return {"ok": False, "reason": "http-error", "status": response.status_code}
            content_type = response.headers.get("Content-Type", "").lower()
            if not content_type.startswith("image/"):
                return {"ok": False, "reason": "not-an-image"}
            content = response.content
            if not content or len(content) > MAX_BYTES:
                return {"ok": False, "reason": "empty-or-too-large"}
        finally:
            response.close()
        try:
            with Image.open(BytesIO(content)) as image:
                width, height = image.size
                image.verify()
        except (UnidentifiedImageError, OSError, ValueError):
            return {"ok": False, "reason": "image-decode-failed"}
        ratio = width / height if height else 0
        if width < MIN_WIDTH or height < MIN_HEIGHT:
            return {"ok": False, "reason": "below-minimum-resolution", "width": width, "height": height}
        if ratio < MIN_ASPECT or ratio > MAX_ASPECT:
            return {"ok": False, "reason": "unsuitable-aspect-ratio", "width": width, "height": height}
        return {"ok": True, "reason": "high-resolution", "width": width, "height": height, "format": content_type}
    except requests.RequestException:
        return {"ok": False, "reason": "request-failed"}
