import tkinter as tk
from config import cfg
from gui.styles import COLORS, FONTS
from gui.widgets import ResizeGrip


class SentenceWindow(tk.Toplevel):
    # Константы
    MIN_WINDOW_WIDTH = 200
    MIN_WINDOW_HEIGHT = 80
    TEXT_PADDING = 30
    MIN_WRAPLENGTH = 100

    def __init__(self, master):
        super().__init__(master)
        self.overrideredirect(True)
        self.wm_attributes("-topmost", True)
        self.configure(bg=COLORS["bg"])

        # Геометрия
        geo_str = cfg.get("USER", "SentWindowGeometry", "600x150+700+100")
        self.geometry(geo_str)

        initial_wrap = 570
        try:
            w_str = geo_str.split('x')[0]
            width = int(w_str)
            initial_wrap = width - self.TEXT_PADDING
        except:
            pass

        self.content_frame = tk.Frame(self, bg=COLORS["bg"])
        self.content_frame.pack(fill="both", expand=True)

        self.lbl_eng = tk.Label(
            self.content_frame,
            text="",
            font=FONTS["sentence_text"],
            bg=COLORS["bg"],
            fg=COLORS["text_main"],
            justify="left",
            anchor="w",
            wraplength=initial_wrap
        )
        self.lbl_eng.pack(fill="x", padx=15, pady=(10, 5))

        self.lbl_rus = tk.Label(
            self.content_frame,
            text="...",
            font=FONTS["translation"],
            bg=COLORS["bg"],
            fg=COLORS["text_accent"],
            justify="left",
            anchor="w",
            wraplength=initial_wrap
        )
        self.lbl_rus.pack(fill="x", padx=15, pady=(5, 10))

        # Grip с callback-ом
        self.grip = ResizeGrip(
            self,
            self.resize_window,
            self.save_geometry,
            COLORS["bg"],
            COLORS["resize_grip"]
        )
        self.grip.place(relx=1.0, rely=1.0, anchor="se")

        # Перемещение
        self._x = 0
        self._y = 0

        # Привязываем начало перемещения к окну и лейблам
        for widget in [self, self.lbl_eng, self.lbl_rus, self.content_frame]:
            widget.bind("<Button-1>", self.start_move)
            widget.bind("<B1-Motion>", self.do_move)
            widget.bind("<ButtonRelease-1>", self.stop_move)

        # Применяем начальное состояние видимости из настроек
        if not cfg.get_bool("USER", "ShowSentenceWindow", True):
            self.withdraw()

    def start_move(self, event):
        self._x = event.x
        self._y = event.y

    def do_move(self, event):
        x = self.winfo_x() + (event.x - self._x)
        y = self.winfo_y() + (event.y - self._y)
        self.geometry(f"+{x}+{y}")

    def stop_move(self, event):
        self.save_geometry()

    def resize_window(self, dx, dy):
        """Изменение размера окна"""
        current_x = self.winfo_x()
        current_y = self.winfo_y()

        new_w = max(self.MIN_WINDOW_WIDTH, self.winfo_width() + dx)
        new_h = max(self.MIN_WINDOW_HEIGHT, self.winfo_height() + dy)

        self.geometry(f"{new_w}x{new_h}+{current_x}+{current_y}")

        self.after_idle(lambda: self._update_wraplength(new_w))

    def _update_wraplength(self, width):
        new_wrap = max(self.MIN_WRAPLENGTH, width - self.TEXT_PADDING)
        if self.lbl_eng.cget("wraplength") != new_wrap:
            self.lbl_eng.config(wraplength=new_wrap)
            self.lbl_rus.config(wraplength=new_wrap)

    def save_geometry(self, event=None):
        """Сохраняем текущее положение в файл"""
        cfg.set("USER", "SentWindowGeometry", self.geometry())

    def show(self):
        self.geometry(cfg.get("USER", "SentWindowGeometry", "600x150+700+100"))
        self.deiconify()

    def hide(self):
        cfg.set("USER", "SentWindowGeometry", self.geometry())
        cfg.set("USER", "ShowSentenceWindow", "False")
        self.withdraw()
