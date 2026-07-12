# -*- coding: utf-8 -*-
"""Core functions for Song Credit Overlay.

This module intentionally has no OBS dependency so that search parsing, credit
formatting, and history persistence can be tested outside OBS Studio.
"""

import datetime
import json
import os
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request


APP_NAME = "SongCreditOverlay"
APP_VERSION = "0.1.2"
MUSICBRAINZ_BASE_URL = "https://musicbrainz.org/ws/2"
DEFAULT_TIMEOUT_SECONDS = 12
MIN_REQUEST_INTERVAL_SECONDS = 1.1


class SongCreditError(Exception):
    """User-facing error raised by the core module."""


def _utc_now():
    value = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    return value.isoformat().replace("+00:00", "Z")


def _unique(values):
    result = []
    seen = set()
    for value in values:
        text = (value or "").strip()
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result


def _artist_name(relationship):
    artist = relationship.get("artist") or {}
    return (artist.get("name") or artist.get("sort-name") or "").strip()


def artist_credit_text(artist_credit):
    """Convert a MusicBrainz artist-credit array into display text."""
    parts = []
    for credit in artist_credit or []:
        if isinstance(credit, str):
            parts.append(credit)
            continue
        name = credit.get("name")
        if not name:
            artist = credit.get("artist") or {}
            name = artist.get("name") or artist.get("sort-name") or ""
        parts.append(name)
        parts.append(credit.get("joinphrase") or "")
    return "".join(parts).strip()


def parse_search_response(payload):
    """Return compact, display-ready recording candidates."""
    results = []
    for recording in payload.get("recordings") or []:
        recording_id = (recording.get("id") or "").strip()
        title = (recording.get("title") or "").strip()
        if not recording_id or not title:
            continue
        releases = recording.get("releases") or []
        first_release = releases[0] if releases else {}
        try:
            score = int(recording.get("score") or 0)
        except (TypeError, ValueError):
            score = 0
        results.append(
            {
                "id": recording_id,
                "title": title,
                "artist": artist_credit_text(recording.get("artist-credit")),
                "date": (recording.get("first-release-date") or "").strip(),
                "release": (first_release.get("title") or "").strip(),
                "disambiguation": (recording.get("disambiguation") or "").strip(),
                "score": score,
            }
        )
    return results


def _collect_people(relationships, buckets, notes):
    writers = []
    for relationship in relationships or []:
        name = _artist_name(relationship)
        if not name:
            continue
        relation_type = (relationship.get("type") or "").strip().casefold()
        if relation_type == "composer":
            buckets["composers"].append(name)
        elif relation_type in ("lyricist", "librettist"):
            buckets["lyricists"].append(name)
        elif relation_type == "writer":
            writers.append(name)
        elif relation_type in ("arranger", "instrument arranger", "orchestrator"):
            buckets["arrangers"].append(name)

    # MusicBrainz uses "writer" when the exact division between words and music
    # is unknown. It is kept separate rather than silently mislabelled.
    if writers:
        buckets["writers"].extend(writers)
        notes.append("MusicBrainzでは役割が「writer」のため、作詞・作曲を個別確認してください。")


def parse_credit_payload(recording, work_payloads):
    """Build a normalized credit record from recording and work lookups."""
    buckets = {
        "lyricists": [],
        "composers": [],
        "arrangers": [],
        "writers": [],
    }
    notes = []
    _collect_people(recording.get("relations"), buckets, notes)
    work_ids = []
    work_titles = []

    for relationship in recording.get("relations") or []:
        work = relationship.get("work") or {}
        work_id = (work.get("id") or "").strip()
        if work_id:
            work_ids.append(work_id)
        work_title = (work.get("title") or "").strip()
        if work_title:
            work_titles.append(work_title)

    for work in work_payloads or []:
        work_id = (work.get("id") or "").strip()
        work_title = (work.get("title") or "").strip()
        if work_id:
            work_ids.append(work_id)
        if work_title:
            work_titles.append(work_title)
        _collect_people(work.get("relations"), buckets, notes)

    for key in buckets:
        buckets[key] = _unique(buckets[key])

    return {
        "title": (recording.get("title") or "").strip(),
        "artist": artist_credit_text(recording.get("artist-credit")),
        "lyricists": buckets["lyricists"],
        "composers": buckets["composers"],
        "arrangers": buckets["arrangers"],
        "writers": buckets["writers"],
        "work_ids": _unique(work_ids),
        "work_titles": _unique(work_titles),
        "notes": _unique(notes),
        "source": "musicbrainz",
        "source_id": (recording.get("id") or "").strip(),
        "source_url": "https://musicbrainz.org/recording/{}".format(
            (recording.get("id") or "").strip()
        ),
        "fetched_at": _utc_now(),
        "verified": False,
    }


def _escape_lucene_phrase(value):
    return (value or "").replace("\\", "\\\\").replace('"', '\\"').strip()


