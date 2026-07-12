# -*- coding: utf-8 -*-

import importlib.util
import os
import sys
import types
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class FakeSource(object):
    def __init__(self, name):
        self.name = name
        self.source_id = "text_gdiplus"
        self.settings = {"text": ""}


def build_fake_obs():
    module = types.ModuleType("obspython")
    module.OBS_INVALID_HOTKEY_ID = -1
    module.LOG_INFO = 200
    module.LOG_WARNING = 300
    module.OBS_TEXT_DEFAULT = 0
    module.OBS_TEXT_MULTILINE = 1
    module.OBS_TEXT_INFO = 2
    module.OBS_COMBO_TYPE_LIST = 0
    module.OBS_COMBO_FORMAT_STRING = 0
    module.sources = {
        name: FakeSource(name) for name in ("Song Title", "Song Artist", "Song Credits")
    }

    module.script_log = lambda level, message: None
    module.obs_data_set_default_string = lambda data, key, value: data.setdefault(key, value)
    module.obs_data_set_default_bool = lambda data, key, value: data.setdefault(key, bool(value))
    module.obs_data_get_string = lambda data, key: data.get(key, "")
    module.obs_data_get_bool = lambda data, key: bool(data.get(key, False))
    module.obs_data_set_string = lambda data, key, value: data.__setitem__(key, value)
    module.obs_properties_create = lambda: {"properties": []}

    def add_property(props, key, label, kind):
        prop = {"key": key, "label": label, "kind": kind, "items": []}
        props["properties"].append(prop)
        return prop

    module.obs_properties_add_text = (
        lambda props, key, label, style: add_property(props, key, label, "text")
    )
    module.obs_properties_add_bool = (
        lambda props, key, label: add_property(props, key, label, "bool")
    )
    module.obs_properties_add_button = (
        lambda props, key, label, callback: add_property(props, key, label, "button")
    )
    module.obs_properties_add_list = (
        lambda props, key, label, combo_type, combo_format: add_property(
            props, key, label, "list"
        )
    )
    module.obs_property_list_add_string = (
        lambda prop, label, value: prop["items"].append((label, value))
    )
    module.obs_properties_get = lambda props, key: next(
        (prop for prop in props["properties"] if prop["key"] == key), None
    )
    module.obs_property_list_clear = lambda prop: prop["items"].clear()
    module.obs_enum_sources = lambda: list(module.sources.values())
    module.source_list_release = lambda sources: None
    module.obs_source_get_unversioned_id = lambda source: source.source_id
    module.obs_source_get_name = lambda source: source.name
    module.obs_get_source_by_name = lambda name: module.sources.get(name)
    module.obs_data_create = lambda: {}
    module.obs_data_release = lambda data: None
    module.obs_source_update = lambda source, data: source.settings.update(data)
    module.obs_source_release = lambda source: None
    return module


class ObsScriptSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fake_obs = build_fake_obs()
        sys.modules["obspython"] = cls.fake_obs
        path = os.path.join(ROOT, "song_credit_overlay.py")
        spec = importlib.util.spec_from_file_location("song_credit_overlay_smoke", path)
        cls.script = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.script)

    def test_properties_can_be_built(self):
        settings = {}
        self.script.script_defaults(settings)
        self.script.script_update(settings)
        props = self.script.script_properties()
        keys = [prop["key"] for prop in props["properties"]]
        self.assertIn(self.script.KEY_QUERY_TITLE, keys)
        self.assertIn(self.script.KEY_TITLE_SOURCE, keys)
        self.assertIn("show_button", keys)

    def test_candidate_combo_can_be_refreshed_in_place(self):
        settings = {}
        self.script.script_defaults(settings)
        self.script.script_update(settings)
        props = self.script.script_properties()
        self.script._search_results = [
            {
                "id": "recording-1",
                "title": "テスト曲",
                "artist": "テスト歌手",
                "date": "2026",
                "release": "",
                "disambiguation": "",
            }
        ]
        self.script._refresh_candidate_property(props)
        candidate = self.fake_obs.obs_properties_get(props, self.script.KEY_CANDIDATE)
        self.assertEqual(1, len(candidate["items"]))
        self.assertEqual("recording-1", candidate["items"][0][1])

    def test_history_combo_can_be_refreshed_in_place(self):
        settings = {}
        self.script.script_defaults(settings)
        self.script.script_update(settings)
        props = self.script.script_properties()
        self.script._history = [
            {"title": "履歴の曲", "artist": "履歴の歌手", "source_id": "history-1"}
        ]
        self.script._refresh_history_property(props)
        history = self.fake_obs.obs_properties_get(props, self.script.KEY_HISTORY)
        self.assertEqual(1, len(history["items"]))
        self.assertEqual("mb:history-1", history["items"][0][1])

    def test_manual_record_is_written_to_three_sources(self):
        settings = {
            self.script.KEY_TITLE: "テスト曲",
            self.script.KEY_ARTIST: "テスト歌手",
            self.script.KEY_LYRICISTS: "作詞者",
            self.script.KEY_COMPOSERS: "作曲者",
            self.script.KEY_ARRANGERS: "編曲者",
            self.script.KEY_TITLE_SOURCE: "Song Title",
            self.script.KEY_ARTIST_SOURCE: "Song Artist",
            self.script.KEY_CREDIT_SOURCE: "Song Credits",
            self.script.KEY_FORMAT: "jp",
            self.script.KEY_SAVE_HISTORY: False,
        }
        self.script.script_update(settings)
        self.assertTrue(self.script._show_overlay(False))
        self.assertEqual("テスト曲", self.fake_obs.sources["Song Title"].settings["text"])
        self.assertEqual("テスト歌手", self.fake_obs.sources["Song Artist"].settings["text"])
        self.assertEqual(
            "作詞：作詞者　作曲：作曲者　編曲：編曲者",
            self.fake_obs.sources["Song Credits"].settings["text"],
        )

    def test_hide_clears_dedicated_sources(self):
        settings = {
            self.script.KEY_TITLE_SOURCE: "Song Title",
            self.script.KEY_ARTIST_SOURCE: "Song Artist",
            self.script.KEY_CREDIT_SOURCE: "Song Credits",
            self.script.KEY_FORMAT: "jp",
            self.script.KEY_SAVE_HISTORY: False,
        }
        for source in self.fake_obs.sources.values():
            source.settings["text"] = "表示中"
        self.script.script_update(settings)
        self.assertTrue(self.script._hide_overlay())
        for source in self.fake_obs.sources.values():
            self.assertEqual("", source.settings["text"])


if __name__ == "__main__":
    unittest.main()
