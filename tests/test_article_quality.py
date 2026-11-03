import unittest
from article_quality import repair_mojibake, text_integrity_issues, seo_description


class ArticleQualityTests(unittest.TestCase):
    def test_repairs_common_utf8_mojibake_without_changing_good_text(self):
        self.assertEqual(repair_mojibake("AndrÃ© and El NiÃ±o cost Â£5"), "André and El Niño cost £5")
        self.assertEqual(repair_mojibake("The challenge was difficult."), "The challenge was difficult.")

    def test_does_not_guess_when_repair_is_not_reversible(self):
        self.assertEqual(repair_mojibake("Ã broken"), "Ã broken")

    def test_flags_known_truncation_and_encoding_errors(self):
        self.assertIn("possible_mojibake_or_replacement_character",
                      text_integrity_issues("Title", "", "AndrÃ©"))
        self.assertIn("known_truncated_or_malformed_phrase",
                      text_integrity_issues("Title", "", "sent of for his challe"))

    def test_seo_description_truncates_at_word_boundary(self):
        result = seo_description("This is a complete sentence about his challenge and the result.", "Title", 30)
        self.assertTrue(result.endswith("..."))
        self.assertLessEqual(len(result), 30)


if __name__ == "__main__":
    unittest.main()
