import tkinter as tk
from config import cfg
from gui.styles import COLORS, FONTS


class ResizeGrip(tk.Label):
    def __init__(self, parent, resize_callback, stop_callback, bg, fg):
        super().__init__(parent, text="◢", font=("Arial", 10), bg=bg, fg=fg, cursor="sizing")
        self.resize_callback = resize_callback
        self.stop_callback = stop_callback
        self.bind("<Button-1>", self._start_resize)
        self.bind("<B1-Motion>", self._do_resize)
        self.bind("<ButtonRelease-1>", self._stop_resize)
        self._root_x = 0
        self._root_y = 0

    def _start_resize(self, event):
        self._root_x = event.x_root
        self._root_y = event.y_root

    def _do_resize(self, event):
        dx = event.x_root - self._root_x
        dy = event.y_root - self._root_y
        self.resize_callback(dx, dy)
        self._root_x = event.x_root
        self._root_y = event.y_root

    def _stop_resize(self, event):
        self.stop_callback()


class SentenceWindow(tk.Toplevel):
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
            initial_wrap = width - 30
        except:
            pass

        custom_font = ("Segoe UI", 12)

        self.content_frame = tk.Frame(self, bg=COLORS["bg"])
        self.content_frame.pack(fill="both", expand=True)

        self.lbl_eng = tk.Label(self.content_frame, text="", font=custom_font, bg=COLORS["bg"],
                                fg=COLORS["text_main"], justify="left", anchor="w",
                                wraplength=initial_wrap)
        self.lbl_eng.pack(fill="x", padx=15, pady=(10, 5))

        self.lbl_rus = tk.Label(self.content_frame, text="...", font=custom_font, bg=COLORS["bg"],
                                fg=COLORS["text_accent"], justify="left", anchor="w",
                                wraplength=initial_wrap)
        self.lbl_rus.pack(fill="x", padx=15, pady=(5, 10))

        # Grip с callback-ом на сохранение
        self.grip = ResizeGrip(self, self.resize_window, self.save_geometry, COLORS["bg"], COLORS["resize_grip"])
        self.grip.place(relx=1.0, rely=1.0, anchor="se")

        # Перемещение
        self._x = 0
        self._y = 0

        # Привязываем начало перемещения
        for widget in [self, self.lbl_eng, self.lbl_rus, self.content_frame]:
            widget.bind("<Button-1>", self.start_move)
            widget.bind("<B1-Motion>", self.do_move)
            widget.bind("<ButtonRelease-1>", self.stop_move)  # Сохраняем, когда отпустили

        self.bind("<Configure>", self.on_resize)

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
        new_w = self.winfo_width() + dx
        new_h = self.winfo_height() + dy
        if new_w < 200: new_w = 200
        if new_h < 80: new_h = 80
        self.geometry(f"{new_w}x{new_h}")

    def on_resize(self, event):
        if event.widget == self:
            new_wrap = event.width - 30
            if new_wrap < 100: new_wrap = 100
            try:
                if self.lbl_eng.cget("wraplength") != new_wrap:
                    self.lbl_eng.config(wraplength=new_wrap)
                    self.lbl_rus.config(wraplength=new_wrap)
            except:
                pass

    def save_geometry(self, event=None):
        """Сохраняем текущее положение в файл"""
        cfg.set("USER", "SentWindowGeometry", self.geometry())
        cfg.save()

    def show(self):
        self.geometry(cfg.get("USER", "SentWindowGeometry", "600x150+700+100"))
        self.deiconify()

    def hide(self):
        cfg.set("USER", "SentWindowGeometry", self.geometry())
        cfg.set("USER", "ShowSentenceWindow", "False")
        cfg.save()  # <-- Добавлено сохранение
        self.withdraw()
