import unittest
from unittest.mock import patch
from image_quality import inspect_image_url


class FakeResponse:
    def __init__(self, content, content_type="image/jpeg", ok=True, status_code=200):
        self.content = content
        self.headers = {"Content-Type": content_type}
        self.ok = ok
        self.status_code = status_code
    def close(self):
        pass


class ImageQualityTests(unittest.TestCase):
    @patch("image_quality.requests.get")
    def test_rejects_small_images(self, get):
        from PIL import Image
        from io import BytesIO
        buf = BytesIO()
        Image.new("RGB", (800, 450)).save(buf, format="JPEG")
        get.return_value = FakeResponse(buf.getvalue())
        result = inspect_image_url("https://cdn.example.com/small.jpg")
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "below-minimum-resolution")
        self.assertEqual(result["width"], 800)

    @patch("image_quality.requests.get")
    def test_accepts_large_landscape_image(self, get):
        from PIL import Image
        from io import BytesIO
        buf = BytesIO()
        Image.new("RGB", (1600, 900)).save(buf, format="JPEG")
        get.return_value = FakeResponse(buf.getvalue())
        result = inspect_image_url("https://cdn.example.com/large.jpg")
        self.assertTrue(result["ok"])
        self.assertEqual((result["width"], result["height"]), (1600, 900))

    @patch("image_quality.requests.get")
    def test_rejects_non_image_content(self, get):
        get.return_value = FakeResponse(b"not image", content_type="text/html")
        result = inspect_image_url("https://cdn.example.com/broken")
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "not-an-image")

    @patch("image_quality.requests.get")
    def test_rejects_tall_portrait_image(self, get):
        from PIL import Image
        from io import BytesIO
        buf = BytesIO()
        Image.new("RGB", (900, 1600)).save(buf, format="JPEG")
        get.return_value = FakeResponse(buf.getvalue())
        result = inspect_image_url("https://cdn.example.com/portrait.jpg")
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "unsuitable-aspect-ratio")


if __name__ == "__main__":
    unittest.main()
