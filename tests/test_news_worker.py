import unittest
import os
import json
from datetime import datetime, timezone
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

    @patch.object(worker.requests, "get")
    def test_youtube_video_must_pass_oembed_availability_check(self, get_mock):
        metadata = Mock()
        metadata.ok = True
        metadata.json.return_value = {"title": "Publisher video"}
        player = Mock()
        player.ok = True
        player.text = "<html><body>yt player</body></html>"
        get_mock.side_effect = [metadata, player]
        embed = '<iframe src="https://www.youtube-nocookie.com/embed/AbCdEf12345"></iframe>'
        self.assertTrue(worker.video_embed_is_available(embed))
        self.assertEqual(get_mock.call_args_list[0].args[0], "https://www.youtube.com/oembed")
        self.assertEqual(get_mock.call_args_list[1].args[0], "https://www.youtube.com/embed/AbCdEf12345")

    @patch.object(worker.requests, "get")
    def test_unavailable_youtube_video_is_rejected(self, get_mock):
        response = Mock()
        response.ok = False
        get_mock.return_value = response
        embed = '<iframe src="https://www.youtube-nocookie.com/embed/AbCdEf12345"></iframe>'
        self.assertFalse(worker.video_embed_is_available(embed))

    def test_youtube_video_ids_must_be_exactly_eleven_characters(self):
        self.assertEqual(worker.extract_video_embed({"summary": "https://youtu.be/short"}), "")

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
             "title": "NASA Artemis moon mission official video",
             "author": "NASA"}
        ])
        html = worker.fetch_related_youtube_embed("NASA Artemis moon mission", "Science")
        self.assertIn("youtube-nocookie.com/embed/AbCdEf12345", html)
        self.assertIn("Related video", html)
        self.assertIn("youtube.com/feeds/videos.xml?search_query=", get_mock.call_args.args[0])

    @patch.object(worker.requests, "get")
    @patch.object(worker.feedparser, "parse")
    def test_single_common_word_overlap_is_not_enough_for_news_video(self, parse_mock, get_mock):
        response = Mock()
        response.content = b"<feed></feed>"
        response.raise_for_status.return_value = None
        get_mock.return_value = response
        parse_mock.return_value = Mock(entries=[
            {"link": "https://www.youtube.com/watch?v=AbCdEf12345",
             "title": "World news update today",
             "author": "Generic News"}
        ])
        html = worker.fetch_related_youtube_embed("Ferries threaten endangered whales", "Climate")
        self.assertEqual(html, "")

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
        html = worker.fetch_related_youtube_embed("NASA Artemis moon mission", "Science")
        self.assertEqual(html, "")

    @patch.object(worker.requests, "get")
    def test_publisher_video_extraction_ignores_sitewide_sidebar_embeds(self, get_mock):
        response = Mock()
        response.ok = True
        response.headers = {"Content-Type": "text/html; charset=utf-8"}
        response.encoding = "utf-8"
        response.url = "https://publisher.example/story"
        response.iter_content.return_value = [
            b"<html><body><iframe src='https://www.youtube.com/embed/SideBr12345'></iframe>"
            b"<article><h1>Story</h1><iframe src='https://www.youtube.com/embed/StoryVid123'></iframe>"
            b"</article></body></html>"
        ]
        get_mock.return_value = response
        media = worker.fetch_article_media("https://publisher.example/story")
        self.assertIn("StoryVid123", media["video_html"])
        self.assertNotIn("SideBr12345", media["video_html"])

    @patch.object(worker.requests, "get")
    def test_publisher_video_extraction_ignores_sitewide_sidebar_iframes(self, get_mock):
        response = Mock()
        response.ok = True
        response.url = "https://publisher.example/story"
        response.encoding = "utf-8"
        response.headers = {"Content-Type": "text/html; charset=utf-8"}
        response.iter_content.return_value = [
            b'<html><body><article><h1>Story</h1><iframe src="https://www.youtube.com/embed/AbCdEf12345"></iframe></article><aside><iframe src="https://player.vimeo.com/video/987654321"></iframe></aside></body></html>'
        ]
        response.close.return_value = None
        get_mock.return_value = response
        media = worker.fetch_article_media("https://publisher.example/story")
        self.assertIn("youtube-nocookie.com/embed/AbCdEf12345", media["video_html"])
        self.assertNotIn("987654321", media["video_html"])

    def test_auto_publish_requires_flag_low_risk_summary_and_news_image(self):
        item = {
            "title": "A science discovery announced by NASA",
            "url": "https://example.com/story",
            "image_url": "https://images.example.com/story.jpg",
            "description": "This is a sufficiently detailed source summary with relevant facts, verified context, chronology, named details, and supporting information. " * 30,
            "video_html": '<iframe src="https://www.youtube-nocookie.com/embed/AbCdEf12345"></iframe>',
            "risk": False,
        }
        with patch.object(worker, "video_embed_is_available", return_value=True), patch.object(worker, "inspect_image_url", return_value={"ok": True}):
            self.assertTrue(worker.should_auto_publish(item, True))
            item["image_url"] = ""
            self.assertFalse(worker.should_auto_publish(item, True))
            item["image_url"] = "https://images.example.com/story.jpg"
            self.assertFalse(worker.should_auto_publish(item, False))
            item["risk"] = True
            self.assertFalse(worker.should_auto_publish(item, True))
            item["risk"] = False
            item["description"] = "Too short"
            self.assertFalse(worker.should_auto_publish(item, True))

    def test_auto_publish_allows_quality_article_without_video(self):
        item = {
            "title": "A science discovery announced by NASA",
            "url": "https://example.com/story",
            "image_url": "https://images.example.com/story.jpg",
            "description": "This is a sufficiently detailed source summary with relevant facts, verified context, chronology, named details, and supporting information. " * 30,
            "risk": False,
        }
        with patch.object(worker, "inspect_image_url", return_value={"ok": True}):
            self.assertTrue(worker.should_auto_publish(item, True))

    def test_category_classifier_uses_headline_and_source_text(self):
        self.assertEqual(
            worker.classify_story_category("Parliament approves new election law", "The government voted today.", "World"),
            "Politics",
        )
        self.assertEqual(
            worker.classify_story_category("Apple unveils new AI smartphone", "The technology company announced a new device.", "Business"),
            "Technology",
        )
        self.assertEqual(
            worker.classify_story_category("NASA discovers evidence of lunar ice", "Scientists published new research.", "World"),
            "Science",
        )
        self.assertEqual(worker.classify_story_category("An unusual headline", "", "Climate"), "Science")

    def test_feed_text_prefers_longest_content_and_formats_paragraphs(self):
        entry = {
            "summary": "Short summary.",
            "content": [{"value": "<p>First verified sentence. Second verified sentence.</p><p>Third verified sentence.</p>"}],
        }
        extracted = worker.extract_entry_text(entry)
        self.assertGreater(len(extracted), len("Short summary."))
        paragraphs = worker.paragraphize_source_text(extracted)
        self.assertTrue(paragraphs)
        self.assertIn("First verified sentence.", " ".join(paragraphs))

    def test_auto_publish_rejects_thin_summaries_even_if_image_exists(self):
        item = {
            "title": "Science update",
            "url": "https://example.com/story",
            "image_url": "https://images.example.com/story.jpg",
            "description": "A short summary with an image.",
            "risk": False,
        }
        self.assertFalse(worker.should_auto_publish(item, True))

    def test_public_news_brief_without_verified_video_has_no_iframe(self):
        brief = worker.make_public_news_brief(
            "Mediterranean ferries threaten endangered whales",
            "Example Publisher",
            "Environment",
            "A detailed source report with enough context for a meaningful article summary.",
            "https://example.com/whales",
            "https://images.example.com/whales.jpg",
        )
        self.assertNotIn("<iframe", brief["body"].lower())
        self.assertNotIn("<video", brief["body"].lower())

    def test_public_brief_is_attributed_and_has_no_editorial_hold_notice(self):
        brief = worker.make_public_news_brief(
            "Science discovery announced", "NASA", "Science",
            "A detailed summary supplied by the original publisher. " * 4,
            "https://example.com/story"
        )
        self.assertTrue(brief["quality_ok"])
        self.assertIn("Read the original report", brief["body"])
        self.assertNotIn("EDITORIAL REVIEW REQUIRED", brief["body"])

    def test_editorial_draft_contains_related_video_and_review_notice(self):
        video = '<div class="valuted-news-video"><iframe src="https://www.youtube-nocookie.com/embed/AbCdEf12345" loading="lazy"></iframe></div>'
        article = worker.make_editorial(
            "NASA Artemis mission update", "NASA", "Science",
            "A short publisher summary.", video
        )
        self.assertIn(video, article["body"])
        self.assertIn("EDITORIAL REVIEW REQUIRED", article["body"])
        self.assertFalse(article["quality_ok"])


    @patch.object(worker.requests, "get")
    @patch.object(worker.feedparser, "parse")
    def test_movie_category_requires_trailer_match(self, parse_mock, get_mock):
        response = Mock()
        response.content = b"<feed></feed>"
        response.raise_for_status.return_value = None
        get_mock.return_value = response
        parse_mock.return_value = Mock(entries=[
            {"link": "https://www.youtube.com/watch?v=AbCdEf12345",
             "title": "Spider-Man Brand New Day Official Trailer",
             "author": "Sony Pictures"}
        ])
        html = worker.fetch_related_youtube_embed("Spider-Man Brand New Day", "Movies")
        self.assertIn("youtube-nocookie.com/embed/AbCdEf12345", html)
        self.assertIn("Official Trailer", html)
        self.assertIn("official%20trailer", get_mock.call_args.args[0].lower())

    @patch.object(worker.requests, "get")
    @patch.object(worker.feedparser, "parse")
    @patch("yt_dlp.YoutubeDL")
    def test_music_category_queries_for_song_or_music_video(self, ydl_mock, parse_mock, get_mock):
        response = Mock()
        response.content = b"<feed></feed>"
        response.raise_for_status.return_value = None
        get_mock.return_value = response
        parse_mock.return_value = Mock(entries=[
            {"link": "https://www.youtube.com/watch?v=AbCdEf12345",
             "title": "Harry Styles Liam Payne official song music video live performance",
             "author": "Harry Styles"}
        ])
        html = worker.fetch_related_youtube_embed("Harry Styles Liam Payne new song", "Music")
        self.assertIn("youtube-nocookie.com/embed/AbCdEf12345", html)
        self.assertIn("official%20song", get_mock.call_args.args[0].lower())

    @patch.object(worker.requests, "get")
    def test_search_falls_back_to_bing_when_youtube_endpoints_return_400(self, get_mock):
        rss_response = Mock()
        rss_response.raise_for_status.side_effect = worker.requests.HTTPError("400 Bad Request")
        youtube_page = Mock()
        youtube_page.raise_for_status.side_effect = worker.requests.HTTPError("400 Bad Request")
        bing_page = Mock()
        bing_page.raise_for_status.return_value = None
        bing_page.text = '<li class="b_algo"><h2><a href="https://www.youtube.com/watch?v=AbCdEf12345">Spider-Man Brand New Day Official Trailer</a></h2></li>'
        get_mock.side_effect = [rss_response, youtube_page, bing_page]
        result = worker.fetch_related_youtube_embed("Spider-Man Brand New Day", "Movies")
        self.assertIn("youtube-nocookie.com/embed/AbCdEf12345", result)
        self.assertEqual(get_mock.call_count, 3)



    @patch.object(worker, "shopify_graphql")
    def test_related_coverage_index_excludes_unpublished_articles(self, graphql_mock):
        graphql_mock.return_value = {
            "blog": {
                "handle": "news",
                "articles": {"nodes": [
                    {"title": "NASA Artemis lunar mission update", "handle": "artemis-update",
                     "body": "<p><strong>Science</strong></p>", "isPublished": True},
                    {"title": "NASA Artemis lunar mission background", "handle": "artemis-draft",
                     "body": "<p><strong>Science</strong></p>", "isPublished": False},
                ]}
            }
        }
        titles, sources, related = worker.load_existing_shopify_story_index("gid://shopify/Blog/1")
        self.assertEqual(len(related), 1)
        self.assertEqual(related[0]["title"], "NASA Artemis lunar mission update")
        self.assertIn("https://valutednews.com/blogs/news/artemis-update", related[0]["url"])
        self.assertNotIn("artemis-draft", " ".join(item["url"] for item in related))

