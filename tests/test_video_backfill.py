import unittest

import backfill_video


class PublisherVideoBackfillTests(unittest.TestCase):
    def test_primary_source_url_ignores_internal_related_story_links(self):
        body = (
            '<a href="https://valutednews.com/blogs/news/related-story">Related</a>'
            '<p><strong>Source:</strong> Publisher. '
            '<a href="https://publisher.example/exact-story?utm_source=rss">Read the original report</a></p>'
        )
        self.assertEqual(
            backfill_video.primary_source_url(body),
            "https://publisher.example/exact-story?utm_source=rss",
        )

    def test_primary_source_url_returns_empty_when_no_explicit_source(self):
        self.assertEqual(
            backfill_video.primary_source_url('<a href="https://publisher.example/story">Story</a>'),
            "",
        )

    def test_remove_related_video_section_preserves_article_and_source(self):
        body = (
            "<p>Original reporting remains here.</p>"
            '<section class="vn-related-video" aria-label="Related video">'
            "<h2>Related video</h2>"
            '<div class="valuted-news-video"><iframe src="https://www.youtube-nocookie.com/embed/AbCdEf12345"></iframe></div>'
            "</section>"
            '<p><strong>Source:</strong> Publisher. <a href="https://publisher.example/story">Read</a></p>'
        )
        cleaned = backfill_video.remove_related_video(body)
        self.assertIn("Original reporting remains here.", cleaned)
        self.assertIn("https://publisher.example/story", cleaned)
        self.assertNotIn("youtube-nocookie.com/embed", cleaned)
        self.assertNotIn("Related video", cleaned)

    def test_remove_legacy_related_video_block(self):
        body = (
            "<p>Story body.</p><h2>Related video</h2>"
            '<div class="valuted-news-video"><iframe src="https://www.youtube-nocookie.com/embed/AbCdEf12345"></iframe></div>'
            "<p>Source remains.</p>"
        )
        cleaned = backfill_video.remove_related_video(body)
        self.assertIn("Story body.", cleaned)
        self.assertIn("Source remains.", cleaned)
        self.assertNotIn("youtube-nocookie.com/embed", cleaned)

    def test_body_without_video_is_left_unchanged(self):
        body = "<p>Story body.</p><p>Source remains.</p>"
        self.assertEqual(backfill_video.remove_related_video(body), body)


if __name__ == "__main__":
    unittest.main()
