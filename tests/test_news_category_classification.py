import unittest
from news_worker import classify_story_category


class NewsCategoryClassificationTests(unittest.TestCase):
    def test_documentary_trailer_from_music_feed_is_entertainment_not_technology(self):
        title = "Justin Timberlake Documentary Trailer: Apple TV Series to Unpack Britney Spears"
        description = "Apple TV has confirmed a new four-part documentary series."
        self.assertEqual(classify_story_category(title, description, "Music"), "Entertainment")

    def test_ordinary_technology_story_remains_technology(self):
        self.assertEqual(
            classify_story_category("Apple announces a new AI chip for computers", "", "Technology"),
            "Technology",
        )

    def test_music_feed_without_other_strong_headline_signal_uses_entertainment(self):
        self.assertEqual(classify_story_category("New music venue opens", "", "Music"), "Entertainment")


if __name__ == "__main__":
    unittest.main()
