# -*- coding: utf-8 -*-
"""OBS Studio script: search song credits and display them in text sources."""

import os
import sys

import obspython as obs


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import song_credit_core as core


KEY_QUERY_TITLE = "query_title"
KEY_QUERY_ARTIST = "query_artist"
KEY_CANDIDATE = "candidate_id"
KEY_TITLE = "display_title"
KEY_ARTIST = "display_artist"
KEY_LYRICISTS = "display_lyricists"
KEY_COMPOSERS = "display_composers"
KEY_ARRANGERS = "display_arrangers"
KEY_WRITERS = "display_writers"
KEY_SOURCE_ID = "musicbrainz_recording_id"
KEY_NOTES = "credit_notes"
KEY_TITLE_SOURCE = "title_source"
KEY_ARTIST_SOURCE = "artist_source"
KEY_CREDIT_SOURCE = "credit_source"
KEY_FORMAT = "credit_format"
KEY_SAVE_HISTORY = "save_history"
KEY_AUTO_LAYOUT = "auto_lower_third_layout"
KEY_LAYOUT_APPLIED = "lower_third_layout_applied"
KEY_HISTORY = "history_key"
KEY_STATUS = "status_message"
KEY_SHOW_HOTKEY = "show_hotkey"
KEY_HIDE_HOTKEY = "hide_hotkey"


_settings = None
_client = core.MusicBrainzClient()
_search_results = []
_history = []
_show_hotkey_id = obs.OBS_INVALID_HOTKEY_ID
_hide_hotkey_id = obs.OBS_INVALID_HOTKEY_ID

_state = {
    KEY_QUERY_TITLE: "",
    KEY_QUERY_ARTIST: "",
    KEY_CANDIDATE: "",
    KEY_TITLE: "",
    KEY_ARTIST: "",
    KEY_LYRICISTS: "",
    KEY_COMPOSERS: "",
    KEY_ARRANGERS: "",
    KEY_WRITERS: "",
    KEY_SOURCE_ID: "",
    KEY_NOTES: "",
    KEY_TITLE_SOURCE: "",
    KEY_ARTIST_SOURCE: "",
    KEY_CREDIT_SOURCE: "",
    KEY_FORMAT: "jp",
    KEY_SAVE_HISTORY: True,
    KEY_AUTO_LAYOUT: True,
    KEY_LAYOUT_APPLIED: False,
    KEY_HISTORY: "",
}


LOWER_THIRD_LAYOUT = {
    "title": {"position": (160.0, 650.0), "bounds": (1600.0, 90.0)},
    "artist": {"position": (160.0, 760.0), "bounds": (1600.0, 60.0)},
    "credits": {"position": (160.0, 850.0), "bounds": (1600.0, 100.0)},
}
SCENE_ITEM_ALIGN_TOP_LEFT = 5  # OBS_ALIGN_LEFT (1) | OBS_ALIGN_TOP (4)
SCENE_ITEM_BOUNDS_SCALE_INNER = 2


def _log(level, message):
    obs.script_log(level, "[Song Credit Overlay] " + str(message))


def _set_status(message):
    if _settings is not None:
        obs.obs_data_set_string(_settings, KEY_STATUS, message)
    _log(obs.LOG_INFO, message)


def _set_string(key, value):
    value = value or ""
    _state[key] = value
    if _settings is not None:
        obs.obs_data_set_string(_settings, key, value)


def _set_bool(key, value):
    value = bool(value)
    _state[key] = value
    if _settings is not None:
        obs.obs_data_set_bool(_settings, key, value)


def _set_record_fields(record):
    _set_string(KEY_TITLE, record.get("title") or "")
    _set_string(KEY_ARTIST, record.get("artist") or "")
    _set_string(KEY_LYRICISTS, "、".join(record.get("lyricists") or []))
    _set_string(KEY_COMPOSERS, "、".join(record.get("composers") or []))
    _set_string(KEY_ARRANGERS, "、".join(record.get("arrangers") or []))
    _set_string(KEY_WRITERS, "、".join(record.get("writers") or []))
    _set_string(KEY_SOURCE_ID, record.get("source_id") or "")
    _set_string(KEY_NOTES, "\n".join(record.get("notes") or []))


def _split_people(value):
    normalized = (value or "").replace(",", "、").replace("/", "、")
    return [part.strip() for part in normalized.split("、") if part.strip()]


