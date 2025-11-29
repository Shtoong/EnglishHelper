import tkinter as tk
from gui.styles import COLORS, FONTS
from config import cfg


class ResizeGrip(tk.Label):
    def __init__(self, parent, resize_callback, finish_callback, bg, fg):
        super().__init__(parent, text="◢", font=("Arial", 10), bg=bg, fg=fg, cursor="sizing")
        self.parent = parent
        self.resize_callback = resize_callback
        self.finish_callback = finish_callback
        self.bind("<Button-1>", self._start_resize)
        self.bind("<B1-Motion>", self._do_resize)
        self.bind("<ButtonRelease-1>", self._stop_resize)
        self._x = 0
        self._y = 0

    def _start_resize(self, event):
        self._x = event.x
        self._y = event.y

    def _do_resize(self, event):
        dx = event.x - self._x
        dy = event.y - self._y
        self.resize_callback(dx, dy)

    def _stop_resize(self, event):
        self.finish_callback()


class SentenceWindow(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.COLORS = COLORS

        self.overrideredirect(True)
        self.wm_attributes("-topmost", True)
        self.configure(bg=self.COLORS["bg_secondary"])

        w = cfg.get("USER", "SentWindowWidth", "600")
        h = cfg.get("USER", "SentWindowHeight", "120")
        x = cfg.get("USER", "SentWindowX", "100")
        y = cfg.get("USER", "SentWindowY", "600")
        self.geometry(f"{w}x{h}+{x}+{y}")

        # --- UI ---
        self.top_bar = tk.Frame(self, bg=self.COLORS["bg_secondary"], height=15, cursor="fleur")
        self.top_bar.pack(fill="x", side="top")

        self.btn_close = tk.Label(self.top_bar, text="✕", font=("Arial", 10), bg=self.COLORS["bg_secondary"],
                                  fg=self.COLORS["text_faint"], cursor="hand2")
        self.btn_close.pack(side="right", padx=5)
        self.btn_close.bind("<Button-1>", self.hide_window)

        self.content_frame = tk.Frame(self, bg=self.COLORS["bg_secondary"])
        self.content_frame.pack(fill="both", expand=True, padx=15, pady=0)

        self.lbl_eng = tk.Label(
            self.content_frame,
            text="",
            font=("Consolas", 12),
            bg=self.COLORS["bg_secondary"],
            fg=self.COLORS["text_main"],
            wraplength=580,
            justify="left",
            anchor="w"
        )
        self.lbl_eng.pack(pady=(5, 5), fill="x")

        self.lbl_rus = tk.Label(
            self.content_frame,
            text="...",
            font=("Segoe UI", 22),
            bg=self.COLORS["bg_secondary"],
            fg=self.COLORS["text_accent"],
            wraplength=580,
            justify="left",
            anchor="w"
        )
        self.lbl_rus.pack(pady=(0, 5), fill="x")

        self.bottom_bar = tk.Frame(self, bg=self.COLORS["bg_secondary"], height=15)
        self.bottom_bar.pack(side="bottom", fill="x")

        self.grip = ResizeGrip(self.bottom_bar, self.resize_window, self.save_size, self.COLORS["bg_secondary"],
                               self.COLORS["text_faint"])
        self.grip.pack(side="right", anchor="se")

        # --- DRAG & DROP LOGIC ---
        self.dragging = False
        self.drag_x = 0
        self.drag_y = 0

        # Привязываем перетаскивание КО ВСЕМУ (кроме кнопки и грипа)
        for widget in [self, self.top_bar, self.content_frame, self.lbl_eng, self.lbl_rus, self.bottom_bar]:
            widget.bind("<Button-1>", self.start_move)
            widget.bind("<B1-Motion>", self.do_move)
            widget.bind("<ButtonRelease-1>", self.stop_move)

        if not cfg.get_bool("USER", "ShowSentenceWindow"):
            self.withdraw()

    def start_move(self, event):
        self.dragging = True
        self.drag_x = event.x
        self.drag_y = event.y

    def do_move(self, event):
        if self.dragging:
            # Рассчитываем смещение относительно экрана, а не виджета
            x = self.winfo_x() + (event.x - self.drag_x)
            y = self.winfo_y() + (event.y - self.drag_y)
            self.geometry(f"+{x}+{y}")

    def stop_move(self, event):
        self.dragging = False
        cfg.set("USER", "SentWindowX", self.winfo_x())
        cfg.set("USER", "SentWindowY", self.winfo_y())

    def resize_window(self, dx, dy):
        new_w = self.winfo_width() + dx
        new_h = self.winfo_height() + dy
        if new_w < 200: new_w = 200
        if new_h < 50: new_h = 50
        self.geometry(f"{new_w}x{new_h}")
        self.lbl_eng.config(wraplength=new_w - 20)
        self.lbl_rus.config(wraplength=new_w - 20)

    def save_size(self):
        cfg.set("USER", "SentWindowWidth", self.winfo_width())
        cfg.set("USER", "SentWindowHeight", self.winfo_height())

    def hide_window(self, event=None):
        self.withdraw()
        cfg.set("USER", "ShowSentenceWindow", False)

    def show(self):
        self.deiconify()
        cfg.set("USER", "ShowSentenceWindow", True)

    def hide(self):
        self.withdraw()
