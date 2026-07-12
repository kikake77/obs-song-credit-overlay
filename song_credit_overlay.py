# -*- coding: utf-8 -*-
"""OBS Studio script: search song credits and display them in text sources."""

import importlib
import os
import sys

import obspython as obs


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import song_credit_core as core

core = importlib.reload(core)


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
KEY_SETLIST_LIBRARY = "setlist_library"
KEY_SETLIST_NAME = "setlist_name"
KEY_SETLIST_SONG = "setlist_song_index"
KEY_SETLIST_SUMMARY = "setlist_summary"
KEY_NOW_PLAYING = "now_playing"
KEY_STATUS = "status_message"
KEY_SHOW_HOTKEY = "show_hotkey"
KEY_HIDE_HOTKEY = "hide_hotkey"


_settings = None
_client = core.MusicBrainzClient()
_search_results = []
_history = []
_setlist_names = []
_active_setlist = {"name": "", "items": []}
_active_setlist_index = -1
_ui_props = {}
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
    KEY_SETLIST_LIBRARY: "",
    KEY_SETLIST_NAME: "",
    KEY_SETLIST_SONG: "",
    KEY_SETLIST_SUMMARY: "セットリスト未選択",
    KEY_NOW_PLAYING: "まだ表示していません",
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


def _refresh_setlist_names():
    global _setlist_names
    try:
        _setlist_names = core.list_setlists()
    except core.SongCreditError as exc:
        _setlist_names = []
        _set_status(str(exc))


def _setlist_index():
    try:
        index = int(_state[KEY_SETLIST_SONG])
    except (TypeError, ValueError):
        return -1
    return index if 0 <= index < len(_active_setlist["items"]) else -1


def _update_setlist_summary():
    count = len(_active_setlist["items"])
    index = _setlist_index()
    if not _active_setlist["name"]:
        message = "セットリスト未選択"
    elif count == 0:
        message = "{}：0曲（曲を検索して追加してください）".format(_active_setlist["name"])
    else:
        position = index + 1 if index >= 0 else 0
        message = "{}：{}曲／選択 {}曲目".format(_active_setlist["name"], count, position)
    _set_string(KEY_SETLIST_SUMMARY, message)


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
    if props is None:
        return
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


def _refresh_setlist_properties():
    live_props = _ui_props.get("live")
    if live_props is None:
        return
    library_prop = obs.obs_properties_get(live_props, KEY_SETLIST_LIBRARY)
    if library_prop is not None:
        obs.obs_property_list_clear(library_prop)
        if not _setlist_names:
            obs.obs_property_list_add_string(library_prop, "保存済みセットリストなし", "")
        for name in _setlist_names:
            obs.obs_property_list_add_string(library_prop, name, name)

    song_prop = obs.obs_properties_get(live_props, KEY_SETLIST_SONG)
    if song_prop is not None:
        obs.obs_property_list_clear(song_prop)
        if not _active_setlist["items"]:
            obs.obs_property_list_add_string(song_prop, "曲なし", "")
        for index, item in enumerate(_active_setlist["items"]):
            label = "{:02d}. {}".format(index + 1, core.record_label(item))
            obs.obs_property_list_add_string(song_prop, label, str(index))
    _update_setlist_summary()


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


def _on_display_history_clicked(props, prop):
    item = _find_history_item(_state[KEY_HISTORY])
    if item is None:
        _set_status("最近使った曲を選択してください。")
        return True
    _set_record_fields(item)
    _on_emergency_show_clicked(props, prop)
    return True


def _save_active_setlist():
    global _active_setlist
    name = (_state[KEY_SETLIST_NAME] or _active_setlist["name"]).strip()
    if not name:
        raise core.SongCreditError("セットリスト名を入力してください。")
    core.save_setlist(name, _active_setlist["items"])
    _active_setlist["name"] = name
    _set_string(KEY_SETLIST_NAME, name)
    _set_string(KEY_SETLIST_LIBRARY, name)
    _refresh_setlist_names()
    _refresh_setlist_properties()


def _on_create_setlist_clicked(props, prop):
    global _active_setlist
    name = _state[KEY_SETLIST_NAME].strip()
    if not name:
        _set_status("新しいセットリスト名を入力してください。")
        return True
    _refresh_setlist_names()
    if name in _setlist_names:
        _set_status("同名のセットリストがあります。保存済み一覧から開いてください。")
        return True
    _active_setlist = {"name": name, "items": []}
    _set_string(KEY_SETLIST_SONG, "")
    try:
        _save_active_setlist()
        _set_status("セットリスト「{}」を新規作成しました。".format(name))
    except core.SongCreditError as exc:
        _set_status(str(exc))
    return True


