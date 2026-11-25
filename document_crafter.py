"""
Wajeeha Document Crafter
Generates a formal letter/application draft with an OpenAI-compatible API
(LM Studio, Ollama, OpenAI, etc.), lets you edit it in a formatted preview,
and saves it as RTF.
Standard library only (tkinter + urllib) so it packages cleanly with PyInstaller.
"""
import datetime
import json
import os
import re
import sys
import threading
import tkinter as tk
import urllib.error
import urllib.request
from tkinter import filedialog, messagebox, ttk

APP_TITLE = "Wajeeha Document Crafter"
TIMEOUT_SECONDS = 7200  # long timeout for slow local models (LM Studio)

BASE_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))
CONFIG_PATH = os.path.join(BASE_DIR, "crafter_config.json")

CLOSING_LINE = (
    "I shall be highly grateful for your kind consideration and necessary action in this regard."
)

DEFAULT_SYSTEM_PROMPT = (
    "You are an expert correspondence writer for Pakistani government and official offices. "
    "Write in formal, polite, concise English suitable for an official application or letter. "
    "Output ONLY the body paragraphs of the letter. Do not include the salutation, the subject line, "
    "the closing line, the signature block, or the date. Do not use markdown, headings, or bullet points."
)

DEFAULT_USER_PROMPT = (
    "Write the main body of this application on the subject above. Explain the matter clearly, "
    "state the request respectfully, and use 2 to 4 short paragraphs."
)

FAMILIES = ["Times New Roman", "Arial", "Calibri", "Cambria", "Georgia", "Verdana", "Courier New"]
DEFAULT_FAMILY = "Times New Roman"
DEFAULT_SIZE = 11

ALIGN_TAGS = {"left": "al_left", "center": "al_center", "right": "al_right", "justify": "al_full"}
ALIGN_NAMES = set(ALIGN_TAGS.values())
RTF_ALIGN = {"al_left": r"\ql", "al_center": r"\qc", "al_right": r"\qr", "al_full": r"\qj"}

ACCENT = "#1F4E79"
BG = "#F3F4F6"
PAPER = "#FFFFFF"


# ---------------------------------------------------------------- API helpers
def normalise_base_url(url):
    url = url.strip().rstrip("/")
    if url and not url.endswith("/v1"):
        url += "/v1"
    return url


def api_call(url, api_key, payload=None):
    """GET when payload is None, otherwise POST JSON. Returns parsed JSON."""
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    method = "POST" if payload is not None else "GET"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code} from server:\n{body[:500]}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Could not reach server: {e.reason}") from e


def fetch_models(base_url, api_key):
    data = api_call(f"{base_url}/models", api_key)
    return sorted(item["id"] for item in data.get("data", []) if "id" in item)


def clean_model_output(text):
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S | re.I)
    return text.strip()


def generate_body(base_url, api_key, model, system_prompt, user_prompt):
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.4,
        "stream": False,
    }
    data = api_call(f"{base_url}/chat/completions", api_key, payload)
    return clean_model_output(data["choices"][0]["message"]["content"])


# ---------------------------------------------------------- document building
def build_paragraphs(f, body):
    """Return list of (text, options) describing the letter layout."""
    sender_line = ", ".join(p for p in [f["organization"], f["section"]] if p)
    paras = [
        ("To", {"bold": True}),
        (f"The {f['to']},", {"indent": True}),
        (f"{f['organization']},", {"indent": True}),
        ("Government of Pakistan.", {"indent": True}),
        ("", {}),
        (f"SUBJECT: {f['subject'].upper()}", {"bold": True, "underline": True}),
        ("Respected Sir,", {}),
        ("", {}),
    ]
    for block in re.split(r"\n\s*\n", body):
        block = " ".join(block.split())
        if block:
            paras.append((block, {}))
            paras.append(("", {}))
    paras += [
        (CLOSING_LINE, {"indent": True}),
        ("", {}),
        ("Yours faithfully,", {"align": "right"}),
        ("", {}),
        ("", {}),
        (f["name"], {"align": "right"}),
        (f["post"], {"align": "right"}),
        (sender_line, {"align": "right"}),
        ("", {}),
        (f"Date: {f['date']}", {"bold": True}),
    ]
    return paras


