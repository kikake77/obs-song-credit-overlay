import csv
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import song_credit_core as core
import song_credit_manager_core as manager_core


class ManagerSetlistTests(unittest.TestCase):
    def test_manager_file_is_readable_by_existing_core(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "配信テスト.json")
            manager_core.save_setlist_file(
                path,
                "配信テスト",
                [
                    {
                        "title": "祝福",
                        "artist": "YOASOBI",
                        "lyricists": ["Ayase"],
                        "composers": ["Ayase"],
                    }
                ],
            )
            loaded = core.load_setlist("配信テスト", directory)
            self.assertEqual("祝福", loaded["items"][0]["title"])
            self.assertEqual(["Ayase"], loaded["items"][0]["lyricists"])

    def test_document_can_add_update_move_remove_and_save(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "歌枠.scolist.json")
            document = manager_core.SetlistDocument("歌枠")
            first = document.add({"title": "一曲目", "artist": "歌手A"})
            second = document.add({"title": "二曲目", "artist": "歌手B"})
            self.assertEqual((0, 1), (first, second))
            self.assertTrue(document.dirty)
            self.assertEqual(0, document.move(1, -1))
            document.update(0, {"title": "二曲目・修正版", "artist": "歌手B"})
            removed = document.remove(1)
            self.assertEqual("一曲目", removed["title"])
            document.save(path)
            self.assertFalse(document.dirty)

            loaded = manager_core.SetlistDocument.load(path)
            self.assertEqual("歌枠", loaded.name)
            self.assertEqual(["二曲目・修正版"], [item["title"] for item in loaded.items])

    def test_csv_and_text_import_are_human_friendly(self):
        with tempfile.TemporaryDirectory() as directory:
            csv_path = os.path.join(directory, "夏歌枠.csv")
            with open(csv_path, "w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["順番", "曲名", "アーティスト", "作詞", "作曲", "編曲", "メモ"])
                writer.writerow([1, "夜に駆ける", "YOASOBI", "Ayase", "Ayase", "Ayase", "キー-2"])
            csv_payload = manager_core.load_setlist_file(csv_path)
            self.assertEqual("夜に駆ける", csv_payload["items"][0]["title"])
            self.assertEqual(["Ayase"], csv_payload["items"][0]["composers"])
            self.assertEqual(["キー-2"], csv_payload["items"][0]["notes"])

            text_path = os.path.join(directory, "リクエスト.txt")
            with open(text_path, "w", encoding="utf-8") as handle:
                handle.write("祝福 / YOASOBI\nアイドル\tYOASOBI\n")
            text_payload = manager_core.load_setlist_file(text_path)
            self.assertEqual(["祝福", "アイドル"], [item["title"] for item in text_payload["items"]])
            self.assertEqual("YOASOBI", text_payload["items"][1]["artist"])

    def test_csv_export_uses_utf8_bom_and_japanese_headers(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "export.csv")
            manager_core.export_setlist_csv(
                path,
                [{"title": "祝福", "artist": "YOASOBI", "lyricists": ["Ayase"]}],
            )
            with open(path, "rb") as handle:
                self.assertEqual(b"\xef\xbb\xbf", handle.read(3))
            with open(path, "r", encoding="utf-8-sig") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual("祝福", rows[0]["曲名"])
            self.assertEqual("Ayase", rows[0]["作詞"])


class OverlayStateTests(unittest.TestCase):
    def test_display_settings_round_trip_and_invalid_values_fall_back(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "settings.json")
            saved = manager_core.save_display_settings(
                {"theme": "light", "panel": False, "font": "mincho", "credit_style": "en"},
                path,
            )
            self.assertEqual("light", saved["theme"])
            self.assertFalse(saved["panel"])
            self.assertEqual(saved, manager_core.load_display_settings(path))

            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"theme": "unknown", "font": "comic", "credit_style": "x"}, handle)
            loaded = manager_core.load_display_settings(path)
            self.assertEqual(manager_core.DEFAULT_DISPLAY_SETTINGS, loaded)

    def test_display_settings_can_be_loaded_from_legacy_product_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            preferred = os.path.join(directory, "new", "settings.json")
            legacy = os.path.join(directory, "old", "settings.json")
            manager_core.save_display_settings(
                {"theme": "light", "panel": False, "font": "rounded", "credit_style": "compact"},
                legacy,
            )
            with mock.patch.object(manager_core, "default_settings_path", return_value=preferred), mock.patch.object(
                manager_core, "legacy_settings_path", return_value=legacy
            ):
                loaded = manager_core.load_display_settings()
            self.assertEqual("light", loaded["theme"])
            self.assertFalse(loaded["panel"])
            self.assertEqual("rounded", loaded["font"])
            self.assertEqual("compact", loaded["credit_style"])

    def test_overlay_state_can_show_and_hide(self):
        store = manager_core.OverlayStateStore(
            {"theme": "light", "panel": False, "font": "mincho"}
        )
        shown = store.show_record(
            {
                "title": "祝福",
                "artist": "YOASOBI",
                "lyricists": ["Ayase"],
                "composers": ["Ayase"],
            }
        )
        self.assertTrue(shown["visible"])
        self.assertEqual("祝福", shown["title"])
        self.assertIn("作詞：Ayase", shown["credits"])
        self.assertEqual("light", shown["theme"])
        self.assertFalse(shown["panel"])
        self.assertEqual("mincho", shown["font"])

        restyled = store.set_style(theme="dark", panel=True, font="rounded")
        self.assertEqual("dark", restyled["theme"])
        self.assertTrue(restyled["panel"])
        self.assertEqual("rounded", restyled["font"])
        self.assertTrue(restyled["visible"])
        self.assertEqual("祝福", restyled["title"])

        hidden = store.hide()
        self.assertFalse(hidden["visible"])
        self.assertGreater(hidden["sequence"], restyled["sequence"])


if __name__ == "__main__":
    unittest.main()