def _on_save_setlist_clicked(props, prop):
    try:
        _save_active_setlist()
        _set_status("セットリスト「{}」を保存しました。".format(_active_setlist["name"]))
    except core.SongCreditError as exc:
        _set_status(str(exc))
    return True


def _on_open_setlist_clicked(props, prop):
    global _active_setlist
    name = _state[KEY_SETLIST_LIBRARY].strip()
    if not name:
        _set_status("保存済みセットリストを選択してください。")
        return True
    try:
        _active_setlist = core.load_setlist(name)
        _set_string(KEY_SETLIST_NAME, _active_setlist["name"])
        _set_string(KEY_SETLIST_LIBRARY, _active_setlist["name"])
        _set_string(KEY_SETLIST_SONG, "0" if _active_setlist["items"] else "")
        if _active_setlist["items"]:
            _set_record_fields(_active_setlist["items"][0])
        _refresh_setlist_properties()
        _set_status("セットリスト「{}」を開きました。".format(_active_setlist["name"]))
    except core.SongCreditError as exc:
        _set_status(str(exc))
    return True


def _on_add_to_setlist_clicked(props, prop):
    if not _active_setlist["name"]:
        _set_status("先にセットリストを新規作成するか、保存済みセットリストを開いてください。")
        return True
    record = _current_record()
    if not record["title"]:
        _set_status("追加する曲の表示タイトルを入力してください。")
        return True
    _active_setlist["items"].append(record)
    _set_string(KEY_SETLIST_SONG, str(len(_active_setlist["items"]) - 1))
    try:
        _save_active_setlist()
        _set_status("「{}」をセットリストへ追加しました。".format(record["title"]))
    except core.SongCreditError as exc:
        _set_status(str(exc))
    return True


def _on_update_setlist_song_clicked(props, prop):
    index = _setlist_index()
    if index < 0:
        _set_status("更新するセットリスト曲を選択してください。")
        return True
    record = _current_record()
    if not record["title"]:
        _set_status("表示タイトルを入力してください。")
        return True
    _active_setlist["items"][index] = record
    try:
        _save_active_setlist()
        _set_status("{}曲目を「{}」で更新しました。".format(index + 1, record["title"]))
    except core.SongCreditError as exc:
        _set_status(str(exc))
    return True


def _on_remove_setlist_song_clicked(props, prop):
    index = _setlist_index()
    if index < 0:
        _set_status("削除するセットリスト曲を選択してください。")
        return True
    removed = _active_setlist["items"].pop(index)
    next_index = min(index, len(_active_setlist["items"]) - 1)
    _set_string(KEY_SETLIST_SONG, str(next_index) if next_index >= 0 else "")
    try:
        _save_active_setlist()
        _set_status("「{}」をセットリストから削除しました。".format(removed.get("title") or ""))
    except core.SongCreditError as exc:
        _set_status(str(exc))
    return True


def _move_setlist_song(delta):
    index = _setlist_index()
    target = index + delta
    if index < 0 or not (0 <= target < len(_active_setlist["items"])):
        _set_status("これ以上、曲順を移動できません。")
        return False
    items = _active_setlist["items"]
    items[index], items[target] = items[target], items[index]
    _set_string(KEY_SETLIST_SONG, str(target))
    try:
        _save_active_setlist()
    except core.SongCreditError as exc:
        _set_status(str(exc))
        return False
    _set_status("曲順を{}へ移動しました。".format("上" if delta < 0 else "下"))
    return True


def _on_move_setlist_song_up_clicked(props, prop):
    _move_setlist_song(-1)
    return True


def _on_move_setlist_song_down_clicked(props, prop):
    _move_setlist_song(1)
    return True


def _display_setlist_index(index):
    if not (0 <= index < len(_active_setlist["items"])):
        _set_status("表示するセットリスト曲を選択してください。")
        return False
    item = _active_setlist["items"][index]
    _set_string(KEY_SETLIST_SONG, str(index))
    _set_record_fields(item)
    if not _show_overlay(True):
        return False
    _set_string(KEY_NOW_PLAYING, "{}曲目：{}".format(index + 1, core.record_label(item)))
    if _history:
        _set_string(KEY_HISTORY, core.history_key(_history[0]))
    _refresh_history_property(_ui_props.get("live"))
    _refresh_setlist_properties()
    return True


