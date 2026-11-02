import unittest
from publisher_video import _trusted_player_url


class PublisherVideoTrustTests(unittest.TestCase):
    def test_trusts_embedded_player_from_supported_provider(self):
        self.assertTrue(_trusted_player_url("https://www.youtube.com/embed/AbCdEf12345"))
        self.assertTrue(_trusted_player_url("https://player.vimeo.com/video/123456789"))
        self.assertTrue(_trusted_player_url("https://players.brightcove.net/123/default_default/index.html"))

    def test_rejects_non_player_pages_and_untrusted_hosts(self):
        self.assertFalse(_trusted_player_url("https://www.youtube.com/results?search_query=news"))
        self.assertFalse(_trusted_player_url("https://evil.example/embed/AbCdEf12345"))
        self.assertFalse(_trusted_player_url("http://www.youtube.com/embed/AbCdEf12345"))
        self.assertFalse(_trusted_player_url("javascript:alert(1)"))


if __name__ == "__main__":
    unittest.main()
