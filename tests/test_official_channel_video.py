import unittest
from unittest.mock import Mock, patch

from official_channel_video import fetch_official_channel_video, _publisher_channel


class OfficialChannelVideoTests(unittest.TestCase):
    def test_only_maps_known_publisher_domains(self):
        self.assertEqual(_publisher_channel("https://www.bbc.com/news/story"),
                         ("BBC News", "UC16niRr50-MSBwiO3YDb3RA"))
        self.assertEqual(_publisher_channel("https://www.nasa.gov/news/story"),
                         ("NASA", "UCLA_DiR1FfKNvjuUpBHmylQ"))
        self.assertIsNone(_publisher_channel("https://example.com/story"))

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