def _on_display_selected_setlist_song_clicked(props, prop):
    _display_setlist_index(_setlist_index())
    return True


def _on_load_selected_setlist_song_clicked(props, prop):
    index = _setlist_index()
    if index < 0:
        _set_status("入力欄へ読み込むセットリスト曲を選択してください。")
        return True
    item = _active_setlist["items"][index]
    _set_record_fields(item)
    _set_status("{}曲目「{}」を編集欄へ読み込みました。".format(index + 1, item.get("title") or ""))
    return True


def _on_previous_setlist_song_clicked(props, prop):
    index = _setlist_index()
    if index <= 0:
        _set_status("これがセットリストの先頭です。")
    else:
        _display_setlist_index(index - 1)
    return True


def _on_next_setlist_song_clicked(props, prop):
    index = _setlist_index()
    target = 0 if index < 0 else index + 1
    if target >= len(_active_setlist["items"]):
        _set_status("これがセットリストの最後です。")
    else:
        _display_setlist_index(target)
    return True


def _on_emergency_show_clicked(props, prop):
    if _show_overlay(True):
        record = _current_record()
        _set_string(KEY_NOW_PLAYING, "リクエスト／臨時：{}".format(core.record_label(record)))
        if _history:
            _set_string(KEY_HISTORY, core.history_key(_history[0]))
        _refresh_history_property(_ui_props.get("live"))
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


def _show_selected_scene_items():
    """Ensure selected outputs are visible in the current scene."""
    selected_names = [name for name, unused in _selected_output_sources() if name]
    if not selected_names:
        return

    scene_source = obs.obs_frontend_get_current_scene()
    if scene_source is None:
        return
    try:
        scene = obs.obs_scene_from_source(scene_source)
        if scene is None:
            return
        finder = getattr(obs, "obs_scene_find_source_recursive", None)
        if finder is None:
            finder = obs.obs_scene_find_source
        for source_name in selected_names:
            item = finder(scene, source_name)
            if item is not None:
                obs.obs_sceneitem_set_visible(item, True)
    finally:
        obs.obs_source_release(scene_source)


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

    _show_selected_scene_items()

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
    return _on_emergency_show_clicked(props, prop)


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
        "<b>Song Credit Overlay 0.2.0</b><br>"
        "配信前は複数のセットリストを作成・保存し、配信中は前／次ボタンで即切替できます。"
        "リクエスト曲はセットリストを変更せず緊急表示できます。"
    )


def script_defaults(settings):
    obs.obs_data_set_default_string(settings, KEY_QUERY_TITLE, "")
    obs.obs_data_set_default_string(settings, KEY_QUERY_ARTIST, "")
    obs.obs_data_set_default_string(settings, KEY_FORMAT, "jp")
    obs.obs_data_set_default_bool(settings, KEY_SAVE_HISTORY, True)
    obs.obs_data_set_default_bool(settings, KEY_AUTO_LAYOUT, True)
    obs.obs_data_set_default_bool(settings, KEY_LAYOUT_APPLIED, False)
    obs.obs_data_set_default_string(settings, KEY_SETLIST_LIBRARY, "")
    obs.obs_data_set_default_string(settings, KEY_SETLIST_NAME, "")
    obs.obs_data_set_default_string(settings, KEY_SETLIST_SONG, "")
    obs.obs_data_set_default_string(settings, KEY_SETLIST_SUMMARY, "セットリスト未選択")
    obs.obs_data_set_default_string(settings, KEY_NOW_PLAYING, "まだ表示していません")
    obs.obs_data_set_default_string(
        settings, KEY_STATUS, "配信前はセットリストを開くか、リクエスト欄から曲を追加してください。"
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
        KEY_SETLIST_LIBRARY,
        KEY_SETLIST_NAME,
        KEY_SETLIST_SONG,
        KEY_SETLIST_SUMMARY,
        KEY_NOW_PLAYING,
    ]
    for key in string_keys:
        _state[key] = obs.obs_data_get_string(settings, key) or ""
    _state[KEY_SAVE_HISTORY] = obs.obs_data_get_bool(settings, KEY_SAVE_HISTORY)
    _state[KEY_AUTO_LAYOUT] = obs.obs_data_get_bool(settings, KEY_AUTO_LAYOUT)
    _state[KEY_LAYOUT_APPLIED] = obs.obs_data_get_bool(settings, KEY_LAYOUT_APPLIED)


