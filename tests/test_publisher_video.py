import unittest
from publisher_video import _trusted_player_url


class PublisherVideoTrustTests(unittest.TestCase):
    def test_trusts_embedded_player_from_supported_provider(self):
        self.assertTrue(_trusted_player_url("https://www.youtube.com/embed/AbCdEf12345"))
        self.assertTrue(_trusted_player_url("https://player.vimeo.com/video/123456789"))
        self.assertTrue(_trusted_player_url("https://players.brightcove.net/123/default_default/index.html"))

    def test_accepts_player_hosted_on_the_original_publisher_domain(self):
        self.assertTrue(_trusted_player_url(
            "https://video.publisher.example/player/story-123",
            "publisher.example",
        ))
        self.assertFalse(_trusted_player_url(
            "https://unrelated.example/player/story-123",
            "publisher.example",
        ))

    def test_rejects_non_player_pages_and_untrusted_hosts(self):
        self.assertFalse(_trusted_player_url("https://www.youtube.com/results?search_query=news"))
        self.assertFalse(_trusted_player_url("https://evil.example/embed/AbCdEf12345"))
        self.assertFalse(_trusted_player_url("http://www.youtube.com/embed/AbCdEf12345"))
        self.assertFalse(_trusted_player_url("javascript:alert(1)"))

    def test_accepts_allowlisted_publisher_player_when_endpoint_is_playable(self):
        from unittest.mock import Mock, patch
        from news_worker import video_embed_is_available
        response = Mock()
        response.ok = True
        response.headers = {"Content-Type": "text/html; charset=utf-8"}
        response.close.return_value = None
        markup = '<iframe src="https://players.brightcove.net/123/default_default/index.html"></iframe>'
        with patch("news_worker.requests.get", return_value=response):
            self.assertTrue(video_embed_is_available(markup))

    def test_rejects_untrusted_player_host_even_if_http_ok(self):
        from news_worker import video_embed_is_available
        markup = '<iframe src="https://evil.example/embed/video123"></iframe>'
        self.assertFalse(video_embed_is_available(markup))


if __name__ == "__main__":
    unittest.main()
