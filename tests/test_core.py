# -*- coding: utf-8 -*-

import json
import os
import sys
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import song_credit_core as core


class SearchParsingTests(unittest.TestCase):
    def test_parse_search_response(self):
        payload = {
            "recordings": [
                {
                    "id": "recording-1",
                    "title": "テスト曲",
                    "score": "98",
                    "first-release-date": "2024-01-02",
                    "artist-credit": [
                        {"name": "Singer A", "joinphrase": " & "},
                        {"artist": {"name": "Singer B"}},
                    ],
                    "releases": [{"title": "テストアルバム"}],
                }
            ]
        }
        results = core.parse_search_response(payload)
        self.assertEqual(1, len(results))
        self.assertEqual("テスト曲", results[0]["title"])
        self.assertEqual("Singer A & Singer B", results[0]["artist"])
        self.assertEqual(98, results[0]["score"])

    def test_parse_search_page_preserves_total_and_offset(self):
        payload = {
            "count": 123,
            "offset": 20,
            "recordings": [
                {
                    "id": "recording-2",
                    "title": "次のページ",
                    "artist-credit": [{"name": "Singer"}],
                }
            ],
        }
        page = core.parse_search_page(payload)
        self.assertEqual(123, page["count"])
        self.assertEqual(20, page["offset"])
        self.assertEqual("次のページ", page["items"][0]["title"])

    def test_artist_candidates_are_unique_and_keep_result_order(self):
        values = core.artist_candidates(
            [
                {"artist": "Singer B"},
                {"artist": "Singer A"},
                {"artist": "singer b"},
                {"artist": ""},
            ]
        )
        self.assertEqual(["Singer B", "Singer A"], values)

    def test_search_page_uses_limit_and_offset(self):
        client = core.MusicBrainzClient()
        captured = {}

        def fake_request(path, params):
            captured["path"] = path
            captured["params"] = params
            return {"count": 60, "offset": 20, "recordings": []}

        client._request_json = fake_request
        page = client.search_recordings_page("テスト曲", "歌手", limit=20, offset=20)
        self.assertEqual(60, page["count"])
        self.assertEqual(20, captured["params"]["limit"])
        self.assertEqual(20, captured["params"]["offset"])
        self.assertIn('artist:"歌手"', captured["params"]["query"])


class CreditParsingTests(unittest.TestCase):
    def test_parse_credit_roles(self):
        recording = {
            "id": "recording-1",
            "title": "テスト曲",
            "artist-credit": [{"name": "Singer"}],
            "relations": [
                {"type": "recording of", "work": {"id": "work-1", "title": "テスト曲"}},
                {"type": "arranger", "artist": {"name": "Arrange Person"}},
            ],
        }
        works = [
            {
                "id": "work-1",
                "title": "テスト曲",
                "relations": [
                    {"type": "lyricist", "artist": {"name": "Lyric Person"}},
                    {"type": "composer", "artist": {"name": "Music Person"}},
                ],
            }
        ]
        result = core.parse_credit_payload(recording, works)
        self.assertEqual(["Lyric Person"], result["lyricists"])
        self.assertEqual(["Music Person"], result["composers"])
        self.assertEqual(["Arrange Person"], result["arrangers"])
        self.assertEqual("recording-1", result["source_id"])

    def test_recording_artist_credit_is_preserved(self):
        recording = {
            "id": "recording-artist",
            "title": "Artist Credit Test",
            "artist-credit": [
                {"name": "Artist A", "joinphrase": " feat. "},
                {"name": "Artist B", "joinphrase": ""},
            ],
            "relations": [],
        }
        result = core.parse_credit_payload(recording, [])
        self.assertEqual("Artist A feat. Artist B", result["artist"])

    def test_writer_is_not_silently_mislabelled(self):
        recording = {
            "id": "recording-2",
            "title": "Role Unknown",
            "artist-credit": [{"name": "Singer"}],
            "relations": [],
        }
        works = [
            {
                "id": "work-2",
                "relations": [{"type": "writer", "artist": {"name": "Writer Person"}}],
            }
        ]
        result = core.parse_credit_payload(recording, works)
        self.assertEqual([], result["lyricists"])
        self.assertEqual([], result["composers"])
        self.assertEqual(["Writer Person"], result["writers"])
        self.assertTrue(result["notes"])


class FormattingTests(unittest.TestCase):
    def setUp(self):
        self.record = {
            "title": "テスト曲",
            "artist": "Singer",
            "lyricists": ["Lyric Person"],
            "composers": ["Music Person"],
            "arrangers": ["Arrange Person"],
            "writers": [],
        }

    def test_japanese_format(self):
        value = core.format_credits(self.record, "jp")
        self.assertEqual("作詞：Lyric Person　作曲：Music Person　編曲：Arrange Person", value)

    def test_compact_format(self):
        value = core.format_credits(self.record, "compact")
        self.assertEqual("詞 Lyric Person / 曲 Music Person / 編 Arrange Person", value)


class HistoryTests(unittest.TestCase):
    def test_history_is_utf8_and_deduplicated(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "history.json")
            record = {
                "title": "日本語タイトル",
                "artist": "歌手",
                "source_id": "mb-id-1",
            }
            core.upsert_history(record, path=path)
            updated = dict(record)
            updated["artist"] = "更新後の歌手"
            core.upsert_history(updated, path=path)

            items = core.load_history(path)
            self.assertEqual(1, len(items))
            self.assertEqual("更新後の歌手", items[0]["artist"])
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            self.assertEqual(1, payload["version"])


class SetlistTests(unittest.TestCase):
    def test_setlists_are_saved_loaded_and_listed_as_utf8_json(self):
        with tempfile.TemporaryDirectory() as directory:
            items = [
                {
                    "title": "祝福",
                    "artist": "YOASOBI",
                    "lyricists": ["Ayase"],
                    "composers": ["Ayase"],
                }
            ]
            path = core.save_setlist("歌枠その1", items, directory)
            self.assertTrue(os.path.exists(path))
            loaded = core.load_setlist("歌枠その1", directory)
            self.assertEqual("歌枠その1", loaded["name"])
            self.assertEqual("祝福", loaded["items"][0]["title"])
            self.assertEqual(["歌枠その1"], core.list_setlists(directory))
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            self.assertEqual("歌枠その1", payload["name"])

    def test_setlist_filename_is_safe_and_empty_name_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = core.save_setlist("日曜/夜:歌枠", [], directory)
            self.assertEqual("日曜_夜_歌枠.json", os.path.basename(path))
            with self.assertRaises(core.SongCreditError):
                core.save_setlist("   ", [], directory)


if __name__ == "__main__":
    unittest.main()