def script_properties():
    global _ui_props
    props = obs.obs_properties_create()

    obs.obs_properties_add_text(props, KEY_STATUS, "現在の状態", obs.OBS_TEXT_INFO)

    live_props = obs.obs_properties_create()
    saved_setlists = [(name, name) for name in _setlist_names]
    _add_string_list(
        live_props,
        KEY_SETLIST_LIBRARY,
        "使うセットリスト",
        saved_setlists,
        "保存済みセットリストなし",
    )
    obs.obs_properties_add_button(
        live_props, "open_setlist_button", "選択したセットリストを開く", _on_open_setlist_clicked
    )
    setlist_songs = [
        ("{:02d}. {}".format(index + 1, core.record_label(item)), str(index))
        for index, item in enumerate(_active_setlist["items"])
    ]
    _add_string_list(live_props, KEY_SETLIST_SONG, "次に出す曲", setlist_songs, "曲なし")
    obs.obs_properties_add_button(
        live_props, "previous_setlist_song_button", "◀ 前の曲を表示", _on_previous_setlist_song_clicked
    )
    obs.obs_properties_add_button(
        live_props,
        "display_selected_setlist_song_button",
        "選択した曲を表示",
        _on_display_selected_setlist_song_clicked,
    )
    obs.obs_properties_add_button(
        live_props, "next_setlist_song_button", "次の曲を表示 ▶", _on_next_setlist_song_clicked
    )
    obs.obs_properties_add_button(
        live_props, "live_hide_button", "曲間：表示を消す", _on_hide_clicked
    )
    obs.obs_properties_add_text(live_props, KEY_NOW_PLAYING, "現在表示中", obs.OBS_TEXT_INFO)
    history_items = [(core.record_label(item), core.history_key(item)) for item in _history]
    _add_string_list(live_props, KEY_HISTORY, "最近使った曲", history_items, "履歴なし")
    obs.obs_properties_add_button(
        live_props, "display_history_button", "最近使った曲を再表示", _on_display_history_clicked
    )
    obs.obs_properties_add_group(
        props, "live_group", "① 配信中：曲を切り替える", obs.OBS_GROUP_NORMAL, live_props
    )

    prep_props = obs.obs_properties_create()
    obs.obs_properties_add_text(
        prep_props, KEY_SETLIST_NAME, "セットリスト名", obs.OBS_TEXT_DEFAULT
    )
    obs.obs_properties_add_button(
        prep_props, "create_setlist_button", "この名前で新規作成", _on_create_setlist_clicked
    )
    obs.obs_properties_add_button(
        prep_props, "save_setlist_button", "現在のセットリストを保存", _on_save_setlist_clicked
    )
    obs.obs_properties_add_text(
        prep_props, KEY_SETLIST_SUMMARY, "現在編集中", obs.OBS_TEXT_INFO
    )
    obs.obs_properties_add_button(
        prep_props,
        "load_selected_setlist_song_button",
        "選択曲を下の編集欄へ読み込む",
        _on_load_selected_setlist_song_clicked,
    )
    obs.obs_properties_add_button(
        prep_props,
        "update_setlist_song_button",
        "編集内容で選択曲を更新",
        _on_update_setlist_song_clicked,
    )
    obs.obs_properties_add_button(
        prep_props, "move_setlist_song_up_button", "選択曲を上へ", _on_move_setlist_song_up_clicked
    )
    obs.obs_properties_add_button(
        prep_props,
        "move_setlist_song_down_button",
        "選択曲を下へ",
        _on_move_setlist_song_down_clicked,
    )
    obs.obs_properties_add_button(
        prep_props,
        "remove_setlist_song_button",
        "選択曲をセットリストから削除",
        _on_remove_setlist_song_clicked,
    )
    obs.obs_properties_add_group(
        props, "prep_group", "② 配信前：セットリストを作る", obs.OBS_GROUP_NORMAL, prep_props
    )

    request_props = obs.obs_properties_create()
    obs.obs_properties_add_text(
        request_props, KEY_QUERY_TITLE, "検索する曲名", obs.OBS_TEXT_DEFAULT
    )
    obs.obs_properties_add_text(
        request_props, KEY_QUERY_ARTIST, "アーティスト（任意）", obs.OBS_TEXT_DEFAULT
    )
    obs.obs_properties_add_button(
        request_props, "search_button", "曲を検索", _on_search_clicked
    )

    candidates = [(_candidate_label(item), item["id"]) for item in _search_results]
    _add_string_list(request_props, KEY_CANDIDATE, "検索候補", candidates, "候補なし")
    obs.obs_properties_add_button(
        request_props,
        "load_candidate_button",
        "選択候補のクレジットを取得",
        _on_load_candidate_clicked,
    )

    obs.obs_properties_add_text(request_props, KEY_TITLE, "表示タイトル", obs.OBS_TEXT_DEFAULT)
    obs.obs_properties_add_text(request_props, KEY_ARTIST, "表示アーティスト", obs.OBS_TEXT_DEFAULT)
    obs.obs_properties_add_text(
        request_props, KEY_LYRICISTS, "作詞（複数は「、」区切り）", obs.OBS_TEXT_DEFAULT
    )
    obs.obs_properties_add_text(
        request_props, KEY_COMPOSERS, "作曲（複数は「、」区切り）", obs.OBS_TEXT_DEFAULT
    )
    obs.obs_properties_add_text(
        request_props, KEY_ARRANGERS, "編曲（複数は「、」区切り）", obs.OBS_TEXT_DEFAULT
    )
    obs.obs_properties_add_text(
        request_props, KEY_WRITERS, "Writer／役割未確定（要確認）", obs.OBS_TEXT_DEFAULT
    )
    obs.obs_properties_add_text(request_props, KEY_NOTES, "確認事項", obs.OBS_TEXT_MULTILINE)
    obs.obs_properties_add_button(
        request_props,
        "emergency_show_button",
        "リクエスト／臨時曲を今すぐ表示",
        _on_emergency_show_clicked,
    )
    obs.obs_properties_add_button(
        request_props,
        "add_to_setlist_button",
        "この曲を現在のセットリストへ追加",
        _on_add_to_setlist_clicked,
    )
    obs.obs_properties_add_group(
        props,
        "request_group",
        "③ リクエスト対応／曲を検索・編集",
        obs.OBS_GROUP_NORMAL,
        request_props,
    )

    setup_props = obs.obs_properties_create()
    sources = [(name, name) for name in _text_sources()]
    _add_string_list(setup_props, KEY_TITLE_SOURCE, "曲名の出力先", sources, "使用しない")
    _add_string_list(
        setup_props, KEY_ARTIST_SOURCE, "アーティストの出力先", sources, "使用しない"
    )
    _add_string_list(
        setup_props, KEY_CREDIT_SOURCE, "クレジットの出力先", sources, "使用しない"
    )
    obs.obs_properties_add_bool(
        setup_props, KEY_AUTO_LAYOUT, "初回表示時に1920×1080の下部へ自動配置"
    )
    obs.obs_properties_add_button(
        setup_props,
        "apply_lower_third_layout_button",
        "出力先を1920×1080の下部へ配置し直す",
        _on_apply_layout_clicked,
    )

    formats = [("日本語", "jp"), ("English", "en"), ("コンパクト", "compact")]
    _add_string_list(setup_props, KEY_FORMAT, "クレジット表記", formats)
    obs.obs_properties_add_bool(setup_props, KEY_SAVE_HISTORY, "表示時に履歴へ保存")
    obs.obs_properties_add_group(
        props,
        "setup_group",
        "④ 初期設定（通常は触らない）",
        obs.OBS_GROUP_NORMAL,
        setup_props,
    )

    _ui_props = {
        "root": props,
        "live": live_props,
        "prep": prep_props,
        "request": request_props,
        "setup": setup_props,
    }
    return props


def script_load(settings):
    global _show_hotkey_id, _hide_hotkey_id, _active_setlist
    _refresh_history()
    _refresh_setlist_names()
    saved_setlist = _state[KEY_SETLIST_LIBRARY].strip()
    if saved_setlist:
        try:
            _active_setlist = core.load_setlist(saved_setlist)
            if _setlist_index() < 0 and _active_setlist["items"]:
                _set_string(KEY_SETLIST_SONG, "0")
            _update_setlist_summary()
        except core.SongCreditError as exc:
            _active_setlist = {"name": "", "items": []}
            _set_status(str(exc))
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
