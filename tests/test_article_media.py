import unittest
from unittest.mock import Mock, patch

from news_worker import fetch_article_media


class ArticleMediaExtractionTests(unittest.TestCase):
    @patch("news_worker.fetch_official_channel_video", return_value="")
    @patch("news_worker.fetch_publisher_video", return_value="")
    @patch("news_worker.inspect_image_url", return_value={"ok": True, "width": 1600, "height": 900})
    @patch("news_worker.requests.get")
    def test_extracts_high_resolution_image_from_json_ld(self, get_mock, inspect_mock, publisher_video, official_video):
        markup = """<html><head><script type="application/ld+json">
        {"@context":"https://schema.org","@type":"NewsArticle",
         "image":{"@type":"ImageObject","url":"https://images.publisher.example/story-1600x900.jpg"}}
        </script></head><body><article><p>This is the article body with enough text to be extracted safely.</p></article></body></html>"""
        page = Mock(ok=True, headers={"Content-Type": "text/html; charset=utf-8"},
                    encoding="utf-8", url="https://www.theguardian.com/world/story")
        page.iter_content.return_value = [markup.encode("utf-8")]
        page.close.return_value = None
        get_mock.return_value = page

        result = fetch_article_media("https://www.theguardian.com/world/story", "A publisher story")

        self.assertEqual(result["image_url"], "https://images.publisher.example/story-1600x900.jpg")
        inspect_mock.assert_called_once()
        publisher_video.assert_called_once()
        official_video.assert_called_once()


if __name__ == "__main__":
    unittest.main()
