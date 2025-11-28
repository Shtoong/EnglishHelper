import tkinter as tk
from config import cfg
from gui.styles import COLORS, FONTS


class ResizeGrip(tk.Label):
    """Виджет-треугольник для изменения размера окна"""

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
    def __init__(self, master):
        super().__init__(master)
        self.overrideredirect(True)
        self.wm_attributes("-topmost", True)
        self.configure(bg=COLORS["bg"])

        # Загружаем сохраненные координаты и размеры или дефолтные
        x = cfg.get("USER", "SentWindowX", "500")
        y = cfg.get("USER", "SentWindowY", "500")
        w = cfg.get("USER", "SentWindowWidth", "600")
        h = cfg.get("USER", "SentWindowHeight", "200")  # Чуть увеличил дефолтную высоту

        self.geometry(f"{w}x{h}+{x}+{y}")

        self.dragging_allowed = False
        self.COLORS = COLORS
        self.FONTS = FONTS

        self._init_ui()
        self._bind_events()

        # Скрываем, если так настроено
        if not cfg.get_bool("USER", "ShowSentenceWindow"):
            self.withdraw()

    def _init_ui(self):
        # Основной контейнер для контента
        self.content_frame = tk.Frame(self, bg=self.COLORS["bg"])
        self.content_frame.pack(fill="both", expand=True, padx=10, pady=5)

        self.lbl_eng = tk.Label(self.content_frame, text="", font=("Consolas", 12),
                                bg=self.COLORS["bg"], fg=self.COLORS["text_main"],
                                wraplength=580, justify="left")
        self.lbl_eng.pack(anchor="w", pady=(5, 5), fill="x")

        tk.Frame(self.content_frame, height=1, bg=self.COLORS["separator"]).pack(fill="x", pady=5)

        # УВЕЛИЧЕННЫЙ ШРИФТ ЗДЕСЬ (было 11, стало 33)
        self.lbl_rus = tk.Label(self.content_frame, text="...", font=("Segoe UI", 33),
                                bg=self.COLORS["bg"], fg=self.COLORS["text_accent"],
                                wraplength=580, justify="left")
        self.lbl_rus.pack(anchor="w", pady=(5, 0), fill="x")

        # Нижняя панель для Grip (чтобы он был в углу)
        self.bottom_frame = tk.Frame(self, bg=self.COLORS["bg"], height=15)
        self.bottom_frame.pack(side="bottom", fill="x")

        self.grip = ResizeGrip(self.bottom_frame, self.resize_window, self.save_size,
                               self.COLORS["bg"], self.COLORS["resize_grip"])
        self.grip.pack(side="right", anchor="se", padx=0, pady=0)

    def _bind_events(self):
        self.bind("<Button-1>", self.start_move)
        self.bind("<B1-Motion>", self.do_move)
        self.bind("<ButtonRelease-1>", self.stop_move)

    # --- RESIZE LOGIC ---
    def resize_window(self, dx, dy):
        new_w = self.winfo_width() + dx
        new_h = self.winfo_height() + dy

        # Минимальные размеры
        if new_w < 300: new_w = 300
        if new_h < 100: new_h = 100

        self.geometry(f"{new_w}x{new_h}")

        # Обновляем ширину перевода текста (wraplength), чтобы текст переносился
        text_width = new_w - 20
        self.lbl_eng.config(wraplength=text_width)
        self.lbl_rus.config(wraplength=text_width)

    def save_size(self):
        cfg.set("USER", "SentWindowWidth", self.winfo_width())
        cfg.set("USER", "SentWindowHeight", self.winfo_height())

    # --- MOVE LOGIC ---
    def start_move(self, event):
        # Если кликнули по грипу - не таскаем окно
        if event.widget == self.grip:
            self.dragging_allowed = False
            return

        self.dragging_allowed = True
        self.x = event.x
        self.y = event.y

    def do_move(self, event):
        if not self.dragging_allowed: return
        x = self.winfo_x() + (event.x - self.x)
        y = self.winfo_y() + (event.y - self.y)
        self.geometry(f"+{x}+{y}")

    def stop_move(self, event):
        if self.dragging_allowed:
            cfg.set("USER", "SentWindowX", self.winfo_x())
            cfg.set("USER", "SentWindowY", self.winfo_y())
        self.dragging_allowed = False

    # --- VISIBILITY ---
    def show(self):
        self.deiconify()

    def hide(self):
        self.withdraw()