class TrendingNewsRankingTests(unittest.TestCase):
    def test_multi_publisher_story_ranks_above_single_source_story(self):
        now = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
        items = [
            {"title": "Scientists discover major ocean breakthrough", "publisher": "BBC", "published": now},
            {"title": "Major ocean breakthrough discovered by researchers", "publisher": "NPR", "published": now},
            {"title": "Local museum announces weekend opening", "publisher": "Local", "published": now},
        ]
        ranked = worker.rank_trending_news(items, now)
        self.assertEqual(ranked[0]["publisher"], "BBC")
        self.assertGreater(ranked[0]["trend_score"], ranked[-1]["trend_score"])

    def test_google_trends_interest_boosts_relevant_headline(self):
        now = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
        items = [
            {"title": "New Artemis moon mission update", "publisher": "NASA", "published": now},
            {"title": "Local museum opens new exhibit", "publisher": "Local", "published": now},
        ]
        signals = [{"text": "Artemis moon mission", "geo": "US", "source": "google_trends"}]
        ranked = worker.rank_trending_news(items, now, signals)
        self.assertEqual(ranked[0]["title"], "New Artemis moon mission update")
        self.assertEqual(ranked[0]["google_trends_matches"], 1)

    def test_news_seo_and_tags_are_relevant_and_bounded(self):
        seo_title, description = worker.build_news_seo(
            "NASA Artemis mission discovers lunar ice",
            "NASA reports new evidence of lunar ice in the Artemis mission.",
            "Science"
        )
        tags = worker.build_news_tags(
            "NASA Artemis mission discovers lunar ice",
            "Science",
            "NASA"
        )
        self.assertLessEqual(len(seo_title), 70)
        self.assertLessEqual(len(description), 155)
        self.assertIn("Science", seo_title)
        self.assertIn("NASA", tags)
        self.assertIn("Artemis", tags)
        self.assertLessEqual(len(tags), 10)

    def test_tie_break_is_stable(self):
        now = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
        items = [
            {"title": "Single source art exhibition", "publisher": "A", "published": now},
            {"title": "Single source sports exhibition", "publisher": "B", "published": now},
        ]
        ranked = worker.rank_trending_news(items, now)
        self.assertEqual([item["publisher"] for item in ranked], ["A", "B"])



    def test_related_internal_links_only_use_relevant_existing_articles(self):
        markup = worker.build_related_internal_links(
            "NASA Artemis mission discovers lunar ice", "Science",
            [
                {"title": "Artemis mission reveals new lunar findings", "url": "https://valutednews.com/blogs/news/artemis-lunar-findings", "body": "<strong>Science</strong>"},
                {"title": "Football club wins local cup", "url": "https://valutednews.com/blogs/news/football-cup", "body": "<strong>Sports</strong>"},
            ],
        )
        self.assertIn("artemis-lunar-findings", markup)
        self.assertNotIn("football-cup", markup)
        self.assertIn("Related coverage", markup)

    @patch.object(worker, "shopify_graphql")
    @patch.dict(os.environ, {"SHOPIFY_STORE_DOMAIN": "wzn96t-cc.myshopify.com"}, clear=False)
    def test_existing_story_internal_links_use_public_domain_not_admin_host(self, graphql_mock):
        graphql_mock.return_value = {
            "blog": {
                "handle": "news",
                "articles": {"nodes": [
                    {"title": "Artemis mission reveals new lunar findings",
                     "handle": "artemis-lunar-findings",
                     "body": "<strong>Science</strong>"}
                ]}
            }
        }
        _, _, related = worker.load_existing_shopify_story_index("gid://shopify/Blog/1")
        self.assertEqual(len(related), 1)
        self.assertEqual(
            related[0]["url"],
            "https://valutednews.com/blogs/news/artemis-lunar-findings",
        )
        self.assertNotIn("myshopify.com", related[0]["url"])

    def test_news_article_jsonld_contains_required_fields(self):
        markup = worker.build_news_jsonld(
            "NASA Artemis mission discovers lunar ice",
            "NASA reports evidence of lunar ice.", "Science",
            "https://images.example.com/moon.jpg",
            datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc),
        )
        self.assertIn('type="application/ld+json"', markup)
        payload = json.loads(markup.split(">", 1)[1].rsplit("</script>", 1)[0])
        self.assertEqual(payload["@type"], "NewsArticle")
        self.assertEqual(payload["datePublished"], "2026-11-02T12:00:00+00:00")
        self.assertEqual(payload["image"], ["https://images.example.com/moon.jpg"])
        self.assertEqual(payload["publisher"]["name"], "VALUTED NEWS")
        self.assertEqual(payload["publisher"]["url"], "https://valutednews.com/")
        self.assertIn("Artemis", payload["keywords"])
        self.assertIn("Science", payload["keywords"])

    @patch.object(worker, "shopify_graphql")
    def test_news_article_includes_concise_seo_metadata(self, graphql_mock):
        graphql_mock.return_value = {"articleCreate": {"article": {"id": "gid://shopify/Article/1", "title": "Global science breakthrough", "handle": "global-science-breakthrough", "isPublished": True}, "userErrors": []}}
        article = worker.create_shopify_article(
            "gid://shopify/Blog/1",
            "Global science breakthrough",
            "Researchers announced a new discovery with significant implications.",
            "<p>Source-attributed reporting text.</p>",
            "https://example.com/story",
            "Example Publisher",
            "Science",
            True,
            "https://images.example.com/story.jpg",
        )
        payload = graphql_mock.call_args.args[1]["article"]
        self.assertLessEqual(len(payload["title"]), 120)
        self.assertLessEqual(len(payload["summary"]), 300)
        seo_fields = {item["key"]: item["value"] for item in payload["metafields"]}
        self.assertLessEqual(len(seo_fields["title_tag"]), 70)
        self.assertLessEqual(len(seo_fields["description_tag"]), 155)
        self.assertEqual({item["namespace"] for item in payload["metafields"]}, {"global"})
        self.assertIn("Valuted News", payload["tags"])
        self.assertIn("Science", payload["tags"])
        self.assertIn("Global", payload["tags"])
        self.assertEqual(article["isPublished"], True)




