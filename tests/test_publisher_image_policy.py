import unittest
from publisher_image_policy import inspect_publisher_page, verify_publisher_image


PAGE = """
<html><head>
<link rel="canonical" href="https://publisher.example/story/one">
<meta property="og:title" content="NASA discovers new moon around distant planet">
<meta property="og:image" content="https://publisher.example/images/nasa-moon.jpg">
<meta property="article:published_time" content="2026-11-02T10:00:00Z">
<meta property="article:modified_time" content="2026-11-02T12:00:00Z">
</head></html>
"""


class PublisherImagePolicyTests(unittest.TestCase):
    def test_accepts_exact_publisher_image_and_matching_recent_story(self):
        result = verify_publisher_image(
            "https://publisher.example/story/one", PAGE,
            "NASA discovers new moon around distant planet",
            "https://publisher.example/images/nasa-moon.jpg",
            "2026-11-02T10:00:00Z",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["publisher_host"], "publisher.example")

    def test_rejects_unrelated_publisher_page(self):
        result = inspect_publisher_page(
            "https://publisher.example/story/one", PAGE,
            "Netflix announces a new film release", "2026-11-02T10:00:00Z",
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "publisher-page-title-mismatch")

    def test_rejects_image_not_declared_by_publisher(self):
        result = verify_publisher_image(
            "https://publisher.example/story/one", PAGE,
            "NASA discovers new moon around distant planet",
            "https://publisher.example/images/other-story.jpg",
            "2026-11-02T10:00:00Z",
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "image-not-declared-by-publisher-page")

    def test_rejects_image_host_outside_publisher(self):
        result = verify_publisher_image(
            "https://publisher.example/story/one", PAGE,
            "NASA discovers new moon around distant planet",
            "https://unrelated-cdn.example/nasa-moon.jpg",
            "2026-11-02T10:00:00Z",
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "image-not-hosted-by-original-publisher")

    def test_rejects_missing_source_date(self):
        page = PAGE.replace(
            '<meta property="article:published_time" content="2026-11-02T10:00:00Z">',
            "",
        ).replace(
            '<meta property="article:modified_time" content="2026-11-02T12:00:00Z">',
            "",
        )
        result = inspect_publisher_page(
            "https://publisher.example/story/one", page,
            "NASA discovers new moon around distant planet", "2026-11-02T10:00:00Z",
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "publisher-publication-date-missing")

    def test_rejects_source_date_outside_article_window(self):
        result = inspect_publisher_page(
            "https://publisher.example/story/one", PAGE,
            "NASA discovers new moon around distant planet", "2025-01-01T10:00:00Z",
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "publisher-publication-date-mismatch")

    def test_rejects_article_update_when_publisher_has_no_modified_date(self):
        page = PAGE.replace(
            '<meta property="article:modified_time" content="2026-11-02T12:00:00Z">', ""
        )
        result = inspect_publisher_page(
            "https://publisher.example/story/one", page,
            "NASA discovers new moon around distant planet",
            "2026-11-02T10:00:00Z", "2026-11-04T10:00:00Z",
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "publisher-update-date-missing")

    def test_rejects_mismatched_publisher_update_date(self):
        page = PAGE.replace(
            'content="2026-11-02T12:00:00Z"',
            'content="2026-11-02T12:00:00Z"',
        )
        result = inspect_publisher_page(
            "https://publisher.example/story/one", page,
            "NASA discovers new moon around distant planet",
            "2026-11-02T10:00:00Z", "2026-11-20T10:00:00Z",
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "publisher-update-date-mismatch")


if __name__ == "__main__":
    unittest.main()
