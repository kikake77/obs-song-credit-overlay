import csv
import datetime
import json
import os
import re
import tempfile
import threading

import song_credit_core as core


SETLIST_VERSION = 1
SETLIST_EXTENSION = ".scolist.json"
SETTINGS_VERSION = 1
PRODUCT_DIRECTORY = "Song Credit Manager for OBS"
LEGACY_PRODUCT_DIRECTORY = "Song Credit Overlay"
DISPLAY_THEMES = ("dark", "light")
DISPLAY_FONTS = ("gothic", "rounded", "mincho", "sans")
DISPLAY_CREDIT_STYLES = ("jp", "en", "compact")
DEFAULT_DISPLAY_SETTINGS = {
    "theme": "dark",
    "panel": True,
    "font": "gothic",
    "credit_style": "jp",
}

PEOPLE_FIELDS = ("lyricists", "composers", "arrangers", "writers")
LIST_FIELDS = PEOPLE_FIELDS + ("notes",)


def _utc_now():
    value = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    return value.isoformat().replace("+00:00", "Z")


def _as_list(value):
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value is None:
        return []
    text = str(value).strip()
    if not text:
        return []
    return [part.strip() for part in re.split(r"[、,;|/]", text) if part.strip()]


def normalize_record(record):
    if not isinstance(record, dict):
        raise core.SongCreditError("楽曲データの形式が正しくありません。")
    normalized = {
        "title": str(record.get("title") or "").strip(),
        "artist": str(record.get("artist") or "").strip(),
    }
    for key in PEOPLE_FIELDS:
        normalized[key] = _as_list(record.get(key))
    notes = record.get("notes")
    if isinstance(notes, str):
        normalized["notes"] = [line.strip() for line in notes.splitlines() if line.strip()]
    else:
        normalized["notes"] = _as_list(notes)
    normalized["source"] = str(record.get("source") or "manual").strip() or "manual"
    normalized["source_id"] = str(record.get("source_id") or "").strip()
    normalized["source_url"] = str(record.get("source_url") or "").strip()
    normalized["verified"] = bool(record.get("verified", False))
    if record.get("fetched_at"):
        normalized["fetched_at"] = str(record.get("fetched_at")).strip()
    return normalized


def validate_record(record):
    normalized = normalize_record(record)
    if not normalized["title"]:
        raise core.SongCreditError("曲名を入力してください。")
    return normalized


def default_setlists_dir():
    documents = os.path.join(os.path.expanduser("~"), "Documents")
    preferred = os.path.join(documents, PRODUCT_DIRECTORY, "Setlists")
    legacy = os.path.join(documents, LEGACY_PRODUCT_DIRECTORY, "Setlists")
    if not os.path.isdir(preferred) and os.path.isdir(legacy):
        return legacy
    return preferred


def safe_setlist_filename(name):
    display_name = (name or "").strip() or "新しいセットリスト"
    filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", display_name)
    filename = re.sub(r"\s+", " ", filename).strip(" .")[:80]
    return (filename or "setlist") + SETLIST_EXTENSION


def suggested_setlist_path(name):
    return os.path.join(default_setlists_dir(), safe_setlist_filename(name))


def default_settings_path():
    if os.name == "nt" and os.environ.get("APPDATA"):
        root = os.environ["APPDATA"]
    else:
        root = os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(root, PRODUCT_DIRECTORY, "settings.json")


def legacy_settings_path():
    if os.name == "nt" and os.environ.get("APPDATA"):
        root = os.environ["APPDATA"]
    else:
        root = os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(root, LEGACY_PRODUCT_DIRECTORY, "settings.json")


def normalize_display_settings(settings):
    source = settings if isinstance(settings, dict) else {}
    theme = str(source.get("theme") or DEFAULT_DISPLAY_SETTINGS["theme"]).strip().casefold()
    font = str(source.get("font") or DEFAULT_DISPLAY_SETTINGS["font"]).strip().casefold()
    credit_style = str(
        source.get("credit_style") or DEFAULT_DISPLAY_SETTINGS["credit_style"]
    ).strip().casefold()
    return {
        "theme": theme if theme in DISPLAY_THEMES else DEFAULT_DISPLAY_SETTINGS["theme"],
        "panel": bool(source.get("panel", DEFAULT_DISPLAY_SETTINGS["panel"])),
        "font": font if font in DISPLAY_FONTS else DEFAULT_DISPLAY_SETTINGS["font"],
        "credit_style": (
            credit_style
            if credit_style in DISPLAY_CREDIT_STYLES
            else DEFAULT_DISPLAY_SETTINGS["credit_style"]
        ),
    }


