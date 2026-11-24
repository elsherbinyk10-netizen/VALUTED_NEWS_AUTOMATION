import unittest
from unittest.mock import Mock, patch

from official_channel_video import (
    fetch_official_channel_video,
    _publisher_channel,
    _CHANNEL_ID_CACHE,
    _CHANNEL_FEED_CACHE,
    _PLAYABLE_VIDEO_CACHE,
)


class OfficialChannelVideoTests(unittest.TestCase):
    def setUp(self):
        _CHANNEL_ID_CACHE.clear()
        _CHANNEL_FEED_CACHE.clear()
        _PLAYABLE_VIDEO_CACHE.clear()

    def test_only_maps_known_publisher_domains(self):
        self.assertEqual(_publisher_channel("https://www.bbc.com/news/story"),
                         ("BBC News", "UC16niRr50-MSBwiO3YDb3RA"))
        self.assertEqual(_publisher_channel("https://www.nasa.gov/news/story"),
                         ("NASA", "UCLA_DiR1FfKNvjuUpBHmylQ"))
        self.assertEqual(_publisher_channel("https://www.npr.org/2026/11/24/story"),
                         ("NPR", "UCJnS2EsPfv46u1JR8cnD0NA"))
        self.assertEqual(_publisher_channel("https://www.billboard.com/pro/story"),
                         ("Billboard", "UCsVcseUYbYjldc-XgcsiEbg"))
        self.assertEqual(_publisher_channel("https://www.rollingstone.com/music/story"),
                         ("Rolling Stone", "UC-JblcinswY50lrUdSaRNEg"))
        self.assertEqual(_publisher_channel("https://www.theguardian.com/world/story"),
                         ("The Guardian", "@theGuardian"))
        self.assertEqual(_publisher_channel("https://variety.com/2026/music/story"),
                         ("Variety", "@Variety"))
        self.assertIsNone(_publisher_channel("https://example.com/story"))

    @patch("official_channel_video.requests.get")
    def test_resolves_only_the_allowlisted_handle_to_a_channel_id(self, get_mock):
        page = Mock(ok=True, text='{"channelId":"UC1234567890123456789012"}')
        get_mock.return_value = page
        from official_channel_video import _resolve_channel_id, _CHANNEL_ID_CACHE
        _CHANNEL_ID_CACHE.clear()
        self.assertEqual(_resolve_channel_id("@theGuardian"), "UC1234567890123456789012")
        self.assertEqual(get_mock.call_count, 1)

    @patch("official_channel_video.requests.get")
    def test_uses_only_channel_feed_match_and_checks_playback(self, get_mock):
        xml = b'''<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"
        xmlns:yt="http://www.youtube.com/xml/schemas/2015">
        <entry><id>yt:video:AbCdEf12345</id><yt:videoId>AbCdEf12345</yt:videoId>
        <yt:channelId>UC16niRr50-MSBwiO3YDb3RA</yt:channelId>
        <title>NASA Artemis mission update</title><link href="https://www.youtube.com/watch?v=AbCdEf12345"/></entry>
        </feed>'''
        feed = Mock(ok=True, content=xml)
        metadata = Mock(ok=True)
        metadata.json.return_value = {"title": "NASA Artemis mission update"}
        player = Mock(ok=True, text="<html>playable video player</html>")
        get_mock.side_effect = [feed, metadata, player]
        result = fetch_official_channel_video(
            "NASA Artemis mission update", "https://www.bbc.com/news/story"
        )
        self.assertIn("youtube-nocookie.com/embed/AbCdEf12345", result)
        self.assertIn("Official video: BBC News", result)

    @patch("official_channel_video.requests.get")
    def test_rejects_unavailable_official_channel_video(self, get_mock):
        xml = b'''<feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015">
        <entry><yt:videoId>AbCdEf12345</yt:videoId><yt:channelId>UCLA_DiR1FfKNvjuUpBHmylQ</yt:channelId>
        <title>NASA Artemis mission update</title></entry></feed>'''
        feed = Mock(ok=True, content=xml)
        metadata = Mock(ok=True)
        metadata.json.return_value = {"title": "NASA Artemis mission update"}
        player = Mock(ok=True, text="Video unavailable")
        get_mock.side_effect = [feed, metadata, player]
        self.assertEqual(fetch_official_channel_video(
            "NASA Artemis mission update", "https://www.nasa.gov/news/story"
        ), "")


if __name__ == "__main__":
    unittest.main()
