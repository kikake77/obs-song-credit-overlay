import os
import random
import threading
import webbrowser
import tkinter as tk
from tkinter import font as tkfont
from tkinter import filedialog, messagebox, simpledialog, ttk

import song_credit_core as core
import song_credit_manager_core as manager_core
from song_credit_server import DEFAULT_PORT, OverlayServer, resource_path


PROJECT_URL = "https://github.com/kikake77/obs-song-credit-overlay"
SEARCH_PAGE_SIZE = 20
ARTIST_CANDIDATE_PLACEHOLDER = "表示中の候補から選択"
DISPLAY_PRESETS = {
    "標準（暗いパネル）": {"theme": "dark", "panel": True},
    "明るいパネル": {"theme": "light", "panel": True},
    "文字のみ（背景パネルなし）": {"theme": "dark", "panel": False},
}
FONT_CHOICES = {
    "ゴシック（推奨）": "gothic",
    "丸ゴシック": "rounded",
    "明朝": "mincho",
    "英字サンセリフ": "sans",
}
FONT_KEY_TO_LABEL = {value: key for key, value in FONT_CHOICES.items()}
CREDIT_STYLE_CHOICES = {"日本語": "jp", "英語": "en", "コンパクト": "compact"}
CREDIT_KEY_TO_LABEL = {value: key for key, value in CREDIT_STYLE_CHOICES.items()}
FONT_SIZE_CHOICES = {
    "自動（長い文字を縮小・推奨）": "auto",
    "小": "small",
    "標準": "medium",
    "大": "large",
}
FONT_SIZE_KEY_TO_LABEL = {value: key for key, value in FONT_SIZE_CHOICES.items()}
PREVIEW_FONT_SIZES = {
    "auto": (20, 12, 10),
    "small": (16, 10, 8),
    "medium": (20, 12, 10),
    "large": (24, 14, 12),
}
TUTORIAL_SETLIST_NAME = "チュートリアル：歌枠セットリスト例"
TUTORIAL_SETLIST_PATH = os.path.join("docs", "samples", "歌枠セットリスト例.tsv")
TUTORIAL_ITEM_COUNT = 10
TUTORIAL_RANDOM_SEED = "song-credit-manager-tutorial-v1"


def load_bundled_tutorial_document():
    payload = manager_core.load_setlist_file(resource_path(TUTORIAL_SETLIST_PATH))
    items = payload["items"]
    if len(items) > TUTORIAL_ITEM_COUNT:
        items = random.Random(TUTORIAL_RANDOM_SEED).sample(items, TUTORIAL_ITEM_COUNT)
    document = manager_core.SetlistDocument(TUTORIAL_SETLIST_NAME, items)
    document.dirty = False
    return document


