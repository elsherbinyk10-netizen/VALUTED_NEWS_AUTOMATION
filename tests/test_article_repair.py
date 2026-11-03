import unittest

from article_quality import normalize_article_summary, repair_mojibake
from audit_repair_articles import repair_article_fields
from news_worker import make_public_news_brief, paragraphize_source_text


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


    def test_normalizes_cut_off_excerpt_without_splitting_a_word(self):
        summary = "A spate of cyber-attacks hit supermarket chains across Europe and officials warned of disruption to the food supply chain " + ("across several regions " * 8)
        normalized = normalize_article_summary(summary, "Europe on alert")
        self.assertLessEqual(len(normalized), 241)
        self.assertTrue(normalized.endswith("…") or normalized.endswith((".", "!", "?")))
        self.assertTrue(normalized.endswith("…"))
        self.assertTrue(normalized[:-1].endswith("regions"))

    def test_paragraphizer_splits_sentences_into_readable_paragraphs(self):
        text = "First sentence explains the development. Second sentence gives the immediate context. Third sentence adds the impact. Fourth sentence explains what happens next."
        paragraphs = paragraphize_source_text(text, max_sentences=2)
        self.assertEqual(len(paragraphs), 2)
        self.assertIn("Second sentence", paragraphs[0])
        self.assertIn("Fourth sentence", paragraphs[1])

    def test_new_articles_use_semantic_article_structure_and_safe_excerpt(self):
        story = "First complete sentence describes the report. Second complete sentence adds context. " + ("Additional reporting detail supports the story. " * 35)
        article = make_public_news_brief("Test headline", "BBC", "World", story, "https://bbc.example/story")
        self.assertIn('<article class="valuted-news-article">', article["body"])
        self.assertIn('class="vn-news-category"', article["body"])
        self.assertIn('class="vn-article-lead"', article["body"])
        self.assertLessEqual(len(article["summary"]), 240)
        self.assertNotRegex(article["summary"], r"[A-Za-z]…")


if __name__ == "__main__":
    unittest.main()
