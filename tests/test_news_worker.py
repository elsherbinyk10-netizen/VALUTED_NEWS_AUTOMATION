import unittest
from unittest.mock import patch, Mock

import feedparser
import news_worker as worker


class VideoEmbedTests(unittest.TestCase):
    def test_youtube_watch_url_is_privacy_enhanced_and_lazy(self):
        html = worker.extract_video_embed({
            "content": [{"value": "Watch https://www.youtube.com/watch?v=AbCdEf12345"}]
        })
        self.assertIn("youtube-nocookie.com/embed/AbCdEf12345", html)
        self.assertIn('loading="lazy"', html)
        self.assertIn("allowfullscreen", html)

    def test_youtu_be_url_is_supported(self):
        html = worker.extract_video_embed({
            "summary": "https://youtu.be/AbCdEf12345"
        })
        self.assertIn("youtube-nocookie.com/embed/AbCdEf12345", html)

    def test_vimeo_url_is_supported(self):
        html = worker.extract_video_embed({
            "summary": "https://vimeo.com/123456789"
        })
        self.assertIn("player.vimeo.com/video/123456789", html)

    def test_direct_video_file_is_responsive(self):
        html = worker.extract_video_embed({
            "enclosures": [{"href": "https://media.example.org/report.mp4", "type": "video/mp4"}]
        })
        self.assertIn("<video controls", html)
        self.assertIn("report.mp4", html)
        self.assertIn("playsinline", html)

    def test_untrusted_javascript_url_is_rejected(self):
        html = worker.extract_video_embed({
            "summary": "javascript:alert(1)"
        })
        self.assertEqual(html, "")

    @patch.object(worker.requests, "get")
    @patch.object(worker.feedparser, "parse")
    def test_related_youtube_search_requires_title_overlap(self, parse_mock, get_mock):
        response = Mock()
        response.content = b"<feed></feed>"
        response.raise_for_status.return_value = None
        get_mock.return_value = response
        parse_mock.return_value = Mock(entries=[
            {"link": "https://www.youtube.com/watch?v=AbCdEf12345",
             "title": "NASA Artemis moon mission latest update",
             "author": "NASA"}
        ])
        html = worker.fetch_related_youtube_embed("NASA Artemis moon mission")
        self.assertIn("youtube-nocookie.com/embed/AbCdEf12345", html)
        self.assertIn("Related video", html)
        self.assertIn("youtube.com/feeds/videos.xml?search_query=", get_mock.call_args.args[0])

    @patch.object(worker.requests, "get")
    @patch.object(worker.feedparser, "parse")
    def test_unrelated_youtube_result_is_not_embedded(self, parse_mock, get_mock):
        response = Mock()
        response.content = b"<feed></feed>"
        response.raise_for_status.return_value = None
        get_mock.return_value = response
        parse_mock.return_value = Mock(entries=[
            {"link": "https://www.youtube.com/watch?v=AbCdEf12345",
             "title": "Unrelated cooking show recipe",
             "author": "Food Channel"}
        ])
        html = worker.fetch_related_youtube_embed("NASA Artemis moon mission")
        self.assertEqual(html, "")

    def test_editorial_draft_contains_related_video_and_review_notice(self):
        video = '<div class="valuted-news-video"><iframe src="https://www.youtube-nocookie.com/embed/AbCdEf12345" loading="lazy"></iframe></div>'
        article = worker.make_editorial(
            "NASA Artemis mission update", "NASA", "Science",
            "A short publisher summary.", video
        )
        self.assertIn(video, article["body"])
        self.assertIn("EDITORIAL REVIEW REQUIRED", article["body"])
        self.assertFalse(article["quality_ok"])


if __name__ == "__main__":
    unittest.main()