def load_display_settings(path=None):
    if path is None:
        path = default_settings_path()
        legacy_path = legacy_settings_path()
        if not os.path.isfile(path) and os.path.isfile(legacy_path):
            path = legacy_path
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (FileNotFoundError, OSError, TypeError, ValueError):
        return dict(DEFAULT_DISPLAY_SETTINGS)
    return normalize_display_settings(payload)


def save_display_settings(settings, path=None):
    path = path or default_settings_path()
    normalized = normalize_display_settings(settings)
    payload = {"version": SETTINGS_VERSION}
    payload.update(normalized)
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=directory, delete=False, suffix=".tmp"
        ) as handle:
            temporary_path = handle.name
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary_path, path)
    except OSError as exc:
        if temporary_path and os.path.exists(temporary_path):
            try:
                os.unlink(temporary_path)
            except OSError:
                pass
        raise core.SongCreditError("表示設定を保存できませんでした: {}".format(exc))
    return normalized


def _read_json_setlist(path):
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            payload = json.load(handle)
    except (OSError, TypeError, ValueError) as exc:
        raise core.SongCreditError("セットリストを読み込めませんでした: {}".format(exc))
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise core.SongCreditError("セットリストのファイル形式が正しくありません。")
    name = str(payload.get("name") or os.path.basename(path)).strip()
    return {
        "version": int(payload.get("version") or SETLIST_VERSION),
        "name": name,
        "items": [normalize_record(item) for item in payload["items"] if isinstance(item, dict)],
    }


def _row_value(row, *names):
    lowered = {str(key).strip().casefold(): value for key, value in row.items() if key is not None}
    for name in names:
        if name.casefold() in lowered:
            return lowered[name.casefold()]
    return ""


def _read_delimited_setlist(path, delimiter):
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle, delimiter=delimiter))
    except (OSError, csv.Error) as exc:
        raise core.SongCreditError("表形式のセットリストを読み込めませんでした: {}".format(exc))
    items = []
    for row in rows:
        record = {
            "title": _row_value(row, "曲名", "title", "song"),
            "artist": _row_value(row, "アーティスト", "artist"),
            "lyricists": _row_value(row, "作詞", "lyricists", "lyrics"),
            "composers": _row_value(row, "作曲", "composers", "music"),
            "arrangers": _row_value(row, "編曲", "arrangers", "arrangement"),
            "writers": _row_value(row, "writer", "writers", "役割未確定"),
            "notes": _row_value(row, "メモ", "notes", "確認事項"),
            "source": "manual",
        }
        if str(record["title"] or "").strip():
            items.append(normalize_record(record))
    if not items:
        raise core.SongCreditError("曲名のある行が見つかりませんでした。")
    return {
        "version": SETLIST_VERSION,
        "name": os.path.splitext(os.path.basename(path))[0],
        "items": items,
    }


def _read_text_setlist(path):
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            lines = handle.readlines()
    except OSError as exc:
        raise core.SongCreditError("テキストのセットリストを読み込めませんでした: {}".format(exc))
    items = []
    for line in lines:
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        if "\t" in text:
            title, unused, artist = text.partition("\t")
        elif " / " in text:
            title, unused, artist = text.partition(" / ")
        else:
            title, artist = text, ""
        if title.strip():
            items.append(normalize_record({"title": title, "artist": artist, "source": "manual"}))
    if not items:
        raise core.SongCreditError("曲名のある行が見つかりませんでした。")
    return {
        "version": SETLIST_VERSION,
        "name": os.path.splitext(os.path.basename(path))[0],
        "items": items,
    }


def load_setlist_file(path):
    extension = os.path.splitext(path)[1].casefold()
    if extension == ".csv":
        return _read_delimited_setlist(path, ",")
    if extension == ".tsv":
        return _read_delimited_setlist(path, "\t")
    if extension == ".txt":
        return _read_text_setlist(path)
    return _read_json_setlist(path)


def save_setlist_file(path, name, items):
    payload = {
        "version": SETLIST_VERSION,
        "name": (name or "").strip() or "新しいセットリスト",
        "saved_at": _utc_now(),
        "items": [normalize_record(item) for item in (items or [])],
    }
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=directory, delete=False, suffix=".tmp"
        ) as handle:
            temporary_path = handle.name
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary_path, path)
    except OSError as exc:
        if temporary_path and os.path.exists(temporary_path):
            try:
                os.unlink(temporary_path)
            except OSError:
                pass
        raise core.SongCreditError("セットリストを保存できませんでした: {}".format(exc))
    return os.path.abspath(path)