def _current_record():
    return {
        "title": _state[KEY_TITLE].strip(),
        "artist": _state[KEY_ARTIST].strip(),
        "lyricists": _split_people(_state[KEY_LYRICISTS]),
        "composers": _split_people(_state[KEY_COMPOSERS]),
        "arrangers": _split_people(_state[KEY_ARRANGERS]),
        "writers": _split_people(_state[KEY_WRITERS]),
        "notes": [line for line in _state[KEY_NOTES].splitlines() if line.strip()],
        "source": "musicbrainz" if _state[KEY_SOURCE_ID] else "manual",
        "source_id": _state[KEY_SOURCE_ID].strip(),
        "source_url": (
            "https://musicbrainz.org/recording/" + _state[KEY_SOURCE_ID].strip()
            if _state[KEY_SOURCE_ID].strip()
            else ""
        ),
        "verified": bool(
            _state[KEY_TITLE].strip()
            and (_state[KEY_LYRICISTS].strip() or _state[KEY_COMPOSERS].strip())
        ),
    }


def _refresh_history():
    global _history
    try:
        _history = core.load_history()
    except core.SongCreditError as exc:
        _history = []
        _set_status(str(exc))


def _text_sources():
    names = []
    sources = obs.obs_enum_sources()
    if sources is None:
        return names
    try:
        for source in sources:
            source_id = obs.obs_source_get_unversioned_id(source) or ""
            if source_id in ("text_gdiplus", "text_ft2_source"):
                names.append(obs.obs_source_get_name(source))
    finally:
        obs.source_list_release(sources)
    return sorted(set(names), key=lambda value: value.casefold())


def _add_string_list(props, key, label, items, empty_label=None):
    prop = obs.obs_properties_add_list(
        props, key, label, obs.OBS_COMBO_TYPE_LIST, obs.OBS_COMBO_FORMAT_STRING
    )
    if empty_label is not None:
        obs.obs_property_list_add_string(prop, empty_label, "")
    for item_label, item_value in items:
        obs.obs_property_list_add_string(prop, item_label, item_value)
    return prop


def _candidate_label(candidate):
    details = []
    if candidate.get("date"):
        details.append(candidate["date"])
    if candidate.get("release"):
        details.append(candidate["release"])
    if candidate.get("disambiguation"):
        details.append(candidate["disambiguation"])
    suffix = " / ".join(details)
    label = "{} — {}".format(
        candidate.get("title") or "タイトルなし",
        candidate.get("artist") or "アーティスト不明",
    )
    if suffix:
        label += " ({})".format(suffix)
    return label


def _refresh_candidate_property(props):
    """Refresh the existing search result combo without reopening the dialog."""
    candidate_prop = obs.obs_properties_get(props, KEY_CANDIDATE)
    if candidate_prop is None:
        return
    obs.obs_property_list_clear(candidate_prop)
    if not _search_results:
        obs.obs_property_list_add_string(candidate_prop, "候補なし", "")
        return
    for item in _search_results:
        obs.obs_property_list_add_string(candidate_prop, _candidate_label(item), item["id"])


def _refresh_history_property(props):
    """Refresh the existing history combo after saving a displayed song."""
    history_prop = obs.obs_properties_get(props, KEY_HISTORY)
    if history_prop is None:
        return
    obs.obs_property_list_clear(history_prop)
    if not _history:
        obs.obs_property_list_add_string(history_prop, "履歴なし", "")
        return
    for item in _history:
        obs.obs_property_list_add_string(
            history_prop, core.record_label(item), core.history_key(item)
        )


def _on_search_clicked(props, prop):
    global _search_results
    try:
        _set_status("MusicBrainzを検索しています…")
        _search_results = _client.search_recordings(
            _state[KEY_QUERY_TITLE], _state[KEY_QUERY_ARTIST]
        )
        selected = _search_results[0]["id"] if _search_results else ""
        _set_string(KEY_CANDIDATE, selected)
        _refresh_candidate_property(props)
        if _search_results:
            _set_status("{}件の候補が見つかりました。候補を選択してください。".format(len(_search_results)))
        else:
            _set_status("候補が見つかりませんでした。検索語を変えるか手動入力してください。")
    except Exception as exc:
        _search_results = []
        _set_string(KEY_CANDIDATE, "")
        _refresh_candidate_property(props)
        _set_status("検索エラー: {}".format(exc))
        _log(obs.LOG_WARNING, repr(exc))
    return True