class SongCreditManagerApp(object):
    def __init__(self, root):
        self.root = root
        self.root.title("Song Credit Manager for OBS {}".format(core.APP_VERSION))
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        initial_width = min(1320, max(1060, screen_width - 120))
        initial_height = min(860, max(690, screen_height - 140))
        self.root.geometry("{}x{}".format(initial_width, initial_height))
        self.root.minsize(1040, 680)

        self.tutorial_loaded = False
        try:
            self.document = load_bundled_tutorial_document()
            self.tutorial_loaded = True
        except core.SongCreditError:
            self.document = manager_core.SetlistDocument()
        self.display_settings = manager_core.load_display_settings()
        self.play_index = -1
        self.overlay_visible = False
        self.last_display_label = ""
        self.current_display_record = None
        self.search_results = []
        self.search_total = 0
        self.search_offset = 0
        self.search_query_title = ""
        self.search_query_artist = ""
        self.editor_metadata = {"source": "manual", "source_id": "", "source_url": "", "verified": False}
        self.closing = False

        self.state_store = manager_core.OverlayStateStore(self.display_settings)
        self.server = OverlayServer(self.state_store, port=DEFAULT_PORT)
        self.client = core.MusicBrainzClient(contact=PROJECT_URL)

        self.status_var = tk.StringVar(value="起動しています…")
        self.server_status_var = tk.StringVar(value="表示サーバー：停止")
        self.overlay_url_var = tk.StringVar(value=self.server.overlay_url)
        self.now_playing_var = tk.StringVar(value="まだ表示していません")
        self.setlist_name_var = tk.StringVar(value=self.document.name)
        self.setlist_summary_var = tk.StringVar()
        self.setlist_path_var = tk.StringVar(value="未保存")

        self.search_title_var = tk.StringVar()
        self.search_artist_var = tk.StringVar()
        self.search_summary_var = tk.StringVar(value="曲名を入力して検索してください。")
        self.artist_candidate_var = tk.StringVar(value=ARTIST_CANDIDATE_PLACEHOLDER)
        self.title_var = tk.StringVar()
        self.artist_var = tk.StringVar()
        self.lyricists_var = tk.StringVar()
        self.composers_var = tk.StringVar()
        self.arrangers_var = tk.StringVar()
        self.writers_var = tk.StringVar()
        self.display_preset_var = tk.StringVar(value=self._preset_label_from_settings())
        self.font_choice_var = tk.StringVar(
            value=FONT_KEY_TO_LABEL.get(self.display_settings["font"], "ゴシック（推奨）")
        )
        self.font_size_var = tk.StringVar(
            value=FONT_SIZE_KEY_TO_LABEL.get(
                self.display_settings["font_size"], "自動（長い文字を縮小・推奨）"
            )
        )
        self.credit_format_var = tk.StringVar(
            value=CREDIT_KEY_TO_LABEL.get(self.display_settings["credit_style"], "日本語")
        )

        self._configure_style()
        self._build_ui()
        self._refresh_setlist()
        for variable in (
            self.title_var,
            self.artist_var,
            self.lyricists_var,
            self.composers_var,
            self.arrangers_var,
            self.writers_var,
        ):
            variable.trace_add("write", lambda *unused: self.root.after_idle(self._refresh_display_preview))
        self.root.after_idle(self._refresh_display_preview)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(50, self._start_server)

    def _configure_style(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("vista")
        except tk.TclError:
            pass
        style.configure("Header.TLabel", font=("Yu Gothic UI", 16, "bold"))
        style.configure("Subheader.TLabel", font=("Yu Gothic UI", 11, "bold"))
        style.configure("Primary.TButton", font=("Yu Gothic UI", 10, "bold"), padding=(12, 8))
        style.configure("Danger.TButton", padding=(10, 7))

    def _build_ui(self):
        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer)
        header.pack(fill="x", pady=(0, 10))
        ttk.Label(header, text="Song Credit Manager for OBS", style="Header.TLabel").pack(side="left")
        ttk.Label(header, textvariable=self.server_status_var).pack(side="right")

        now_frame = ttk.LabelFrame(outer, text="現在の表示", padding=(12, 8))
        now_frame.pack(fill="x", pady=(0, 10))
        ttk.Label(now_frame, textvariable=self.now_playing_var, style="Subheader.TLabel").pack(side="left")

        status = ttk.Label(outer, textvariable=self.status_var, relief="sunken", anchor="w", padding=(8, 5))
        status.pack(fill="x", pady=(0, 10))

        panes = ttk.Panedwindow(outer, orient="horizontal")
        panes.pack(fill="both", expand=True)

        left = ttk.Frame(panes, padding=(0, 0, 8, 0))
        right = ttk.Frame(panes, padding=(8, 0, 0, 0))
        panes.add(left, weight=5)
        panes.add(right, weight=7)
        self._build_setlist_pane(left)
        self._build_tabs(right)

    def _build_setlist_pane(self, parent):
        ttk.Label(parent, text="配信中：セットリスト", style="Subheader.TLabel").pack(anchor="w")

        name_row = ttk.Frame(parent)
        name_row.pack(fill="x", pady=(6, 4))
        ttk.Label(name_row, text="名前").pack(side="left")
        ttk.Entry(name_row, textvariable=self.setlist_name_var).pack(side="left", fill="x", expand=True, padx=(8, 0))

        ttk.Label(parent, textvariable=self.setlist_summary_var).pack(anchor="w", pady=(0, 4))

        file_actions = ttk.Frame(parent)
        file_actions.pack(fill="x", pady=(2, 6))
        for column in (0, 1, 2, 3):
            file_actions.columnconfigure(column, weight=1)
        ttk.Button(file_actions, text="新規", command=self._new_setlist).grid(
            row=0, column=0, sticky="ew", padx=(0, 3)
        )
        ttk.Button(file_actions, text="開く", command=self._open_setlist).grid(
            row=0, column=1, sticky="ew", padx=3
        )
        ttk.Button(file_actions, text="保存", style="Primary.TButton", command=self._save_setlist).grid(
            row=0, column=2, sticky="ew", padx=3
        )
        ttk.Button(file_actions, text="別名保存", command=self._save_setlist_as).grid(
            row=0, column=3, sticky="ew", padx=(3, 0)
        )
        ttk.Label(parent, textvariable=self.setlist_path_var, foreground="#606a78", wraplength=470).pack(
            anchor="w", pady=(0, 5)
        )

        list_frame = ttk.Frame(parent)
        list_frame.pack(fill="both", expand=True)
        self.setlist_box = tk.Listbox(
            list_frame,
            activestyle="dotbox",
            exportselection=False,
            font=("Yu Gothic UI", 11),
            selectmode="browse",
        )
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.setlist_box.yview)
        self.setlist_box.configure(yscrollcommand=scrollbar.set)
        self.setlist_box.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.setlist_box.bind("<Double-Button-1>", lambda event: self._display_selected())
        self.setlist_box.bind("<<ListboxSelect>>", lambda event: self._update_setlist_action_states())

        manage = ttk.Frame(parent)
        manage.pack(fill="x", pady=(8, 4))
        for column in (0, 1, 2):
            manage.columnconfigure(column, weight=1)
        self.move_up_button = ttk.Button(manage, text="▲ 上へ", command=lambda: self._move_selected(-1))
        self.move_up_button.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.move_down_button = ttk.Button(manage, text="▼ 下へ", command=lambda: self._move_selected(1))
        self.move_down_button.grid(row=0, column=1, sticky="ew", padx=4)
        self.remove_button = ttk.Button(manage, text="削除", style="Danger.TButton", command=self._remove_selected)
        self.remove_button.grid(row=0, column=2, sticky="ew", padx=(4, 0))

        transport = ttk.Frame(parent)
        transport.pack(fill="x", pady=(8, 4))
        for column in (0, 1, 2):
            transport.columnconfigure(column, weight=1)
        ttk.Button(transport, text="◀ 前の曲", command=self._display_previous).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.display_toggle_button = ttk.Button(
            transport, text="選択曲を表示", style="Primary.TButton", command=self._toggle_overlay
        )
        self.display_toggle_button.grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Button(transport, text="次の曲 ▶", command=self._display_next).grid(row=0, column=2, sticky="ew", padx=(4, 0))

        utility = ttk.Frame(parent)
        utility.pack(fill="x", pady=(4, 0))
        utility.columnconfigure(0, weight=1)
        ttk.Button(utility, text="選択曲を編集欄へ", command=self._load_selected_into_editor).grid(
            row=0, column=0, sticky="ew"
        )

    def _build_tabs(self, parent):
        notebook = ttk.Notebook(parent)
        notebook.pack(fill="both", expand=True)

        edit_tab = ttk.Frame(notebook, padding=12)
        import_export_tab = ttk.Frame(notebook, padding=12)
        design_tab = ttk.Frame(notebook, padding=12)
        notebook.add(edit_tab, text="曲を検索・編集")
        notebook.add(import_export_tab, text="入出力")
        notebook.add(design_tab, text="表示デザイン")
        self._build_edit_tab(edit_tab)
        self._build_import_export_tab(import_export_tab)
        self._build_design_tab(design_tab)

    def _build_edit_tab(self, parent):
        search = ttk.LabelFrame(parent, text="MusicBrainzで検索", padding=10)
        search.pack(fill="x")
        search.columnconfigure(1, weight=1)
        ttk.Label(search, text="曲名").grid(row=0, column=0, sticky="w", pady=3)
        ttk.Entry(search, textvariable=self.search_title_var).grid(row=0, column=1, sticky="ew", padx=8, pady=3)
        ttk.Label(search, text="アーティスト（任意）").grid(row=1, column=0, sticky="w", pady=3)
        ttk.Entry(search, textvariable=self.search_artist_var).grid(row=1, column=1, sticky="ew", padx=8, pady=3)
        ttk.Button(search, text="検索", style="Primary.TButton", command=self._search_musicbrainz).grid(
            row=0, column=2, rowspan=2, sticky="ns", pady=3
        )
        ttk.Label(search, textvariable=self.search_summary_var, style="Subheader.TLabel").grid(
            row=2, column=0, columnspan=3, sticky="w", pady=(9, 4)
        )

        ttk.Label(search, text="アーティスト候補").grid(row=3, column=0, sticky="w", pady=3)
        self.artist_candidate_combo = ttk.Combobox(
            search,
            textvariable=self.artist_candidate_var,
            state="readonly",
            values=(ARTIST_CANDIDATE_PLACEHOLDER,),
        )
        self.artist_candidate_combo.grid(row=3, column=1, sticky="ew", padx=8, pady=3)
        ttk.Button(search, text="この候補で絞る", command=self._filter_by_artist_candidate).grid(
            row=3, column=2, sticky="ew", pady=3
        )

        result_frame = ttk.Frame(search)
        result_frame.grid(row=4, column=0, columnspan=3, sticky="nsew", pady=(6, 4))
        result_frame.columnconfigure(0, weight=1)
        result_frame.rowconfigure(0, weight=1)
        self.candidate_tree = ttk.Treeview(
            result_frame,
            columns=("artist", "date", "release"),
            show="tree headings",
            height=4,
            selectmode="browse",
        )
        self.candidate_tree.heading("#0", text="曲名")
        self.candidate_tree.heading("artist", text="アーティスト")
        self.candidate_tree.heading("date", text="年")
        self.candidate_tree.heading("release", text="収録作品")
        self.candidate_tree.column("#0", width=190, minwidth=120, stretch=True)
        self.candidate_tree.column("artist", width=160, minwidth=110, stretch=True)
        self.candidate_tree.column("date", width=76, minwidth=60, stretch=False)
        self.candidate_tree.column("release", width=190, minwidth=120, stretch=True)
        candidate_scrollbar = ttk.Scrollbar(result_frame, orient="vertical", command=self.candidate_tree.yview)
        self.candidate_tree.configure(yscrollcommand=candidate_scrollbar.set)
        self.candidate_tree.grid(row=0, column=0, sticky="nsew")
        candidate_scrollbar.grid(row=0, column=1, sticky="ns")
        self.candidate_tree.bind("<Double-Button-1>", lambda event: self._fetch_selected_credits())

        page_controls = ttk.Frame(search)
        page_controls.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(3, 0))
        for column in (0, 1, 2):
            page_controls.columnconfigure(column, weight=1)
        self.previous_results_button = ttk.Button(
            page_controls, text="◀ 前の20件", command=self._previous_search_page, state="disabled"
        )
        self.previous_results_button.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ttk.Button(
            page_controls,
            text="選択候補のクレジットを取得",
            style="Primary.TButton",
            command=self._fetch_selected_credits,
        ).grid(row=0, column=1, sticky="ew", padx=4)
        self.next_results_button = ttk.Button(
            page_controls, text="次の20件 ▶", command=self._next_search_page, state="disabled"
        )
        self.next_results_button.grid(row=0, column=2, sticky="ew", padx=(4, 0))

        fields = ttk.LabelFrame(parent, text="表示・保存する内容", padding=10)
        fields.pack(fill="both", expand=True, pady=(10, 0))
        fields.columnconfigure(1, weight=1)
        rows = [
            ("曲名", self.title_var),
            ("アーティスト", self.artist_var),
            ("作詞", self.lyricists_var),
            ("作曲", self.composers_var),
            ("編曲", self.arrangers_var),
            ("Writer／役割未確定", self.writers_var),
        ]
        for row, (label, variable) in enumerate(rows):
            ttk.Label(fields, text=label).grid(row=row, column=0, sticky="w", pady=3)
            ttk.Entry(fields, textvariable=variable).grid(row=row, column=1, sticky="ew", padx=(8, 0), pady=3)
        ttk.Label(fields, text="確認事項").grid(row=len(rows), column=0, sticky="nw", pady=3)
        self.notes_text = tk.Text(fields, height=2, wrap="word", font=("Yu Gothic UI", 10))
        self.notes_text.grid(row=len(rows), column=1, sticky="nsew", padx=(8, 0), pady=3)
        fields.rowconfigure(len(rows), weight=1)

        actions = ttk.Frame(parent)
        actions.pack(fill="x", pady=(10, 0))
        for column in (0, 1, 2):
            actions.columnconfigure(column, weight=1)
        ttk.Button(actions, text="セットリストへ追加", command=self._add_editor_record).grid(
            row=0, column=0, sticky="ew", padx=(0, 4)
        )
        ttk.Button(actions, text="選択曲を更新", command=self._update_selected_record).grid(
            row=0, column=1, sticky="ew", padx=4
        )
        ttk.Button(actions, text="リクエスト曲を今すぐ表示", style="Primary.TButton", command=self._show_editor_record).grid(
            row=0, column=2, sticky="ew", padx=(4, 0)
        )

    def _build_import_export_tab(self, parent):
        ttk.Label(parent, text="外部ファイルとの入出力", style="Subheader.TLabel").pack(anchor="w")
        ttk.Label(
            parent,
            text="通常の保存・読み込みは左のセットリスト欄を使います。ここは表計算ソフトやテキストで作った曲順を取り込む場合だけ使います。",
            wraplength=620,
        ).pack(anchor="w", pady=(4, 14))

        import_box = ttk.LabelFrame(parent, text="取り込む", padding=12)
        import_box.pack(fill="x")
        ttk.Label(
            import_box,
            text="CSV・TSV・TXTを現在のセットリストとして読み込みます。読み込み後は左の［保存］を押してください。",
            wraplength=590,
        ).pack(anchor="w", pady=(0, 8))
        ttk.Button(import_box, text="CSV／TSV／TXTを読み込む", command=self._import_setlist).pack(fill="x")
        ttk.Button(
            import_box,
            text="チュートリアルのセットリストを読み込む",
            command=self._restore_tutorial_setlist,
        ).pack(fill="x", pady=(8, 0))

        export_box = ttk.LabelFrame(parent, text="書き出す", padding=12)
        export_box.pack(fill="x", pady=(14, 0))
        ttk.Label(
            export_box,
            text="現在のセットリストを、Excelなどで編集できるCSVへ書き出します。",
            wraplength=590,
        ).pack(anchor="w", pady=(0, 8))
        ttk.Button(export_box, text="現在のセットリストをCSVへ書き出す", command=self._export_csv).pack(fill="x")

    def _build_design_tab(self, parent):
        ttk.Label(parent, text="OBSへ出す見た目を調整", style="Subheader.TLabel").pack(anchor="w")
        ttk.Label(
            parent,
            text="変更は同じURLのOBSブラウザソースへすぐ反映されます。下のプレビューは編集中の内容を表示します。",
            wraplength=620,
        ).pack(anchor="w", pady=(4, 10))

        self.preview_canvas = tk.Canvas(parent, height=230, background="#151922", highlightthickness=1, highlightbackground="#9aa4b2")
        self.preview_canvas.pack(fill="x")
        self.preview_canvas.bind("<Configure>", lambda event: self._refresh_display_preview())

        controls = ttk.LabelFrame(parent, text="表示形式", padding=10)
        controls.pack(fill="x", pady=(10, 0))
        for column in (1, 3):
            controls.columnconfigure(column, weight=1)
        ttk.Label(controls, text="デザイン").grid(row=0, column=0, sticky="w", pady=3)
        preset_combo = ttk.Combobox(
            controls,
            textvariable=self.display_preset_var,
            state="readonly",
            values=tuple(DISPLAY_PRESETS.keys()),
        )
        preset_combo.grid(row=0, column=1, sticky="ew", padx=(8, 16), pady=3)
        preset_combo.bind("<<ComboboxSelected>>", lambda event: self._apply_display_style())
        ttk.Label(controls, text="フォント").grid(row=0, column=2, sticky="w", pady=3)
        font_combo = ttk.Combobox(
            controls,
            textvariable=self.font_choice_var,
            state="readonly",
            values=tuple(FONT_CHOICES.keys()),
        )
        font_combo.grid(row=0, column=3, sticky="ew", padx=(8, 0), pady=3)
        font_combo.bind("<<ComboboxSelected>>", lambda event: self._apply_display_style())
        ttk.Label(controls, text="文字サイズ").grid(row=1, column=0, sticky="w", pady=3)
        font_size_combo = ttk.Combobox(
            controls,
            textvariable=self.font_size_var,
            state="readonly",
            values=tuple(FONT_SIZE_CHOICES.keys()),
        )
        font_size_combo.grid(row=1, column=1, sticky="ew", padx=(8, 16), pady=3)
        font_size_combo.bind("<<ComboboxSelected>>", lambda event: self._apply_display_style())
        ttk.Label(controls, text="クレジット表記").grid(row=1, column=2, sticky="w", pady=3)
        credit_combo = ttk.Combobox(
            controls,
            textvariable=self.credit_format_var,
            state="readonly",
            values=tuple(CREDIT_STYLE_CHOICES.keys()),
        )
        credit_combo.grid(row=1, column=3, sticky="ew", padx=(8, 0), pady=3)
        credit_combo.bind("<<ComboboxSelected>>", lambda event: self._apply_display_style())
        ttk.Button(controls, text="実ブラウザで確認", command=self._open_preview).grid(
            row=2, column=0, columnspan=4, sticky="ew", pady=(7, 3)
        )
        ttk.Label(
            controls,
            text="自動は1行に収まるよう縮小します。小・標準・大は選んだ大きさを保ち、長い文字を折り返します。",
            wraplength=600,
        ).grid(row=3, column=0, columnspan=4, sticky="w", pady=(5, 0))

        connection = ttk.LabelFrame(parent, text="OBS接続（最初の1回だけ）", padding=10)
        connection.pack(fill="x", pady=(10, 0))
        ttk.Label(
            connection,
            text="OBSのブラウザソースへ登録します。幅1920・高さ1080を推奨します。",
            wraplength=600,
        ).pack(anchor="w", pady=(0, 6))
        url_frame = ttk.Frame(connection)
        url_frame.pack(fill="x")
        ttk.Entry(url_frame, textvariable=self.overlay_url_var, state="readonly").pack(
            side="left", fill="x", expand=True
        )
        ttk.Button(url_frame, text="URLをコピー", command=self._copy_overlay_url).pack(side="left", padx=(8, 0))

    def _preset_label_from_settings(self):
        for label, values in DISPLAY_PRESETS.items():
            if (
                values["theme"] == self.display_settings.get("theme")
                and values["panel"] == self.display_settings.get("panel")
            ):
                return label
        return "標準（暗いパネル）"

    def _current_display_settings(self):
        preset = DISPLAY_PRESETS.get(
            self.display_preset_var.get(), DISPLAY_PRESETS["標準（暗いパネル）"]
        )
        return {
            "theme": preset["theme"],
            "panel": preset["panel"],
            "font": FONT_CHOICES.get(self.font_choice_var.get(), "gothic"),
            "font_size": FONT_SIZE_CHOICES.get(self.font_size_var.get(), "auto"),
            "credit_style": CREDIT_STYLE_CHOICES.get(self.credit_format_var.get(), "jp"),
        }

    def _apply_display_style(self):
        settings = self._current_display_settings()
        self.display_settings = settings
        self.state_store.set_style(
            theme=settings["theme"],
            panel=settings["panel"],
            font=settings["font"],
            font_size=settings["font_size"],
        )
        if self.overlay_visible and self.current_display_record:
            self.state_store.show_record(self.current_display_record, settings["credit_style"])
        try:
            manager_core.save_display_settings(settings)
        except core.SongCreditError as exc:
            self._set_status(str(exc))
            self._refresh_display_preview()
            return
        self._refresh_display_preview()
        self._set_status(
            "表示デザインを変更しました（文字サイズ：{}）。OBSにも反映されます。".format(
                self.font_size_var.get()
            )
        )

    def _preview_record(self):
        title = self.title_var.get().strip()
        artist = self.artist_var.get().strip()
        if title or artist:
            return manager_core.normalize_record(
                {
                    "title": title or "曲名プレビュー",
                    "artist": artist,
                    "lyricists": self._split_people(self.lyricists_var.get()),
                    "composers": self._split_people(self.composers_var.get()),
                    "arrangers": self._split_people(self.arrangers_var.get()),
                    "writers": self._split_people(self.writers_var.get()),
                }
            )
        index = self._selected_index() if hasattr(self, "setlist_box") else -1
        if 0 <= index < len(self.document.items):
            return self.document.items[index]
        return manager_core.normalize_record(
            {
                "title": "夜に駆ける",
                "artist": "YOASOBI",
                "lyricists": ["Ayase"],
                "composers": ["Ayase"],
                "arrangers": ["Ayase"],
            }
        )

    def _refresh_display_preview(self):
        if not hasattr(self, "preview_canvas") or not self.preview_canvas.winfo_exists():
            return
        canvas = self.preview_canvas
        canvas.delete("all")
        width = max(canvas.winfo_width(), 640)
        height = max(canvas.winfo_height(), 230)
        settings = self._current_display_settings()
        record = self._preview_record()
        outputs = core.build_outputs(record, settings["credit_style"])

        canvas.configure(background="#151922")
        canvas.create_text(
            14,
            12,
            text="アプリ内プレビュー（OBS表示の概略）",
            anchor="nw",
            fill="#aab4c3",
            font=("Yu Gothic UI", 9),
        )
        left = max(28, int(width * 0.075))
        right = min(width - 28, int(width * 0.925))
        top = max(52, int(height * 0.26))
        bottom = height - 22
        if settings["theme"] == "light":
            panel_color = "#eef4fb"
            title_color = "#111827"
            artist_color = "#26344a"
            credits_color = "#43516a"
            accent_color = "#087ea4"
            border_color = "#95a2b6"
        else:
            panel_color = "#172033"
            title_color = "#ffffff"
            artist_color = "#d9e3f3"
            credits_color = "#b8c7dc"
            accent_color = "#66d9ff"
            border_color = "#66738a"
        if settings["panel"]:
            canvas.create_rectangle(
                left, top, right, bottom, fill=panel_color, outline=border_color, width=1
            )
        canvas.create_rectangle(left, top, left + 5, bottom, fill=accent_color, outline=accent_color)

        font_family = {
            "gothic": "Yu Gothic UI",
            "rounded": "BIZ UDPGothic",
            "mincho": "Yu Mincho",
            "sans": "Segoe UI",
        }.get(settings["font"], "Yu Gothic UI")
        text_left = left + 22
        text_width = max(100, right - text_left - 14)
        title_text = outputs["title"] or "曲名プレビュー"
        title_size, artist_size, credits_size = PREVIEW_FONT_SIZES.get(
            settings["font_size"], PREVIEW_FONT_SIZES["auto"]
        )
        if settings["font_size"] == "auto":
            title_size = self._fit_preview_font_size(
                title_text, font_family, title_size, 7, text_width, "bold"
            )
            artist_size = self._fit_preview_font_size(
                outputs["artist"], font_family, artist_size, 7, text_width, "bold"
            )
            credits_size = self._fit_preview_font_size(
                outputs["credits"], font_family, credits_size, 6, text_width, "normal"
            )
        title_item = canvas.create_text(
            text_left,
            top + 14,
            text=title_text,
            anchor="nw",
            width=text_width,
            fill=title_color,
            font=(font_family, title_size, "bold"),
        )
        title_box = canvas.bbox(title_item) or (text_left, top + 14, text_left, top + 40)
        artist_top = max(top + 48, title_box[3] + 4)
        if outputs["artist"]:
            canvas.create_text(
                text_left,
                artist_top,
                text=outputs["artist"],
                anchor="nw",
                width=text_width,
                fill=artist_color,
                font=(font_family, artist_size, "bold"),
            )
        if outputs["credits"]:
            canvas.create_text(
                text_left,
                bottom - 16,
                text=outputs["credits"],
                anchor="sw",
                width=text_width,
                fill=credits_color,
                font=(font_family, credits_size),
            )

    def _fit_preview_font_size(self, text, family, preferred, minimum, max_width, weight):
        if not text:
            return preferred
        for size in range(preferred, minimum - 1, -1):
            try:
                measured = tkfont.Font(
                    root=self.root, family=family, size=size, weight=weight
                ).measure(text)
            except tk.TclError:
                return preferred
            if measured <= max_width:
                return size
        return minimum

    def _set_status(self, message):
        self.status_var.set(str(message))

    def _start_server(self):
        try:
            url = self.server.start()
        except OSError as exc:
            self.server_status_var.set("表示サーバー：起動失敗")
            self._set_status("表示サーバーを起動できませんでした: {}".format(exc))
            messagebox.showerror(
                "表示サーバーを起動できません",
                "ポート{}を使用できません。別のSong Credit Manager for OBSが起動していないか確認してください。\n\n{}".format(
                    DEFAULT_PORT, exc
                ),
            )
            return
        self.overlay_url_var.set(url)
        self.server_status_var.set("表示サーバー：起動中")
        if self.tutorial_loaded:
            self._set_status(
                "チュートリアルの{}曲を読み込みました。曲を選び［選択曲を表示］で試せます。".format(
                    len(self.document.items)
                )
            )
        else:
            self._set_status("準備できました。OBSへ表示URLを登録してください。")

    def _selected_index(self):
        selection = self.setlist_box.curselection()
        return int(selection[0]) if selection else -1

    def _select_index(self, index):
        self.setlist_box.selection_clear(0, tk.END)
        if 0 <= index < len(self.document.items):
            self.setlist_box.selection_set(index)
            self.setlist_box.activate(index)
            self.setlist_box.see(index)
        self._update_setlist_action_states()

    def _update_setlist_action_states(self):
        index = self._selected_index()
        item_count = len(self.document.items)
        has_selection = 0 <= index < item_count
        self.move_up_button.configure(state="normal" if has_selection and index > 0 else "disabled")
        self.move_down_button.configure(
            state="normal" if has_selection and index < item_count - 1 else "disabled"
        )
        self.remove_button.configure(state="normal" if has_selection else "disabled")
        if self.overlay_visible:
            self.display_toggle_button.configure(text="表示を消す", state="normal")
        else:
            self.display_toggle_button.configure(
                text="選択曲を表示", state="normal" if has_selection else "disabled"
            )

    def _refresh_setlist(self, select_index=None):
        previous = self._selected_index() if select_index is None else select_index
        self.setlist_box.delete(0, tk.END)
        for index, item in enumerate(self.document.items, 1):
            self.setlist_box.insert(tk.END, "{:02d}. {}".format(index, core.record_label(item)))
        self.setlist_name_var.set(self.document.name)
        dirty = "（未保存の変更あり）" if self.document.dirty else ""
        self.setlist_summary_var.set("{}曲 {}".format(len(self.document.items), dirty).strip())
        if self.tutorial_loaded and not self.document.path:
            self.setlist_path_var.set("チュートリアル見本（保存すると自分用ファイルになります）")
        else:
            self.setlist_path_var.set(self.document.path or "未保存")
        if self.document.items:
            previous = max(0, min(previous if previous >= 0 else 0, len(self.document.items) - 1))
            self._select_index(previous)
        else:
            self._update_setlist_action_states()

    def _credit_style(self):
        return CREDIT_STYLE_CHOICES.get(self.credit_format_var.get(), "jp")

    def _show_index(self, index):
        if not 0 <= index < len(self.document.items):
            self._set_status("表示する曲を選択してください。")
            return False
        try:
            record = self.document.items[index]
            self.state_store.show_record(record, self._credit_style())
        except core.SongCreditError as exc:
            self._set_status(str(exc))
            return False
        self.play_index = index
        self.overlay_visible = True
        self.current_display_record = dict(record)
        self._select_index(index)
        label = core.record_label(self.document.items[index])
        self.last_display_label = label
        self.now_playing_var.set("{:02d}. {}".format(index + 1, label))
        self._set_status("OBSへ「{}」を表示しました。".format(label))
        self._update_setlist_action_states()
        return True

    def _display_selected(self):
        self._show_index(self._selected_index())

    def _toggle_overlay(self):
        if self.overlay_visible:
            self._hide_overlay()
        else:
            self._display_selected()

    def _display_next(self):
        if not self.document.items:
            self._set_status("セットリストに曲がありません。")
            return
        if self.play_index < 0:
            target = self._selected_index()
            target = target if target >= 0 else 0
        else:
            target = self.play_index + 1
        if target >= len(self.document.items):
            self._set_status("セットリストの最後です。")
            return
        self._show_index(target)

    def _display_previous(self):
        if not self.document.items:
            self._set_status("セットリストに曲がありません。")
            return
        if self.play_index < 0:
            target = self._selected_index()
            target = target if target >= 0 else 0
        else:
            target = self.play_index - 1
        if target < 0:
            self._set_status("セットリストの先頭です。")
            return
        self._show_index(target)

    def _hide_overlay(self):
        self.state_store.hide()
        self.overlay_visible = False
        if self.last_display_label:
            self.now_playing_var.set("非表示（直前：{}）".format(self.last_display_label))
        else:
            self.now_playing_var.set("非表示")
        self._set_status("OBSの表示を消しました。")
        self._update_setlist_action_states()

    def _split_people(self, value):
        return [part.strip() for part in value.replace(",", "、").replace("/", "、").split("、") if part.strip()]

    def _editor_record(self):
        record = dict(self.editor_metadata)
        record.update(
            {
                "title": self.title_var.get().strip(),
                "artist": self.artist_var.get().strip(),
                "lyricists": self._split_people(self.lyricists_var.get()),
                "composers": self._split_people(self.composers_var.get()),
                "arrangers": self._split_people(self.arrangers_var.get()),
                "writers": self._split_people(self.writers_var.get()),
                "notes": [line.strip() for line in self.notes_text.get("1.0", tk.END).splitlines() if line.strip()],
            }
        )
        return manager_core.validate_record(record)

    def _set_editor_record(self, record):
        record = manager_core.normalize_record(record)
        self.title_var.set(record["title"])
        self.artist_var.set(record["artist"])
        self.lyricists_var.set("、".join(record["lyricists"]))
        self.composers_var.set("、".join(record["composers"]))
        self.arrangers_var.set("、".join(record["arrangers"]))
        self.writers_var.set("、".join(record["writers"]))
        self.notes_text.delete("1.0", tk.END)
        self.notes_text.insert("1.0", "\n".join(record["notes"]))
        self.editor_metadata = {
            "source": record.get("source") or "manual",
            "source_id": record.get("source_id") or "",
            "source_url": record.get("source_url") or "",
            "verified": bool(record.get("verified", False)),
        }
        if record.get("fetched_at"):
            self.editor_metadata["fetched_at"] = record["fetched_at"]

    def _load_selected_into_editor(self):
        index = self._selected_index()
        if not 0 <= index < len(self.document.items):
            self._set_status("編集する曲を選択してください。")
            return
        self._set_editor_record(self.document.items[index])
        self.search_title_var.set(self.document.items[index]["title"])
        self.search_artist_var.set(self.document.items[index]["artist"])
        self._set_status("選択曲を編集欄へ読み込みました。")

    def _add_editor_record(self):
        try:
            index = self.document.add(self._editor_record())
        except core.SongCreditError as exc:
            self._set_status(str(exc))
            return
        self._refresh_setlist(index)
        self._set_status("セットリストへ追加しました。保存してください。")

    def _update_selected_record(self):
        index = self._selected_index()
        try:
            self.document.update(index, self._editor_record())
        except core.SongCreditError as exc:
            self._set_status(str(exc))
            return
        self._refresh_setlist(index)
        self._set_status("選択曲を更新しました。保存してください。")

    def _show_editor_record(self):
        try:
            record = self._editor_record()
            self.state_store.show_record(record, self._credit_style())
        except core.SongCreditError as exc:
            self._set_status(str(exc))
            return
        label = core.record_label(record)
        self.overlay_visible = True
        self.current_display_record = dict(record)
        self.last_display_label = label
        self.now_playing_var.set("リクエスト／臨時：{}".format(label))
        self._set_status("OBSへ「{}」を緊急表示しました。".format(label))
        self._update_setlist_action_states()

    def _run_background(self, task, on_success, working_message):
        self._set_status(working_message)

        def runner():
            try:
                result = task()
            except Exception as exc:
                if not self.closing:
                    message = "エラー: {}".format(exc)
                    self.root.after(0, lambda value=message: self._set_status(value))
                return
            if not self.closing:
                self.root.after(0, lambda: on_success(result))

        thread = threading.Thread(target=runner)
        thread.daemon = True
        thread.start()

    def _search_musicbrainz(self):
        title = self.search_title_var.get().strip()
        artist = self.search_artist_var.get().strip()
        if not title:
            self._set_status("検索する曲名を入力してください。")
            return
        self.search_query_title = title
        self.search_query_artist = artist
        self._load_search_page(0)

    def _load_search_page(self, offset):
        title = self.search_query_title
        artist = self.search_query_artist
        offset = max(0, int(offset))

        def on_success(page):
            self._apply_search_page(page)

        self._run_background(
            lambda: self.client.search_recordings_page(
                title, artist, limit=SEARCH_PAGE_SIZE, offset=offset
            ),
            on_success,
            "MusicBrainzを検索しています…",
        )

    def _apply_search_page(self, page):
        self.search_results = list(page.get("items") or [])
        self.search_total = max(0, int(page.get("count") or 0))
        self.search_offset = max(0, int(page.get("offset") or 0))

        for item_id in self.candidate_tree.get_children():
            self.candidate_tree.delete(item_id)
        for index, candidate in enumerate(self.search_results):
            date = (candidate.get("date") or "").split("-", 1)[0]
            self.candidate_tree.insert(
                "",
                "end",
                iid=str(index),
                text=candidate.get("title") or "",
                values=(
                    candidate.get("artist") or "",
                    date,
                    candidate.get("release") or "",
                ),
            )
        if self.search_results:
            self.candidate_tree.selection_set("0")
            self.candidate_tree.focus("0")
            self.candidate_tree.see("0")

        artists = core.artist_candidates(self.search_results)
        self.artist_candidate_combo["values"] = (ARTIST_CANDIDATE_PLACEHOLDER,) + tuple(artists)
        self.artist_candidate_var.set(ARTIST_CANDIDATE_PLACEHOLDER)

        shown = len(self.search_results)
        if shown:
            first = self.search_offset + 1
            last = self.search_offset + shown
            self.search_summary_var.set("全{}件中 {}～{}件を表示".format(self.search_total, first, last))
            self._set_status(
                "検索候補を{}件表示しています。候補を選んでクレジットを取得してください。".format(shown)
            )
        else:
            self.search_summary_var.set("検索結果：全{}件（このページに候補はありません）".format(self.search_total))
            self._set_status("候補が見つかりませんでした。条件を変えるか、手入力してください。")

        self.previous_results_button.configure(
            state="normal" if self.search_offset > 0 else "disabled"
        )
        self.next_results_button.configure(
            state=(
                "normal"
                if shown and self.search_offset + SEARCH_PAGE_SIZE < self.search_total
                else "disabled"
            )
        )

    def _previous_search_page(self):
        if self.search_offset <= 0:
            return
        self._load_search_page(max(0, self.search_offset - SEARCH_PAGE_SIZE))

    def _next_search_page(self):
        next_offset = self.search_offset + SEARCH_PAGE_SIZE
        if not self.search_results or next_offset >= self.search_total:
            return
        self._load_search_page(next_offset)

    def _filter_by_artist_candidate(self):
        artist = self.artist_candidate_var.get().strip()
        if not artist or artist == ARTIST_CANDIDATE_PLACEHOLDER:
            self._set_status("絞り込むアーティスト候補を選択してください。")
            return
        self.search_artist_var.set(artist)
        self._search_musicbrainz()

    def _selected_search_result_index(self):
        selection = self.candidate_tree.selection()
        if not selection:
            return -1
        try:
            return int(selection[0])
        except (TypeError, ValueError):
            return -1

    def _fetch_selected_credits(self):
        index = self._selected_search_result_index()
        if not 0 <= index < len(self.search_results):
            self._set_status("検索候補を選択してください。")
            return
        recording_id = self.search_results[index]["id"]

        def on_success(record):
            self._set_editor_record(record)
            self._set_status("クレジットを取得しました。公式情報でも確認してください。")

        self._run_background(
            lambda: self.client.fetch_credits(recording_id), on_success, "クレジットを取得しています…"
        )

    def _move_selected(self, offset):
        index = self._selected_index()
        target = self.document.move(index, offset)
        if target == index:
            self._set_status("これ以上移動できません。")
            return
        if self.play_index == index:
            self.play_index = target
        elif self.play_index == target:
            self.play_index = index
        self._refresh_setlist(target)
        self._set_status("曲順を変更しました。保存してください。")

    def _remove_selected(self):
        index = self._selected_index()
        if not 0 <= index < len(self.document.items):
            self._set_status("削除する曲を選択してください。")
            return
        label = core.record_label(self.document.items[index])
        if not messagebox.askyesno("曲を削除", "「{}」をセットリストから削除しますか？".format(label)):
            return
        self.document.remove(index)
        if self.play_index == index:
            self.play_index = -1
        elif self.play_index > index:
            self.play_index -= 1
        self._refresh_setlist(min(index, len(self.document.items) - 1))
        self._set_status("曲を削除しました。保存してください。")

    def _confirm_discard(self):
        if not self.document.dirty:
            return True
        answer = messagebox.askyesnocancel("未保存の変更", "変更を保存してから続けますか？")
        if answer is None:
            return False
        if answer:
            return self._save_setlist()
        return True

    def _new_setlist(self):
        if not self._confirm_discard():
            return
        name = simpledialog.askstring("新しいセットリスト", "セットリスト名を入力してください。", parent=self.root)
        if name is None:
            return
        self.document = manager_core.SetlistDocument(name=name)
        self.tutorial_loaded = False
        self.play_index = -1
        self._refresh_setlist()
        self._set_status("新しいセットリストを作成しました。")

    def _open_setlist(self):
        if not self._confirm_discard():
            return
        path = filedialog.askopenfilename(
            parent=self.root,
            title="セットリストを開く",
            initialdir=manager_core.default_setlists_dir(),
            filetypes=(("Song Credit Setlist", "*.scolist.json *.json"), ("JSON", "*.json"), ("すべて", "*.*")),
        )
        if not path:
            return
        try:
            self.document = manager_core.SetlistDocument.load(path)
        except core.SongCreditError as exc:
            messagebox.showerror("読み込みエラー", str(exc))
            return
        self.tutorial_loaded = False
        self.play_index = -1
        self._refresh_setlist(0)
        self._set_status("セットリストを開きました。")

    def _save_setlist(self):
        try:
            self.document.rename(self.setlist_name_var.get())
        except core.SongCreditError as exc:
            self._set_status(str(exc))
            return False
        if not self.document.path:
            return self._save_setlist_as()
        try:
            self.document.save()
        except core.SongCreditError as exc:
            messagebox.showerror("保存エラー", str(exc))
            return False
        self._refresh_setlist(self._selected_index())
        self._set_status("セットリストを保存しました。")
        return True

    def _save_setlist_as(self):
        try:
            self.document.rename(self.setlist_name_var.get())
        except core.SongCreditError as exc:
            self._set_status(str(exc))
            return False
        initial_path = manager_core.suggested_setlist_path(self.document.name)
        path = filedialog.asksaveasfilename(
            parent=self.root,
            title="セットリストを保存",
            initialdir=os.path.dirname(initial_path),
            initialfile=os.path.basename(initial_path),
            defaultextension=manager_core.SETLIST_EXTENSION,
            filetypes=(("Song Credit Setlist", "*.scolist.json"), ("JSON", "*.json")),
        )
        if not path:
            return False
        try:
            self.document.save(path)
        except core.SongCreditError as exc:
            messagebox.showerror("保存エラー", str(exc))
            return False
        self.tutorial_loaded = False
        self._refresh_setlist(self._selected_index())
        self._set_status("セットリストを保存しました。")
        return True

    def _import_setlist(self):
        if not self._confirm_discard():
            return
        path = filedialog.askopenfilename(
            parent=self.root,
            title="CSV／TSV／TXTを読み込む",
            filetypes=(("表・テキスト", "*.csv *.tsv *.txt"), ("CSV", "*.csv"), ("すべて", "*.*")),
        )
        if not path:
            return
        try:
            self.document = manager_core.SetlistDocument.load(path)
        except core.SongCreditError as exc:
            messagebox.showerror("読み込みエラー", str(exc))
            return
        self.tutorial_loaded = False
        self.play_index = -1
        self._refresh_setlist(0)
        self._set_status("{}曲を読み込みました。専用形式で保存してください。".format(len(self.document.items)))

    def _restore_tutorial_setlist(self):
        if not self._confirm_discard():
            return
        try:
            self.document = load_bundled_tutorial_document()
        except core.SongCreditError as exc:
            messagebox.showerror("チュートリアル読み込みエラー", str(exc))
            return
        self.tutorial_loaded = True
        self.play_index = -1
        self._refresh_setlist(0)
        self._set_status(
            "チュートリアルの{}曲を読み込みました。保存すると自分用ファイルになります。".format(
                len(self.document.items)
            )
        )

    def _export_csv(self):
        initial_name = os.path.splitext(os.path.basename(self.document.path))[0] if self.document.path else self.document.name
        path = filedialog.asksaveasfilename(
            parent=self.root,
            title="CSVへ書き出す",
            initialfile=initial_name + ".csv",
            defaultextension=".csv",
            filetypes=(("CSV", "*.csv"),),
        )
        if not path:
            return
        try:
            manager_core.export_setlist_csv(path, self.document.items)
        except core.SongCreditError as exc:
            messagebox.showerror("書き出しエラー", str(exc))
            return
        self._set_status("CSVを書き出しました。")

    def _copy_text(self, text):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.root.update_idletasks()
        self._set_status("クリップボードへコピーしました。")

    def _copy_overlay_url(self):
        self._copy_text(self.overlay_url_var.get())

    def _open_preview(self):
        if not self.server.running:
            self._set_status("表示サーバーが起動していません。")
            return
        webbrowser.open(self.overlay_url_var.get())

    def _on_close(self):
        if not self._confirm_discard():
            return
        self.closing = True
        self.server.stop()
        self.root.destroy()


def main():
    root = tk.Tk()
    SongCreditManagerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
