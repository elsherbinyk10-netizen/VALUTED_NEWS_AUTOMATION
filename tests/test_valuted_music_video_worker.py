import unittest
from datetime import datetime, timezone
from music.video_worker import duration_seconds, is_official_music_video, parse_published, build_article

class MusicVideoWorkerTests(unittest.TestCase):
    def test_duration_parser(self):
        self.assertEqual(duration_seconds("PT4M12S"),252)
        self.assertEqual(duration_seconds("PT1H2M3S"),3723)
        self.assertEqual(duration_seconds("PT30S"),30)
        self.assertEqual(duration_seconds("unknown"),0)

    def test_title_and_duration_quality_gate(self):
        self.assertTrue(is_official_music_video("Artist - Track (Official Music Video)","Official release description","PT3M20S"))
        self.assertTrue(is_official_music_video("Artist - Track (Official Lyric Video)","Official lyrics","PT3M20S"))
        self.assertFalse(is_official_music_video("Artist - Track #Shorts (Official Video)","Official video","PT30S"))
        self.assertFalse(is_official_music_video("Artist - Track (Official Music Video)","Official video","PT30S"))
        self.assertTrue(is_official_music_video("Artist - Track (Official Audio)","Official audio","PT3M20S"))

    def test_published_timestamp(self):
        self.assertEqual(parse_published("2026-11-24T10:00:00Z"),datetime(2026,11,24,10,0,tzinfo=timezone.utc))
        self.assertIsNone(parse_published("not-a-date"))

    def test_article_is_staged_with_thumbnail_and_schema_fields(self):
        video={"video_id":"abcdefghijk","title":"Artist — Song (Official Music Video)",
          "description":"An official music video release description with enough text.",
          "channel_title":"Official Label","thumbnail":"https://i.ytimg.com/vi/abcdefghijk/hqdefault.jpg",
          "published":datetime(2026,11,24,10,0,tzinfo=timezone.utc),"duration":"PT3M20S",
          "embed_url":"https://www.youtube-nocookie.com/embed/abcdefghijk",
          "watch_url":"https://www.youtube.com/watch?v=abcdefghijk"}
        article=build_article(video)
        self.assertFalse(article["isPublished"])
        self.assertEqual(article["image"]["url"],video["thumbnail"])
        self.assertIn("youtube-nocookie.com/embed/abcdefghijk",article["body"])
        keys={item["key"] for item in article["metafields"]}
        self.assertTrue({"video_id","video_thumbnail","video_upload_date"}.issubset(keys))
        self.assertEqual(article["author"]["name"],"VALUTED MUSIC Video Desk")
        self.assertIn("VideoObject",article["body"])
        self.assertIn("title_tag",keys)
        self.assertIn("description_tag",keys)

if __name__=="__main__": unittest.main()