def _on_load_candidate_clicked(props, prop):
    selected_id = _state[KEY_CANDIDATE]
    if not selected_id:
        _set_status("楽曲候補を選択してください。")
        return True
    try:
        _set_status("クレジットを取得しています…")
        record = _client.fetch_credits(selected_id)
        _set_record_fields(record)
        if record.get("notes"):
            _set_status("取得しました。注意事項を確認し、必要なら修正してください。")
        else:
            _set_status("クレジットを取得しました。内容を確認して表示してください。")
    except Exception as exc:
        _set_status("クレジット取得エラー: {}".format(exc))
        _log(obs.LOG_WARNING, repr(exc))
    return True


def _find_history_item(key):
    for item in _history:
        if core.history_key(item) == key:
            return item
    return None


def _on_load_history_clicked(props, prop):
    item = _find_history_item(_state[KEY_HISTORY])
    if item is None:
        _set_status("履歴から楽曲を選択してください。")
        return True
    _set_record_fields(item)
    _set_status("履歴から「{}」を読み込みました。".format(item.get("title") or ""))
    return True


def _update_text_source(source_name, text):
    source = obs.obs_get_source_by_name(source_name)
    if source is None:
        return "ソース「{}」が見つかりません。".format(source_name)
    try:
        settings = obs.obs_data_create()
        try:
            obs.obs_data_set_string(settings, "text", text)
            obs.obs_source_update(source, settings)
        finally:
            obs.obs_data_release(settings)
    finally:
        obs.obs_source_release(source)
    return None


def _selected_output_sources():
    return [
        (_state[KEY_TITLE_SOURCE], "title"),
        (_state[KEY_ARTIST_SOURCE], "artist"),
        (_state[KEY_CREDIT_SOURCE], "credits"),
    ]


def _apply_lower_third_layout():
    """Place selected text sources in a safe lower-third area for 1920x1080 scenes."""
    selected = [(name, key) for name, key in _selected_output_sources() if name]
    if not selected:
        return False, "出力先のテキストソースを選択してください。"

    scene_source = obs.obs_frontend_get_current_scene()
    if scene_source is None:
        return False, "現在のシーンを取得できません。"
    try:
        scene = obs.obs_scene_from_source(scene_source)
        if scene is None:
            return False, "現在のシーンを取得できません。"

        finder = getattr(obs, "obs_scene_find_source_recursive", None)
        if finder is None:
            finder = obs.obs_scene_find_source

        errors = []
        scene_items = []
        for source_name, output_key in selected:
            item = finder(scene, source_name)
            if item is None:
                errors.append("「{}」が現在のシーンにありません。".format(source_name))
                continue
            scene_items.append((item, output_key))

        if errors:
            return False, " ".join(errors)

        for item, output_key in scene_items:
            scale = obs.vec2()
            scale.x = 1.0
            scale.y = 1.0
            position = obs.vec2()
            position.x, position.y = LOWER_THIRD_LAYOUT[output_key]["position"]
            bounds = obs.vec2()
            bounds.x, bounds.y = LOWER_THIRD_LAYOUT[output_key]["bounds"]

            obs.obs_sceneitem_set_scale(item, scale)
            obs.obs_sceneitem_set_rot(item, 0.0)
            obs.obs_sceneitem_set_alignment(item, SCENE_ITEM_ALIGN_TOP_LEFT)
            obs.obs_sceneitem_set_bounds_type(item, SCENE_ITEM_BOUNDS_SCALE_INNER)
            obs.obs_sceneitem_set_bounds_alignment(item, SCENE_ITEM_ALIGN_TOP_LEFT)
            obs.obs_sceneitem_set_bounds(item, bounds)
            obs.obs_sceneitem_set_pos(item, position)

    finally:
        obs.obs_source_release(scene_source)
    return True, ""


def _on_apply_layout_clicked(props, prop):
    applied, error = _apply_lower_third_layout()
    if not applied:
        _set_status("下部配置エラー: " + error)
        return True
    _set_bool(KEY_LAYOUT_APPLIED, True)
    _set_status("出力先を1920×1080の下部へ配置しました。")
    return True


