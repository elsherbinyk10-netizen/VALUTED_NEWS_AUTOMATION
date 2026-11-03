import unittest
from article_quality import repair_mojibake, text_integrity_issues, seo_description, final_article_integrity_issues


class ArticleQualityTests(unittest.TestCase):
    def test_repairs_common_utf8_mojibake_without_changing_good_text(self):
        self.assertEqual(repair_mojibake("AndrÃ© and El NiÃ±o cost Â£5"), "André and El Niño cost £5")
        self.assertEqual(repair_mojibake("The challenge was difficult."), "The challenge was difficult.")

    def test_repairs_mixed_windows_1252_punctuation_sequences(self):
        self.assertEqual(repair_mojibake("MNF-U â Ukraine and âreadinessâ"), "MNF-U – Ukraine and “readiness”")

    def test_removes_nonprinting_windows_1252_control_artifact(self):
        self.assertEqual(repair_mojibake("awful â\x81 lot"), "awful lot")
        self.assertEqual(repair_mojibake("focused â\x81 on Hubbard"), "focused on Hubbard")

    def test_does_not_guess_when_repair_is_not_reversible(self):
        self.assertEqual(repair_mojibake("Ã broken"), "Ã broken")
        self.assertEqual(repair_mojibake("â"), "â")

    def test_flags_known_truncation_and_encoding_errors(self):
        self.assertIn("possible_mojibake_or_replacement_character",
                      text_integrity_issues("Title", "", "AndrÃ©"))
        self.assertIn("known_truncated_or_malformed_phrase",
                      text_integrity_issues("Title", "", "sent of for his challe"))

    def test_final_article_gate_blocks_corrupted_body_and_seo(self):
        issues = final_article_integrity_issues(
            "Match report", "A complete summary", "<p>AndrÃ© was sent off for his challe</p>",
            "Match report | Sports", "Sports: AndrÃ© was sent off for his challe"
        )
        self.assertTrue(any("possible_mojibake" in issue for issue in issues))
        self.assertTrue(any("known_truncated" in issue for issue in issues))

    def test_final_article_gate_allows_clean_article(self):
        self.assertEqual(
            final_article_integrity_issues(
                "Match report", "A complete summary", "<p>The player completed his challenge.</p>",
                "Match report | Sports", "Sports: The player completed his challenge."
            ),
            [],
        )

    def test_seo_description_truncates_at_word_boundary(self):
        result = seo_description("This is a complete sentence about his challenge and the result.", "Title", 30)
        self.assertTrue(result.endswith("..."))
        self.assertLessEqual(len(result), 30)


if __name__ == "__main__":
    unittest.main()