def export_setlist_csv(path, items):
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fieldnames = ["順番", "曲名", "アーティスト", "作詞", "作曲", "編曲", "Writer", "メモ"]
    try:
        with open(path, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for index, raw in enumerate(items or [], 1):
                item = normalize_record(raw)
                writer.writerow(
                    {
                        "順番": index,
                        "曲名": item["title"],
                        "アーティスト": item["artist"],
                        "作詞": "、".join(item["lyricists"]),
                        "作曲": "、".join(item["composers"]),
                        "編曲": "、".join(item["arrangers"]),
                        "Writer": "、".join(item["writers"]),
                        "メモ": " / ".join(item["notes"]),
                    }
                )
    except (OSError, csv.Error) as exc:
        raise core.SongCreditError("CSVを書き出せませんでした: {}".format(exc))
    return os.path.abspath(path)


class SetlistDocument(object):
    def __init__(self, name="新しいセットリスト", items=None, path=""):
        self.name = (name or "").strip() or "新しいセットリスト"
        self.items = [normalize_record(item) for item in (items or [])]
        self.path = os.path.abspath(path) if path else ""
        self.dirty = False

    @classmethod
    def load(cls, path):
        payload = load_setlist_file(path)
        document = cls(payload["name"], payload["items"], path if path.casefold().endswith(".json") else "")
        document.dirty = not path.casefold().endswith(".json")
        return document

    def save(self, path=None):
        target = path or self.path
        if not target:
            raise core.SongCreditError("保存先を選択してください。")
        self.path = save_setlist_file(target, self.name, self.items)
        self.dirty = False
        return self.path

    def rename(self, name):
        name = (name or "").strip()
        if not name:
            raise core.SongCreditError("セットリスト名を入力してください。")
        if name != self.name:
            self.name = name
            self.dirty = True

    def add(self, record):
        self.items.append(validate_record(record))
        self.dirty = True
        return len(self.items) - 1

    def update(self, index, record):
        if not 0 <= index < len(self.items):
            raise core.SongCreditError("更新する曲を選択してください。")
        self.items[index] = validate_record(record)
        self.dirty = True
        return index

    def remove(self, index):
        if not 0 <= index < len(self.items):
            raise core.SongCreditError("削除する曲を選択してください。")
        removed = self.items.pop(index)
        self.dirty = True
        return removed

    def move(self, index, offset):
        target = index + offset
        if not 0 <= index < len(self.items) or not 0 <= target < len(self.items):
            return index
        self.items[index], self.items[target] = self.items[target], self.items[index]
        self.dirty = True
        return target


class OverlayStateStore(object):
    def __init__(self, display_settings=None):
        self._lock = threading.RLock()
        self._sequence = 0
        settings = normalize_display_settings(display_settings)
        self._state = {
            "sequence": 0,
            "visible": False,
            "title": "",
            "artist": "",
            "credits": "",
            "theme": settings["theme"],
            "panel": settings["panel"],
            "font": settings["font"],
            "updated_at": _utc_now(),
        }

    def show_record(self, record, style="jp"):
        record = validate_record(record)
        outputs = core.build_outputs(record, style)
        with self._lock:
            self._sequence += 1
            self._state.update(
                {
                    "sequence": self._sequence,
                    "visible": True,
                    "title": outputs["title"],
                    "artist": outputs["artist"],
                    "credits": outputs["credits"],
                    "updated_at": _utc_now(),
                }
            )
            return dict(self._state)

    def set_style(self, theme=None, panel=None, font=None):
        with self._lock:
            settings = normalize_display_settings(
                {
                    "theme": theme if theme is not None else self._state["theme"],
                    "panel": panel if panel is not None else self._state["panel"],
                    "font": font if font is not None else self._state["font"],
                }
            )
            self._sequence += 1
            self._state.update(
                {
                    "sequence": self._sequence,
                    "theme": settings["theme"],
                    "panel": settings["panel"],
                    "font": settings["font"],
                    "updated_at": _utc_now(),
                }
            )
            return dict(self._state)

    def hide(self):
        with self._lock:
            self._sequence += 1
            self._state["sequence"] = self._sequence
            self._state["visible"] = False
            self._state["updated_at"] = _utc_now()
            return dict(self._state)

    def snapshot(self):
        with self._lock:
            return dict(self._state)