def rtf_escape(text):
    out = []
    for ch in text:
        if ch in "\\{}":
            out.append("\\" + ch)
        elif ch == "\t":
            out.append("\\tab ")
        elif ord(ch) < 128:
            out.append(ch)
        else:
            code = ord(ch)
            if code > 32767:
                code -= 65536
            out.append(f"\\u{code}?")
    return "".join(out)


# ------------------------------------------------------------------ GUI
class CrafterApp:
    DOC_FIELDS = [
        ("to", "To (Recipient / Officer)"),
        ("subject", "Subject"),
        ("date", "Date"),
    ]
    SENDER_FIELDS = [
        ("name", "Employee Name"),
        ("post", "Designation / Post"),
        ("section", "Section"),
        ("organization", "Organization"),
    ]

    def __init__(self, root):
        self.root = root
        root.title(APP_TITLE)
        root.configure(bg=BG)

        # Size the window as a share of whatever screen it opens on.
        screen_w = root.winfo_screenwidth()
        screen_h = root.winfo_screenheight()
        width = int(screen_w * 0.75)
        height = int(screen_h * 0.8)
        x = max((screen_w - width) // 2, 0)
        y = max((screen_h - height) // 2 - 20, 0)
        root.geometry(f"{width}x{height}+{x}+{y}")
        root.minsize(int(screen_w * 0.5), int(screen_h * 0.5))

        self.vars = {}
        self.body = ""
        self.dirty = False          # True once the user has edited the preview
        self.style_tags = set()
        self.size_var = tk.StringVar(value=str(DEFAULT_SIZE))
        self.family_var = tk.StringVar(value=DEFAULT_FAMILY)

        self._setup_style()
        self._build_header()
        self._build_footer()        # packed first so it is never pushed off-screen
        self._build_body()
        self._load_config()
        root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------- styling
    def _setup_style(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", background=BG, font=("Segoe UI", 10))
        style.configure("TFrame", background=BG)
        style.configure("Sub.TLabel", background=BG, foreground="#555", font=("Segoe UI", 9))
        style.configure("Generate.TButton", font=("Segoe UI", 11, "bold"), padding=(18, 8),
                        background=ACCENT, foreground="white")
        style.map("Generate.TButton", background=[("disabled", "#8AA7C4"), ("active", "#163A5C")],
                  foreground=[("disabled", "white")])
        style.configure("TButton", padding=(10, 6))
        style.configure("Tool.TButton", padding=(6, 3), font=("Segoe UI", 9))

    # ---------- layout
    def _build_header(self):
        bar = tk.Frame(self.root, bg=ACCENT, height=52)
        bar.pack(side="top", fill="x")
        bar.pack_propagate(False)
        tk.Label(bar, text=APP_TITLE, bg=ACCENT, fg="white",
                 font=("Segoe UI", 15, "bold")).pack(side="left", padx=16)
        tk.Label(bar, text="AI-assisted formal letters", bg=ACCENT, fg="#CFE0F1",
                 font=("Segoe UI", 9)).pack(side="left", padx=4, pady=(6, 0))

    def _build_footer(self):
        foot = tk.Frame(self.root, bg="white", highlightthickness=1, highlightbackground="#D0D5DD")
        foot.pack(side="bottom", fill="x")
        inner = tk.Frame(foot, bg="white")
        inner.pack(fill="x", padx=14, pady=10)

        self.generate_btn = ttk.Button(inner, text="  ✦  GENERATE DRAFT  ",
                                       style="Generate.TButton", command=self._on_generate)
        self.generate_btn.pack(side="left")

        self.save_btn = ttk.Button(inner, text="Save as RTF…", command=self._on_save)
        self.save_btn.pack(side="right")

        mid = tk.Frame(inner, bg="white")
        mid.pack(side="left", fill="x", expand=True, padx=14)
        self.status_var = tk.StringVar(value="Fill the details, then click Generate Draft.")
        tk.Label(mid, textvariable=self.status_var, bg="white", fg="#333",
                 anchor="w", font=("Segoe UI", 9)).pack(fill="x")
        self.progress = ttk.Progressbar(mid, mode="indeterminate")
        self.progress.pack(fill="x", pady=(4, 0))

    def _build_body(self):
        body = ttk.Frame(self.root, padding=12)
        body.pack(side="top", fill="both", expand=True)

        # ---- LEFT: form inside a scrollable area
        left_outer = ttk.Frame(body)
        left_outer.pack(side="left", fill="y")
        canvas = tk.Canvas(left_outer, bg=BG, highlightthickness=0, width=400)
        scroll = ttk.Scrollbar(left_outer, orient="vertical", command=canvas.yview)
        form = ttk.Frame(canvas)
        form.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=form, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="y", expand=True)
        scroll.pack(side="right", fill="y")
        canvas.bind_all("<MouseWheel>",
                        lambda e: canvas.yview_scroll(int(-e.delta / 120), "units"))

        self._card(form, "Document", self.DOC_FIELDS)
        self._card(form, "Sender", self.SENDER_FIELDS)
        self._build_server_card(form)

        # ---- RIGHT: toolbar + editable preview on a grey "desk"
        right = ttk.Frame(body)
        right.pack(side="left", fill="both", expand=True, padx=(12, 0))
        self._build_toolbar(right)

        page_wrap = tk.Frame(right, bg="#D9DDE3", padx=18, pady=18)
        page_wrap.pack(fill="both", expand=True)
        self.preview = tk.Text(page_wrap, wrap="word", width=20, padx=60, pady=45, bg=PAPER,
                               relief="flat", bd=0, undo=True, font=("Times New Roman", 11),
                               highlightthickness=0, tabs=("1c",))
        pv_scroll = ttk.Scrollbar(page_wrap, orient="vertical", command=self.preview.yview)
        self.preview.configure(yscrollcommand=pv_scroll.set)
        self.preview.pack(side="left", fill="both", expand=True)
        pv_scroll.pack(side="right", fill="y")

        for alignment in ALIGN_TAGS.values():
            self.preview.tag_configure(alignment, justify={"al_left": "left", "al_center": "center",
                                                           "al_right": "right", "al_full": "left"}[alignment])
        self.preview.tag_configure("al_full", justify="left")

        # Keyboard shortcuts
        self.preview.bind("<Control-b>", lambda e: self._shortcut(lambda: self._toggle("b")))
        self.preview.bind("<Control-i>", lambda e: self._shortcut(lambda: self._toggle("i")))
        self.preview.bind("<Control-u>", lambda e: self._shortcut(lambda: self._toggle("u")))
        self.preview.bind("<<Modified>>", self._on_modified)
        self.preview.bind("<Tab>", self._on_tab)
        self._show_placeholder()

    def _build_toolbar(self, parent):
        bar = tk.Frame(parent, bg="white", highlightthickness=1, highlightbackground="#D0D5DD")
        bar.pack(fill="x", pady=(0, 6))
        row1 = tk.Frame(bar, bg="white")
        row1.pack(fill="x", padx=6, pady=(5, 2))
        row2 = tk.Frame(bar, bg="white")
        row2.pack(fill="x", padx=6, pady=(2, 5))

        def btn(parent_row, text, cmd, width=None):
            b = ttk.Button(parent_row, text=text, style="Tool.TButton", command=cmd, width=width)
            b.pack(side="left", padx=2, pady=1)
            return b

        def sep(parent_row):
            ttk.Separator(parent_row, orient="vertical").pack(side="left", fill="y", padx=6)

        # Row 1: font, size, B/I/U, alignment
        fam = ttk.Combobox(row1, values=FAMILIES, textvariable=self.family_var,
                           width=13, state="readonly")
        fam.pack(side="left", padx=2)
        fam.bind("<<ComboboxSelected>>", lambda e: self._apply_family())
        size = tk.Spinbox(row1, from_=6, to=72, width=4, textvariable=self.size_var,
                          command=self._apply_size, justify="center")
        size.pack(side="left", padx=2)
        size.bind("<Return>", lambda e: self._apply_size())
        sep(row1)
        btn(row1, "B", lambda: self._toggle("b"), width=3)
        btn(row1, "I", lambda: self._toggle("i"), width=3)
        btn(row1, "U", lambda: self._toggle("u"), width=3)
        sep(row1)
        btn(row1, "Left", lambda: self._align("left"))
        btn(row1, "Center", lambda: self._align("center"))
        btn(row1, "Right", lambda: self._align("right"))
        btn(row1, "Justify", lambda: self._align("justify"))

        # Row 2: indent, bullets, undo/redo, clear
        btn(row2, "Indent →", self._indent)
        btn(row2, "← Outdent", self._outdent)
        btn(row2, "• Bullet", self._bullet)
        sep(row2)
        btn(row2, "Undo", self._undo)
        btn(row2, "Redo", self._redo)
        sep(row2)
        btn(row2, "Clear format", self._clear_format)

        tk.Label(parent, text="Select text, then use the buttons. Ctrl+B / Ctrl+I / Ctrl+U work too. "
                              "Tab inserts a tab.", bg=BG, fg="#555",
                 font=("Segoe UI", 8), wraplength=600, justify="left").pack(anchor="w", pady=(0, 4))

    def _card(self, parent, title, fields):
        card = tk.Frame(parent, bg="white", highlightthickness=1, highlightbackground="#D0D5DD")
        card.pack(fill="x", pady=(0, 10), padx=(0, 8))
        tk.Label(card, text=title, bg="white", fg=ACCENT,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=12, pady=(10, 4))
        grid = tk.Frame(card, bg="white")
        grid.pack(fill="x", padx=12, pady=(0, 12))
        grid.columnconfigure(1, weight=1)
        for r, (key, label) in enumerate(fields):
            tk.Label(grid, text=label, bg="white", fg="#333",
                     font=("Segoe UI", 9)).grid(row=r, column=0, sticky="w", pady=4, padx=(0, 10))
            self.vars[key] = tk.StringVar()
            ttk.Entry(grid, textvariable=self.vars[key], width=30).grid(
                row=r, column=1, sticky="ew", pady=4)

    def _build_server_card(self, parent):
        card = tk.Frame(parent, bg="white", highlightthickness=1, highlightbackground="#D0D5DD")
        card.pack(fill="x", pady=(0, 10), padx=(0, 8))
        tk.Label(card, text="AI Server", bg="white", fg=ACCENT,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=12, pady=(10, 4))
        grid = tk.Frame(card, bg="white")
        grid.pack(fill="x", padx=12, pady=(0, 12))
        grid.columnconfigure(1, weight=1)

        rows = [("server", "Server API URL (v1)", None), ("key", "API Key", "*")]
        for r, (key, label, show) in enumerate(rows):
            tk.Label(grid, text=label, bg="white", fg="#333",
                     font=("Segoe UI", 9)).grid(row=r, column=0, sticky="w", pady=4, padx=(0, 10))
            self.vars[key] = tk.StringVar()
            ttk.Entry(grid, textvariable=self.vars[key], width=30,
                      show=show or "").grid(row=r, column=1, sticky="ew", pady=4)

        tk.Label(grid, text="Model", bg="white", fg="#333",
                 font=("Segoe UI", 9)).grid(row=2, column=0, sticky="w", pady=4, padx=(0, 10))
        mrow = tk.Frame(grid, bg="white")
        mrow.grid(row=2, column=1, sticky="ew", pady=4)
        self.vars["model"] = tk.StringVar()
        self.model_combo = ttk.Combobox(mrow, textvariable=self.vars["model"], width=22)
        self.model_combo.pack(side="left", fill="x", expand=True)
        self.fetch_btn = ttk.Button(mrow, text="Fetch Models", command=self._on_fetch_models)
        self.fetch_btn.pack(side="left", padx=(6, 0))

        tk.Label(grid, text="System prompt", bg="white", fg="#333",
                 font=("Segoe UI", 9)).grid(row=3, column=0, sticky="nw", pady=(8, 4), padx=(0, 10))
        self.system_text = self._text_box(grid, 5, DEFAULT_SYSTEM_PROMPT)
        self.system_text.master.grid(row=3, column=1, sticky="ew", pady=(8, 4))

        tk.Label(grid, text="User prompt", bg="white", fg="#333",
                 font=("Segoe UI", 9)).grid(row=4, column=0, sticky="nw", pady=4, padx=(0, 10))
        self.user_text = self._text_box(grid, 4, DEFAULT_USER_PROMPT)
        self.user_text.master.grid(row=4, column=1, sticky="ew", pady=4)

    def _text_box(self, parent, height, default):
        frame = tk.Frame(parent, bg="#B8C0CC", padx=1, pady=1)
        widget = tk.Text(frame, height=height, width=32, wrap="word", relief="flat",
                         font=("Segoe UI", 9), padx=6, pady=4, highlightthickness=0)
        widget.insert("1.0", default)
        widget.pack(fill="x", expand=True)
        return widget

    # ---------- helpers
    def _v(self, key):
        return self.vars[key].get().strip()

    def _t(self, widget):
        return widget.get("1.0", "end").strip()

    def _msg(self, text):
        self.status_var.set(text)

    def _set_busy(self, busy, message=""):
        state = "disabled" if busy else "normal"
        self.generate_btn.configure(state=state)
        self.fetch_btn.configure(state=state)
        if busy:
            self.progress.start(12)
        else:
            self.progress.stop()
        self.status_var.set(message)

    def _run_async(self, func, on_done, on_error):
        def target():
            try:
                result = func()
            except Exception as exc:  # noqa: BLE001
                err = exc
                self.root.after(0, lambda: on_error(err))
                return
            self.root.after(0, lambda: on_done(result))

        threading.Thread(target=target, daemon=True).start()

    # ---------- style tags: each run of text gets one combined tag
    def _style_tag(self, b, i, u, size, family):
        name = f"st|{int(b)}|{int(i)}|{int(u)}|{int(size)}|{family}"
        if name not in self.style_tags:
            styles = [s for flag, s in ((b, "bold"), (i, "italic"), (u, "underline")) if flag]
            self.preview.tag_configure(name, font=(family, int(size), *styles))
            self.style_tags.add(name)
        return name

    @staticmethod
    def _parse_style(tag):
        _, b, i, u, size, family = tag.split("|", 5)
        return {"b": b == "1", "i": i == "1", "u": u == "1", "size": int(size), "family": family}

    def _style_at(self, index):
        for name in self.preview.tag_names(index):
            if name.startswith("st|"):
                return self._parse_style(name)
        return {"b": False, "i": False, "u": False, "size": DEFAULT_SIZE, "family": DEFAULT_FAMILY}

    def _sel_range(self):
        try:
            return self.preview.index("sel.first"), self.preview.index("sel.last")
        except tk.TclError:
            return None

    def _restyle(self, start, end, **changes):
        t = self.preview
        idx = start
        while t.compare(idx, "<", end):
            nxt = t.index(f"{idx}+1c")
            style = self._style_at(idx)
            style.update(changes)
            for name in t.tag_names(idx):
                if name.startswith("st|"):
                    t.tag_remove(name, idx, nxt)
            t.tag_add(self._style_tag(**style), idx, nxt)
            idx = nxt

    def _all_have(self, start, end, key):
        t = self.preview
        idx = start
        while t.compare(idx, "<", end):
            if not self._style_at(idx)[key]:
                return False
            idx = t.index(f"{idx}+1c")
        return True

    def _need_selection(self):
        rng = self._sel_range()
        if not rng:
            self._msg("Select some text first, then click the button.")
        return rng

    # ---------- toolbar actions
    def _toggle(self, key):
        rng = self._need_selection()
        if not rng:
            return
        turn_on = not self._all_have(rng[0], rng[1], key)
        names = {"b": "b", "i": "i", "u": "u"}
        self._restyle(rng[0], rng[1], **{names[key]: turn_on})

    def _apply_family(self):
        rng = self._need_selection()
        if rng:
            self._restyle(rng[0], rng[1], family=self.family_var.get())

    def _apply_size(self):
        try:
            size = max(6, min(72, int(self.size_var.get())))
        except ValueError:
            size = DEFAULT_SIZE
        self.size_var.set(str(size))
        rng = self._need_selection()
        if rng:
            self._restyle(rng[0], rng[1], size=size)

    def _line_span(self):
        """First and last line numbers covered by the selection (or the cursor line)."""
        rng = self._sel_range()
        start, end = rng if rng else (self.preview.index("insert"), self.preview.index("insert"))
        return int(start.split(".")[0]), int(end.split(".")[0])

    def _align(self, mode):
        first, last = self._line_span()
        tag = ALIGN_TAGS[mode]
        for ln in range(first, last + 1):
            a, b = f"{ln}.0", f"{ln}.0+1c"
            for old in ALIGN_NAMES:
                self.preview.tag_remove(old, a, b)
            self.preview.tag_add(tag, a, b)

    def _indent(self):
        first, last = self._line_span()
        for ln in range(first, last + 1):
            self.preview.insert(f"{ln}.0", "\t")

    def _outdent(self):
        first, last = self._line_span()
        for ln in range(first, last + 1):
            if self.preview.get(f"{ln}.0", f"{ln}.1") == "\t":
                self.preview.delete(f"{ln}.0", f"{ln}.1")

    def _bullet(self):
        first, last = self._line_span()
        for ln in range(first, last + 1):
            self.preview.insert(f"{ln}.0", "•  ")

    def _undo(self):
        try:
            self.preview.edit_undo()
        except tk.TclError:
            pass

    def _redo(self):
        try:
            self.preview.edit_redo()
        except tk.TclError:
            pass

    def _clear_format(self):
        rng = self._need_selection()
        if not rng:
            return
        self._restyle(rng[0], rng[1], b=False, i=False, u=False,
                      size=DEFAULT_SIZE, family=DEFAULT_FAMILY)
        self._align("left")

    def _shortcut(self, func):
        func()
        return "break"

    def _on_tab(self, event):
        self.preview.insert("insert", "\t")
        return "break"

    def _on_modified(self, event):
        if self.preview.edit_modified():
            self.preview.edit_modified(False)
            self.dirty = True

    # ---------- preview rendering
    def _show_placeholder(self):
        t = self.preview
        t.delete("1.0", "end")
        t.insert("end", "\n\n\nYour generated letter will appear here.\n\n"
                        "Fill in the details on the left and click GENERATE DRAFT.\n",
                 (self._style_tag(False, False, False, DEFAULT_SIZE, DEFAULT_FAMILY),
                  ALIGN_TAGS["center"]))
        t.edit_modified(False)
        self.dirty = False

    def _current_fields(self):
        return {k: self._v(k) for k in ["to", "subject", "date", "name", "post",
                                        "section", "organization"]}

    def _render_preview(self):
        t = self.preview
        t.delete("1.0", "end")
        for text, o in build_paragraphs(self._current_fields(), self.body):
            if o.get("indent"):
                text = "\t" + text
            style = self._style_tag(o.get("bold", False), False, o.get("underline", False),
                                    DEFAULT_SIZE, DEFAULT_FAMILY)
            align = ALIGN_TAGS["right"] if o.get("align") == "right" else ALIGN_TAGS["left"]
            t.insert("end", text + "\n", (style, align))
        t.edit_modified(False)
        self.dirty = False
        t.edit_reset()

    # ---------- RTF export (reads the preview as the user left it)
    def _preview_to_rtf(self):
        t = self.preview
        active = set()
        paragraphs = []          # list of (runs, align_tag)
        runs = []
        for kind, value, _index in t.dump("1.0", "end-1c", text=True, tag=True):
            if kind == "tagon":
                if value.startswith("st|"):
                    active = {a for a in active if not a.startswith("st|")}
                    active.add(value)
                elif value in ALIGN_NAMES:
                    active = {a for a in active if a not in ALIGN_NAMES}
                    active.add(value)
            elif kind == "tagoff":
                active.discard(value)
            elif kind == "text":
                for k, piece in enumerate(value.split("\n")):
                    if k > 0:
                        align = next((a for a in active if a in ALIGN_NAMES), "al_left")
                        paragraphs.append((runs, align))
                        runs = []
                    if piece:
                        style = next((a for a in active if a.startswith("st|")), None)
                        runs.append((piece, style))
        if runs:
            paragraphs.append((runs, "al_left"))

        families = [DEFAULT_FAMILY]
        def font_index(family):
            if family not in families:
                families.append(family)
            return families.index(family)

        body_parts = []
        for runs_, align in paragraphs:
            align_code = RTF_ALIGN.get(align, "\\ql")
            body_parts.append("\\pard" + align_code + "\\li0 ")
            for piece, style in runs_:
                if style:
                    st = self._parse_style(style)
                else:
                    st = {"b": False, "i": False, "u": False,
                          "size": DEFAULT_SIZE, "family": DEFAULT_FAMILY}
                fmt = (r"\b" if st["b"] else "") + (r"\i" if st["i"] else "") + \
                      (r"\ul" if st["u"] else "")
                body_parts.append("{" + rf"\f{font_index(st['family'])}\fs{st['size'] * 2}{fmt} "
                                  + rtf_escape(piece) + "}")
            body_parts.append(r"\par" + "\n")

        fonttbl = "".join(f"{{\\f{i}\\fnil {fam};}}" for i, fam in enumerate(families))
        header = r"{\rtf1\ansi\deff0{\fonttbl" + fonttbl + "}" + "\n"
        return header + "".join(body_parts) + "}"

    # ---------- actions
    def _on_fetch_models(self):
        base = normalise_base_url(self._v("server"))
        if not base:
            messagebox.showwarning(APP_TITLE, "Please enter the Server API URL first.")
            return
        self._set_busy(True, "Fetching models from server...")

        def done(models):
            self._set_busy(False, f"{len(models)} model(s) found.")
            self.model_combo["values"] = models
            if models and not self._v("model"):
                self.vars["model"].set(models[0])

        def err(e):
            self._set_busy(False, "Failed to fetch models.")
            messagebox.showerror(APP_TITLE, str(e))

        self._run_async(lambda: fetch_models(base, self._v("key")), done, err)

    def _on_generate(self):
        f = {k: self._v(k) for k in ["to", "subject", "date", "name", "post",
                                     "section", "organization", "server", "key", "model"]}
        required = [("to", "To"), ("subject", "Subject"), ("name", "Employee Name"),
                    ("organization", "Organization"), ("server", "Server API URL"),
                    ("model", "Model")]
        missing = [label for key, label in required if not f[key]]
        if missing:
            messagebox.showwarning(APP_TITLE, "Please fill in: " + ", ".join(missing))
            return
        if self.dirty and self.body:
            if not messagebox.askyesno(APP_TITLE,
                                       "You have edited the preview. Replace it with a new draft?"):
                return
        if not f["date"]:
            f["date"] = datetime.date.today().strftime("%d %B, %Y")
            self.vars["date"].set(f["date"])

        base = normalise_base_url(f["server"])
        system_prompt = self._t(self.system_text)
        user_prompt = self._t(self.user_text)
        user_msg = (
            f"Subject: {f['subject']}\n"
            f"Addressed to: {f['to']}, {f['organization']}\n"
            f"Sender: {f['name']}, {f['post']}, {f['section']}, {f['organization']}\n\n"
            f"{user_prompt}"
        )
        self.save_config()
        self._set_busy(True, f"Generating with {f['model']}… (timeout {TIMEOUT_SECONDS} s)")

        def done(text):
            self.body = text
            self._render_preview()
            self._set_busy(False, "Draft ready. Edit it with the toolbar, then Save as RTF.")

        def err(e):
            self._set_busy(False, "Generation failed.")
            messagebox.showerror(APP_TITLE, str(e))

        self._run_async(
            lambda: generate_body(base, f["key"], f["model"], system_prompt, user_msg),
            done, err)

    def _on_save(self):
        if not self.preview.get("1.0", "end-1c").strip():
            messagebox.showinfo(APP_TITLE, "Generate a draft first.")
            return
        safe_subject = re.sub(r"[^A-Za-z0-9 _-]", "", self._v("subject"))[:40].strip() or "Document"
        path = filedialog.asksaveasfilename(
            title="Save document",
            defaultextension=".rtf",
            initialfile=f"{safe_subject}.rtf",
            filetypes=[("Rich Text Format", "*.rtf")],
        )
        if not path:
            return
        with open(path, "w", encoding="ascii") as fh:
            fh.write(self._preview_to_rtf())
        self._msg(f"Saved: {path}")

    # ---------- config
    def _load_config(self):
        data = {}
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
            except (OSError, json.JSONDecodeError):
                data = {}
        self.vars["server"].set(data.get("server", "http://localhost:1234/v1"))
        self.vars["key"].set(data.get("key", "lm-studio"))
        self.vars["model"].set(data.get("model", ""))
        for key in ["name", "post", "section", "organization"]:
            self.vars[key].set(data.get(key, ""))
        self.vars["date"].set(datetime.date.today().strftime("%d %B, %Y"))
        if data.get("system_prompt"):
            self.system_text.delete("1.0", "end")
            self.system_text.insert("1.0", data["system_prompt"])

    def save_config(self):
        data = {k: self._v(k) for k in ["server", "key", "model", "name",
                                        "post", "section", "organization"]}
        data["system_prompt"] = self._t(self.system_text)
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
        except OSError:
            pass

    def _on_close(self):
        self.save_config()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    CrafterApp(root)
    root.mainloop()
