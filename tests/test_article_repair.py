import unittest

from article_quality import repair_mojibake
from audit_repair_articles import repair_article_fields


class ExistingArticleRepairTests(unittest.TestCase):
    def test_repairs_utf8_punctuation_corruption(self):
        self.assertEqual(repair_mojibake("A report says â\x80\x93 conditions changed."), "A report says – conditions changed.")

    def test_removes_only_duplicate_trailing_source_footer(self):
        body = (
            '<article><p>Report.</p><p><strong>Source:</strong> BBC. '
            '<a href="https://bbc.example/story">Read the original report</a></p>'
            '</article><hr><p><strong>Source:</strong> BBC. '
            '<a href="https://bbc.example/story">Read the original report</a></p>'
        )
        result = repair_article_fields({"title": "Clean", "summary": "Summary", "body": body})
        self.assertEqual(result["body"], body[:body.index("</article>") + len("</article>")])

    def test_keeps_single_source_link_and_unrelated_body(self):
        body = '<article><p>Report.</p><a href="https://bbc.example/story">Read the original report</a></article>'
        self.assertEqual(repair_article_fields({"title": "Clean", "summary": "Summary", "body": body}), {})

    def test_repairs_title_body_without_changing_clean_summary(self):
        article = {
            "title": "A â\x80\x93 B",
            "summary": "A clean summary",
            "body": "<article><p>Text â\x80\x93 here.</p></article>",
        }
        changes = repair_article_fields(article)
        self.assertEqual(changes["title"], "A – B")
        self.assertEqual(changes["body"], "<article><p>Text – here.</p></article>")
        self.assertNotIn("summary", changes)


if __name__ == "__main__":
    unittest.main()