def _show_overlay(save_to_history=True):
    global _history
    record = _current_record()
    if not record["title"]:
        _set_status("表示するタイトルを入力してください。")
        return False

    selected = [(name, key) for name, key in _selected_output_sources() if name]
    if not selected:
        _set_status("出力先のテキストソースを1つ以上選択してください。")
        return False
    names = [name for name, unused in selected]
    if len(names) != len(set(names)):
        _set_status("同じテキストソースを複数の出力先に指定できません。")
        return False

    outputs = core.build_outputs(record, _state[KEY_FORMAT])
    errors = []
    for source_name, output_key in selected:
        error = _update_text_source(source_name, outputs[output_key])
        if error:
            errors.append(error)
    if errors:
        _set_status(" ".join(errors))
        return False

    layout_message = ""
    if _state[KEY_AUTO_LAYOUT] and not _state[KEY_LAYOUT_APPLIED]:
        applied, layout_error = _apply_lower_third_layout()
        if applied:
            _set_bool(KEY_LAYOUT_APPLIED, True)
            layout_message = " 1920×1080の下部へ配置しました。"
        else:
            layout_message = " 下部配置はできませんでした: {}".format(layout_error)

    if save_to_history and _state[KEY_SAVE_HISTORY]:
        try:
            _history = core.upsert_history(record)
        except core.SongCreditError as exc:
            _set_status("表示しましたが、履歴保存に失敗しました: {}".format(exc))
            return True
    _set_status("「{}」をOBSへ表示しました。{}".format(record["title"], layout_message))
    return True


def _hide_overlay():
    selected = [(name, key) for name, key in _selected_output_sources() if name]
    if not selected:
        _set_status("出力先のテキストソースを選択してください。")
        return False
    errors = []
    for source_name, unused in selected:
        error = _update_text_source(source_name, "")
        if error:
            errors.append(error)
    if errors:
        _set_status(" ".join(errors))
        return False
    _set_status("楽曲クレジットを非表示にしました。")
    return True


def _on_show_clicked(props, prop):
    if _show_overlay(True):
        if _history:
            _set_string(KEY_HISTORY, core.history_key(_history[0]))
        _refresh_history_property(props)
    return True


def _on_hide_clicked(props, prop):
    _hide_overlay()
    return True


def _on_show_hotkey(pressed):
    if pressed:
        _show_overlay(True)


def _on_hide_hotkey(pressed):
    if pressed:
        _hide_overlay()


def script_description():
    return (
        "<b>Song Credit Overlay 0.1.2</b><br>"
        "MusicBrainzで楽曲を検索し、曲名・アーティスト・作詞／作曲／編曲を "
        "OBSの専用テキストソースへ表示します。検索結果は必ず確認し、必要に応じて修正してください。"
    )


def script_defaults(settings):
    obs.obs_data_set_default_string(settings, KEY_QUERY_TITLE, "")
    obs.obs_data_set_default_string(settings, KEY_QUERY_ARTIST, "")
    obs.obs_data_set_default_string(settings, KEY_FORMAT, "jp")
    obs.obs_data_set_default_bool(settings, KEY_SAVE_HISTORY, True)
    obs.obs_data_set_default_bool(settings, KEY_AUTO_LAYOUT, True)
    obs.obs_data_set_default_bool(settings, KEY_LAYOUT_APPLIED, False)
    obs.obs_data_set_default_string(
        settings, KEY_STATUS, "曲名を入力して検索するか、表示内容を手動入力してください。"
    )


def script_update(settings):
    global _settings
    _settings = settings
    string_keys = [
        KEY_QUERY_TITLE,
        KEY_QUERY_ARTIST,
        KEY_CANDIDATE,
        KEY_TITLE,
        KEY_ARTIST,
        KEY_LYRICISTS,
        KEY_COMPOSERS,
        KEY_ARRANGERS,
        KEY_WRITERS,
        KEY_SOURCE_ID,
        KEY_NOTES,
        KEY_TITLE_SOURCE,
        KEY_ARTIST_SOURCE,
        KEY_CREDIT_SOURCE,
        KEY_FORMAT,
        KEY_HISTORY,
    ]
    for key in string_keys:
        _state[key] = obs.obs_data_get_string(settings, key) or ""
    _state[KEY_SAVE_HISTORY] = obs.obs_data_get_bool(settings, KEY_SAVE_HISTORY)
    _state[KEY_AUTO_LAYOUT] = obs.obs_data_get_bool(settings, KEY_AUTO_LAYOUT)
    _state[KEY_LAYOUT_APPLIED] = obs.obs_data_get_bool(settings, KEY_LAYOUT_APPLIED)