class MusicBrainzClient(object):
    """Small MusicBrainz client with a process-local rate limiter."""

    _request_lock = threading.Lock()
    _last_request_at = 0.0

    def __init__(self, timeout=DEFAULT_TIMEOUT_SECONDS, contact="local-obs-user"):
        self.timeout = timeout
        self.user_agent = "{}/{} ({})".format(APP_NAME, APP_VERSION, contact)

    def _request_json(self, path, params=None):
        query = urllib.parse.urlencode(params or {})
        url = MUSICBRAINZ_BASE_URL + path
        if query:
            url += "?" + query

        with self._request_lock:
            elapsed = time.monotonic() - self._last_request_at
            if elapsed < MIN_REQUEST_INTERVAL_SECONDS:
                time.sleep(MIN_REQUEST_INTERVAL_SECONDS - elapsed)
            request = urllib.request.Request(
                url,
                headers={
                    "Accept": "application/json",
                    "User-Agent": self.user_agent,
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    data = response.read().decode("utf-8")
            except urllib.error.HTTPError as exc:
                if exc.code == 503:
                    raise SongCreditError(
                        "MusicBrainzが混雑しています。少し待って再検索してください。"
                    )
                raise SongCreditError(
                    "MusicBrainzへの接続に失敗しました（HTTP {}）。".format(exc.code)
                )
            except (urllib.error.URLError, OSError) as exc:
                raise SongCreditError(
                    "MusicBrainzへ接続できませんでした: {}".format(exc)
                )
            finally:
                type(self)._last_request_at = time.monotonic()

        try:
            return json.loads(data)
        except (TypeError, ValueError):
            raise SongCreditError("MusicBrainzから不正な応答を受信しました。")

    def search_recordings(self, title, artist="", limit=8):
        title = (title or "").strip()
        artist = (artist or "").strip()
        if not title:
            raise SongCreditError("曲名を入力してください。")
        query_parts = ['recording:"{}"'.format(_escape_lucene_phrase(title))]
        if artist:
            query_parts.append('artist:"{}"'.format(_escape_lucene_phrase(artist)))
        payload = self._request_json(
            "/recording/",
            {
                "query": " AND ".join(query_parts),
                "fmt": "json",
                "limit": max(1, min(int(limit), 15)),
            },
        )
        return parse_search_response(payload)

    def fetch_credits(self, recording_id):
        recording_id = (recording_id or "").strip()
        if not recording_id:
            raise SongCreditError("楽曲候補を選択してください。")
        recording = self._request_json(
            "/recording/{}".format(urllib.parse.quote(recording_id)),
            {"inc": "artist-credits+work-rels+artist-rels", "fmt": "json"},
        )
        work_ids = []
        for relationship in recording.get("relations") or []:
            work = relationship.get("work") or {}
            work_id = (work.get("id") or "").strip()
            if work_id and work_id not in work_ids:
                work_ids.append(work_id)

        work_payloads = []
        for work_id in work_ids[:4]:
            work_payloads.append(
                self._request_json(
                    "/work/{}".format(urllib.parse.quote(work_id)),
                    {"inc": "artist-rels", "fmt": "json"},
                )
            )
        record = parse_credit_payload(recording, work_payloads)
        if not work_ids:
            record["notes"].append(
                "この録音に対応する作品情報がないため、クレジットを手動確認してください。"
            )
        return record


def default_history_path():
    if os.name == "nt" and os.environ.get("APPDATA"):
        root = os.path.join(os.environ["APPDATA"], "obs-studio", "plugin_config")
    else:
        root = os.path.join(os.path.expanduser("~"), ".config", "obs-studio", "plugin_config")
    return os.path.join(root, "song-credit-overlay", "history.json")


def load_history(path=None):
    path = path or default_history_path()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError:
        return []
    except (OSError, TypeError, ValueError) as exc:
        raise SongCreditError("履歴ファイルを読み込めませんでした: {}".format(exc))
    items = payload.get("items") if isinstance(payload, dict) else None
    return items if isinstance(items, list) else []


def _save_history(items, path):
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    payload = {"version": 1, "items": items}
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
        raise SongCreditError("履歴ファイルを保存できませんでした: {}".format(exc))


def history_key(record):
    source_id = (record.get("source_id") or "").strip()
    if source_id:
        return "mb:" + source_id
    title = (record.get("title") or "").strip().casefold()
    artist = (record.get("artist") or "").strip().casefold()
    return "manual:{}\x1f{}".format(title, artist)


def upsert_history(record, path=None, max_items=100):
    path = path or default_history_path()
    items = load_history(path)
    saved = dict(record)
    saved["saved_at"] = _utc_now()
    key = history_key(saved)
    items = [item for item in items if history_key(item) != key]
    items.insert(0, saved)
    items = items[: max(1, int(max_items))]
    _save_history(items, path)
    return items


def _people_text(record, key):
    value = record.get(key) or []
    if isinstance(value, str):
        return value.strip()
    return "、".join(_unique(value))


def format_credits(record, style="jp"):
    lyricists = _people_text(record, "lyricists")
    composers = _people_text(record, "composers")
    arrangers = _people_text(record, "arrangers")
    writers = _people_text(record, "writers")
    parts = []

    if style == "en":
        if lyricists:
            parts.append("Lyrics: " + lyricists)
        if composers:
            parts.append("Music: " + composers)
        if arrangers:
            parts.append("Arrangement: " + arrangers)
        if writers:
            parts.append("Writer: " + writers)
        return " / ".join(parts)

    if style == "compact":
        if lyricists:
            parts.append("詞 " + lyricists)
        if composers:
            parts.append("曲 " + composers)
        if arrangers:
            parts.append("編 " + arrangers)
        if writers:
            parts.append("Writer " + writers)
        return " / ".join(parts)

    if lyricists:
        parts.append("作詞：" + lyricists)
    if composers:
        parts.append("作曲：" + composers)
    if arrangers:
        parts.append("編曲：" + arrangers)
    if writers:
        parts.append("Writer：" + writers)
    return "　".join(parts)


def build_outputs(record, style="jp"):
    return {
        "title": (record.get("title") or "").strip(),
        "artist": (record.get("artist") or "").strip(),
        "credits": format_credits(record, style),
    }


def record_label(record):
    title = (record.get("title") or "タイトルなし").strip()
    artist = (record.get("artist") or "アーティスト不明").strip()
    return "{} — {}".format(title, artist)
