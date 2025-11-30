import tkinter as tk
from config import cfg
from gui.styles import COLORS, FONTS


class ResizeGrip(tk.Label):
    def __init__(self, parent, resize_callback, finish_callback, bg, fg):
        super().__init__(parent, text="◢", font=("Arial", 10), bg=bg, fg=fg, cursor="sizing")
        self.resize_callback = resize_callback
        self.finish_callback = finish_callback

        # ВАЖНО: return "break" останавливает всплытие события к родительскому окну
        self.bind("<Button-1>", self._start_resize)
        self.bind("<B1-Motion>", self._do_resize)
        self.bind("<ButtonRelease-1>", self._stop_resize)

        self._x = 0
        self._y = 0

    def _start_resize(self, event):
        self._x = event.x_root
        self._y = event.y_root
        return "break"  # <--- ОСТАНАВЛИВАЕМ MOVE LOGIC

    def _do_resize(self, event):
        dx = event.x_root - self._x
        dy = event.y_root - self._y
        self.resize_callback(dx, dy)
        self._x = event.x_root
        self._y = event.y_root
        return "break"  # <--- ОСТАНАВЛИВАЕМ MOVE LOGIC

    def _stop_resize(self, event):
        self.finish_callback()
        return "break"  # <--- ОСТАНАВЛИВАЕМ MOVE LOGIC


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

        # --- ГЕОМЕТРИЯ ---
        geo_str = cfg.get("USER", "SentWindowGeometry", "600x150+700+100")
        self.geometry(geo_str)

        initial_wrap = 570
        try:
            w_str = geo_str.split('x')[0]
            width = int(w_str)
            initial_wrap = width - self.TEXT_PADDING
        except:
            pass

        # Используем шрифт как в главном окне для перевода слова
        translation_font = ("Segoe UI", 33)

        self.content_frame = tk.Frame(self, bg=COLORS["bg"])
        self.content_frame.pack(fill="both", expand=True)

        self.lbl_eng = tk.Label(self.content_frame, text="", font=("Segoe UI", 12), bg=COLORS["bg"],
                                fg=COLORS["text_main"], justify="left", anchor="w",
                                wraplength=initial_wrap)
        self.lbl_eng.pack(fill="x", padx=15, pady=(10, 5))

        self.lbl_rus = tk.Label(self.content_frame, text="...", font=translation_font, bg=COLORS["bg"],
                                fg=COLORS["text_accent"], justify="left", anchor="w",
                                wraplength=initial_wrap)
        self.lbl_rus.pack(fill="x", padx=15, pady=(5, 10))

        # Grip с callback-ом
        self.grip = ResizeGrip(self, self.resize_window, self.save_geometry, COLORS["bg"], COLORS["resize_grip"])
        self.grip.place(relx=1.0, rely=1.0, anchor="se")

        # Перемещение
        self._x = 0
        self._y = 0

        # Привязываем начало перемещения к окну и лейблам
        for widget in [self, self.lbl_eng, self.lbl_rus, self.content_frame]:
            widget.bind("<Button-1>", self.start_move)
            widget.bind("<B1-Motion>", self.do_move)
            widget.bind("<ButtonRelease-1>", self.stop_move)

        # НОВОЕ: Применяем начальное состояние видимости из настроек
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
        # 1. Явно берем текущие координаты, чтобы зафиксировать окно на месте
        current_x = self.winfo_x()
        current_y = self.winfo_y()

        # 2. Считаем новый размер
        new_w = max(self.MIN_WINDOW_WIDTH, self.winfo_width() + dx)
        new_h = max(self.MIN_WINDOW_HEIGHT, self.winfo_height() + dy)

        # 3. Применяем размер И позицию одновременно.
        # Это гарантирует, что левый верхний угол гвоздями прибит к current_x, current_y
        self.geometry(f"{new_w}x{new_h}+{current_x}+{current_y}")

        # 4. Обновляем перенос текста
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