def script_properties():
    props = obs.obs_properties_create()

    obs.obs_properties_add_text(props, KEY_QUERY_TITLE, "検索する曲名", obs.OBS_TEXT_DEFAULT)
    obs.obs_properties_add_text(
        props, KEY_QUERY_ARTIST, "アーティスト（任意）", obs.OBS_TEXT_DEFAULT
    )
    obs.obs_properties_add_button(props, "search_button", "MusicBrainzを検索", _on_search_clicked)

    candidates = [(_candidate_label(item), item["id"]) for item in _search_results]
    _add_string_list(props, KEY_CANDIDATE, "検索候補", candidates, "候補なし")
    obs.obs_properties_add_button(
        props, "load_candidate_button", "選択候補のクレジットを取得", _on_load_candidate_clicked
    )

    obs.obs_properties_add_text(props, KEY_TITLE, "表示タイトル", obs.OBS_TEXT_DEFAULT)
    obs.obs_properties_add_text(props, KEY_ARTIST, "表示アーティスト", obs.OBS_TEXT_DEFAULT)
    obs.obs_properties_add_text(props, KEY_LYRICISTS, "作詞（複数は「、」区切り）", obs.OBS_TEXT_DEFAULT)
    obs.obs_properties_add_text(props, KEY_COMPOSERS, "作曲（複数は「、」区切り）", obs.OBS_TEXT_DEFAULT)
    obs.obs_properties_add_text(props, KEY_ARRANGERS, "編曲（複数は「、」区切り）", obs.OBS_TEXT_DEFAULT)
    obs.obs_properties_add_text(
        props, KEY_WRITERS, "Writer／役割未確定（要確認）", obs.OBS_TEXT_DEFAULT
    )
    obs.obs_properties_add_text(props, KEY_NOTES, "確認事項", obs.OBS_TEXT_MULTILINE)

    sources = [(name, name) for name in _text_sources()]
    _add_string_list(props, KEY_TITLE_SOURCE, "曲名の出力先", sources, "使用しない")
    _add_string_list(props, KEY_ARTIST_SOURCE, "アーティストの出力先", sources, "使用しない")
    _add_string_list(props, KEY_CREDIT_SOURCE, "クレジットの出力先", sources, "使用しない")
    obs.obs_properties_add_bool(
        props, KEY_AUTO_LAYOUT, "初回表示時に1920×1080の下部へ自動配置"
    )
    obs.obs_properties_add_button(
        props,
        "apply_lower_third_layout_button",
        "出力先を1920×1080の下部へ配置し直す",
        _on_apply_layout_clicked,
    )

    formats = [("日本語", "jp"), ("English", "en"), ("コンパクト", "compact")]
    _add_string_list(props, KEY_FORMAT, "クレジット表記", formats)
    obs.obs_properties_add_bool(props, KEY_SAVE_HISTORY, "表示時に履歴へ保存")

    obs.obs_properties_add_button(props, "show_button", "OBSへ表示", _on_show_clicked)
    obs.obs_properties_add_button(props, "hide_button", "非表示（出力先を空にする）", _on_hide_clicked)

    history_items = [(core.record_label(item), core.history_key(item)) for item in _history]
    _add_string_list(props, KEY_HISTORY, "最近使った楽曲", history_items, "履歴なし")
    obs.obs_properties_add_button(
        props, "load_history_button", "選択した履歴を読み込む", _on_load_history_clicked
    )

    obs.obs_properties_add_text(props, KEY_STATUS, "状態", obs.OBS_TEXT_INFO)
    return props


def script_load(settings):
    global _show_hotkey_id, _hide_hotkey_id
    _refresh_history()
    _show_hotkey_id = obs.obs_hotkey_register_frontend(
        "song_credit_overlay.show", "楽曲クレジット: 表示", _on_show_hotkey
    )
    _hide_hotkey_id = obs.obs_hotkey_register_frontend(
        "song_credit_overlay.hide", "楽曲クレジット: 非表示", _on_hide_hotkey
    )

    show_array = obs.obs_data_get_array(settings, KEY_SHOW_HOTKEY)
    hide_array = obs.obs_data_get_array(settings, KEY_HIDE_HOTKEY)
    try:
        obs.obs_hotkey_load(_show_hotkey_id, show_array)
        obs.obs_hotkey_load(_hide_hotkey_id, hide_array)
    finally:
        obs.obs_data_array_release(show_array)
        obs.obs_data_array_release(hide_array)


def script_save(settings):
    show_array = obs.obs_hotkey_save(_show_hotkey_id)
    hide_array = obs.obs_hotkey_save(_hide_hotkey_id)
    try:
        obs.obs_data_set_array(settings, KEY_SHOW_HOTKEY, show_array)
        obs.obs_data_set_array(settings, KEY_HIDE_HOTKEY, hide_array)
    finally:
        obs.obs_data_array_release(show_array)
        obs.obs_data_array_release(hide_array)
