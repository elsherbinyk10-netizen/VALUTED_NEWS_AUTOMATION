import unittest
from datetime import datetime, timezone
from music.video_worker import duration_seconds, is_official_music_video, parse_published, build_article, channel_allowlist, public_player_duration, public_player_duration

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


    def test_public_player_confirms_exact_video_channel_and_duration(self):
        page='ytInitialPlayerResponse = {"playabilityStatus":{"status":"OK"},"videoDetails":{"videoId":"abcdefghijk","channelId":"UC1234567890123456789012","lengthSeconds":"214","isPrivate":false,"isLiveContent":false}};'
        self.assertEqual(public_player_duration(page,"abcdefghijk","UC1234567890123456789012"),214)
        self.assertEqual(public_player_duration(page,"wrongvideoid","UC1234567890123456789012"),0)
        self.assertEqual(public_player_duration(page,"abcdefghijk","UC0000000000000000000000"),0)

    def test_public_player_rejects_unavailable_private_live_and_short(self):
        import json
        base={"playabilityStatus":{"status":"OK"},"videoDetails":{"videoId":"abcdefghijk","channelId":"UC1234567890123456789012","lengthSeconds":"45","isPrivate":False,"isLiveContent":False}}
        def check():
            return public_player_duration("ytInitialPlayerResponse = "+json.dumps(base)+";","abcdefghijk","UC1234567890123456789012")
        self.assertEqual(check(),0)
        base["videoDetails"]["lengthSeconds"]="214"
        base["playabilityStatus"]["status"]="ERROR"
        self.assertEqual(check(),0)
        base["playabilityStatus"]["status"]="OK"
        base["videoDetails"]["isPrivate"]=True
        self.assertEqual(check(),0)
        base["videoDetails"]["isPrivate"]=False
        base["videoDetails"]["isLiveContent"]=True
        self.assertEqual(check(),0)

    def test_verified_official_channel_allowlist(self):
        channels=channel_allowlist()
        ids={item["channel_id"] for item in channels}
        self.assertTrue({"UCg8ZzloDPTrOiGztK0C9txQ","UC9TO_oo4c_LrOiKNaY6aysA","UCowRsWTe-Tpgrckhg26d2kA"}.issubset(ids))

    def test_public_player_must_confirm_exact_public_full_length_video(self):
        import json
        player = {
            "playabilityStatus": {"status": "OK"},
            "videoDetails": {
                "videoId": "abcdefghijk",
                "channelId": "UCNhqvQMXIgRfjAGmxQqdNRw",
                "lengthSeconds": "214",
                "isPrivate": False,
                "isLiveContent": False,
            },
        }
        page = "var ytInitialPlayerResponse = " + json.dumps(player) + ";"
        self.assertEqual(public_player_duration(page, "abcdefghijk", "UCNhqvQMXIgRfjAGmxQqdNRw"), 214)
        self.assertEqual(public_player_duration(page, "wrongvideo1", "UCNhqvQMXIgRfjAGmxQqdNRw"), 0)
        self.assertEqual(public_player_duration(page, "abcdefghijk", "UC0000000000000000000000"), 0)
        player["videoDetails"]["lengthSeconds"] = "30"
        short_page = "var ytInitialPlayerResponse = " + json.dumps(player) + ";"
        self.assertEqual(public_player_duration(short_page, "abcdefghijk", "UCNhqvQMXIgRfjAGmxQqdNRw"), 0)
        player["playabilityStatus"]["status"] = "ERROR"
        unavailable_page = "var ytInitialPlayerResponse = " + json.dumps(player) + ";"
        self.assertEqual(public_player_duration(unavailable_page, "abcdefghijk", "UCNhqvQMXIgRfjAGmxQqdNRw"), 0)

    def test_published_timestamp(self):
        self.assertEqual(parse_published("2026-11-24T10:00:00Z"),datetime(2026,11,24,10,0,tzinfo=timezone.utc))
        self.assertIsNone(parse_published("not-a-date"))

    def test_article_is_published_with_thumbnail_and_schema_fields(self):
        video={"video_id":"abcdefghijk","title":"Artist — Song (Official Music Video)",
          "description":"An official music video release description with enough text.",
          "channel_title":"Official Label","thumbnail":"https://i.ytimg.com/vi/abcdefghijk/hqdefault.jpg",
          "published":datetime(2026,11,24,10,0,tzinfo=timezone.utc),"duration":"PT3M20S",
          "embed_url":"https://www.youtube-nocookie.com/embed/abcdefghijk",
          "watch_url":"https://www.youtube.com/watch?v=abcdefghijk"}
        article=build_article(video)
        self.assertTrue(article["isPublished"])
        self.assertEqual(article["image"]["url"],video["thumbnail"])
        self.assertIn("youtube-nocookie.com/embed/abcdefghijk",article["body"])
        keys={item["key"] for item in article["metafields"]}
        self.assertTrue({"video_id","video_thumbnail","video_upload_date"}.issubset(keys))
        self.assertEqual(article["author"]["name"],"VALUTED MUSIC Video Desk")
        self.assertIn("VideoObject",article["body"])
        self.assertIn("title_tag",keys)
        self.assertIn("description_tag",keys)

if __name__=="__main__": unittest.main()


class ExistingVideoSeoRetrofitTests(unittest.TestCase):
    def test_extract_youtube_embed_id(self):
        from music.video_seo_audit import video_id_from_body
        self.assertEqual(video_id_from_body('<iframe src="https://www.youtube-nocookie.com/embed/abcdefghijk"></iframe>'),"abcdefghijk")
        self.assertEqual(video_id_from_body('<a href="https://www.youtube.com/watch?v=abcdefghijk">Watch</a>'),"abcdefghijk")
        self.assertIsNone(video_id_from_body('<iframe src="https://example.com/embed/abcdefghijk"></iframe>'))

    def test_page_seo_adds_schema_and_correct_video_kind(self):
        from music.video_seo_audit import page_seo
        article={"handle":"artist-song","body":"<p>Existing editorial copy</p>"}
        video={"id":"abcdefghijk","title":"Artist - Song (Official Lyrics Video)",
          "description":"Official lyrics video release with verified source information and credits.",
          "channel":"Official Label","published":"2026-11-24T10:00:00Z",
          "duration":"PT3M20S","thumbnail":"https://i.ytimg.com/vi/abcdefghijk/hqdefault.jpg",
          "embed":"https://www.youtube-nocookie.com/embed/abcdefghijk",
          "watch":"https://www.youtube.com/watch?v=abcdefghijk"}
        body,metafields=page_seo(article,video)
        self.assertIn("VideoObject",body)
        self.assertIn("Watch the official lyrics video",body)
        self.assertIn("youtube-nocookie.com/embed/abcdefghijk",body)
        keys={x["key"] for x in metafields}
        self.assertTrue({"title_tag","description_tag","video_id","video_thumbnail","video_upload_date","video_duration"}.issubset(keys))