class YouTubeEmbedPlaybackTests(unittest.TestCase):
    @patch("news_worker.requests.get")
    def test_rejects_embed_when_youtube_player_says_video_unavailable(self, get_mock):
        import news_worker
        metadata = Mock(ok=True)
        metadata.json.return_value = {"title": "Test video"}
        player = Mock(ok=True, text="Video unavailable")
        get_mock.side_effect = [metadata, player]
        self.assertFalse(news_worker.youtube_embed_is_available("AbCdEf12345"))

    @patch("news_worker.requests.get")
    def test_accepts_embed_when_metadata_and_player_are_available(self, get_mock):
        import news_worker
        metadata = Mock(ok=True)
        metadata.json.return_value = {"title": "Test video"}
        player = Mock(ok=True, text="<html><body>yt player</body></html>")
        get_mock.side_effect = [metadata, player]
        self.assertTrue(news_worker.youtube_embed_is_available("AbCdEf12345"))

    @patch("news_worker.requests.get")
    def test_rejects_embed_when_metadata_is_unavailable(self, get_mock):
        import news_worker
        metadata = Mock(ok=False)
        get_mock.return_value = metadata
        self.assertFalse(news_worker.youtube_embed_is_available("AbCdEf12345"))




if __name__ == "__main__":
    unittest.main()
