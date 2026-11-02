import unittest
from unittest.mock import Mock, patch
from publisher_video import _trusted_player_url, fetch_publisher_video


class PublisherVideoTrustTests(unittest.TestCase):
    def test_trusts_embedded_player_from_supported_provider(self):
        self.assertTrue(_trusted_player_url("https://www.youtube.com/embed/AbCdEf12345"))
        self.assertTrue(_trusted_player_url("https://player.vimeo.com/video/123456789"))
        self.assertTrue(_trusted_player_url("https://players.brightcove.net/123/default_default/index.html"))

    def test_accepts_player_hosted_on_the_original_publisher_domain(self):
        self.assertTrue(_trusted_player_url("https://video.publisher.example/player/story-123", "publisher.example"))
        self.assertFalse(_trusted_player_url("https://unrelated.example/player/story-123", "publisher.example"))

    def test_rejects_non_player_pages_and_untrusted_hosts(self):
        self.assertFalse(_trusted_player_url("https://www.youtube.com/results?search_query=news"))
        self.assertFalse(_trusted_player_url("https://evil.example/embed/AbCdEf12345"))
        self.assertFalse(_trusted_player_url("http://www.youtube.com/embed/AbCdEf12345"))
        self.assertFalse(_trusted_player_url("javascript:alert(1)"))

    @patch("publisher_video.requests.get")
    def test_extracts_videoobject_embed_url_when_player_is_client_rendered(self, get_mock):
        page = Mock(ok=True, text='''<html><head><script type="application/ld+json">
        {"@context":"https://schema.org","@type":"NewsArticle","video":{"@type":"VideoObject",
        "name":"Publisher report","embedUrl":"https://players.brightcove.net/123/default_default/index.html"}}
        </script></head><body><article><p>Story text</p></article></body></html>''',
        headers={"Content-Type":"text/html"}, url="https://publisher.example/story")
        player = Mock(ok=True, headers={"Content-Type":"text/html"})
        player.close.return_value = None
        get_mock.side_effect = [page, player]
        result = fetch_publisher_video("https://publisher.example/story")
        self.assertIn("players.brightcove.net/123/default_default/index.html", result)
        self.assertIn("Original publisher video", result)

    @patch("publisher_video.requests.get")
    def test_extracts_open_graph_video_player(self, get_mock):
        page = Mock(ok=True, text='''<html><head><meta property="og:video" content="https://player.vimeo.com/video/123456789"></head>
        <body><article><p>Story</p></article></body></html>''',
        headers={"Content-Type":"text/html"}, url="https://publisher.example/story")
        player = Mock(ok=True, headers={"Content-Type":"text/html"})
        player.close.return_value = None
        get_mock.side_effect = [page, player]
        self.assertIn("player.vimeo.com/video/123456789", fetch_publisher_video("https://publisher.example/story"))

    def test_videoobject_extraction_rejects_untrusted_domains(self):
        from publisher_video import _video_object_urls
        payload = {"@type":"VideoObject","embedUrl":"https://evil.example/embed/clip"}
        self.assertEqual(list(_video_object_urls(payload)), ["https://evil.example/embed/clip"])


if __name__ == "__main__":
    unittest.main()
