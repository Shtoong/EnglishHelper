import tkinter as tk
from config import cfg
from gui.styles import COLORS, FONTS
from gui.components import ResizeGrip


class SentenceWindow(tk.Toplevel):
    """
    Окно для отображения предложений с переводом.

    Features:
    - Синхронизация английского текста с курсором
    - Отложенный перевод (debounce 100ms)
    - Resize через ResizeGrip
    - Сохранение геометрии в config
    - Анимация fade-in/fade-out при показе/скрытии
    - Кнопка закрытия с синхронизацией состояния
    """

    # ===== КОНСТАНТЫ =====
    MIN_WINDOW_WIDTH = 200
    MIN_WINDOW_HEIGHT = 80
    TEXT_PADDING = 30
    MIN_WRAPLENGTH = 100

    # Параметры анимации
    ANIMATION_STEPS = 10  # Количество шагов анимации
    ANIMATION_STEP_MS = 15  # Миллисекунд на шаг (итого ~150ms)
    FADE_IN_START = 0.0  # Начальная прозрачность при появлении
    FADE_OUT_END = 0.0  # Конечная прозрачность при скрытии

    def __init__(self, master):
        super().__init__(master)
        self.main_window = master

        self.overrideredirect(True)
        self.wm_attributes("-topmost", True)
        self.configure(bg=COLORS["bg"])

        # Геометрия из config
        geo_str = cfg.get("USER", "SentWindowGeometry", "600x150+700+100")
        self.geometry(geo_str)

        # Вычисляем начальный wraplength
        initial_wrap = 570
        try:
            w_str = geo_str.split('x')[0]
            width = int(w_str)
            initial_wrap = width - self.TEXT_PADDING
        except:
            pass

        # ===== ВЕРХНЯЯ ПАНЕЛЬ С КРЕСТИКОМ =====
        self._create_top_bar()

        # Контейнер контента
        self.content_frame = tk.Frame(self, bg=COLORS["bg"])
        self.content_frame.pack(fill="both", expand=True)

        # Английский текст с курсором
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

        # Русский перевод
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

        # Resize grip
        self.grip = ResizeGrip(
            self,
            self.resize_window,
            self.save_geometry,
            COLORS["bg"],
            COLORS["resize_grip"]
        )
        self.grip.place(relx=1.0, rely=1.0, anchor="se")

        # Состояние для перемещения
        self._x = 0
        self._y = 0

        # Состояние анимации
        self._animation_id = None
        self._is_animating = False

        # Привязываем drag для перемещения окна
        for widget in [self, self.content_frame, self.lbl_eng, self.lbl_rus]:
            widget.bind("<Button-1>", self.start_move)
            widget.bind("<B1-Motion>", self.do_move)
            widget.bind("<ButtonRelease-1>", self.stop_move)

        # Перехватываем стандартное закрытие окна (Alt+F4, системная кнопка если есть)
        self.protocol("WM_DELETE_WINDOW", self.close_window)

        # Применяем начальное состояние видимости
        if not cfg.get_bool("USER", "ShowSentenceWindow", True):
            self.withdraw()

    def _create_top_bar(self):
        """Создает верхнюю панель с кнопкой закрытия"""
        top_bar = tk.Frame(self, bg=COLORS["bg"], height=25)
        top_bar.pack(fill="x", pady=(3, 0))

        # Кнопка закрытия (крестик)
        btn_close = tk.Label(
            top_bar,
            text="✕",
            font=FONTS.get("close_btn", ("Segoe UI", 11, "bold")),
            bg=COLORS["bg"],
            fg=COLORS["close_btn"],
            cursor="hand2"
        )
        btn_close.pack(side="right", padx=8)
        btn_close.bind("<Button-1>", lambda e: self.close_window())

        # Привязываем drag и для top_bar
        top_bar.bind("<Button-1>", self.start_move)
        top_bar.bind("<B1-Motion>", self.do_move)
        top_bar.bind("<ButtonRelease-1>", self.stop_move)

    def start_move(self, event):
        """Начало перемещения окна"""
        self._x = event.x
        self._y = event.y

    def do_move(self, event):
        """Перемещение окна"""
        x = self.winfo_x() + (event.x - self._x)
        y = self.winfo_y() + (event.y - self._y)
        self.geometry(f"+{x}+{y}")

    def stop_move(self, event):
        """Завершение перемещения с сохранением"""
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
        """Обновляет wraplength для текстовых лейблов"""
        new_wrap = max(self.MIN_WRAPLENGTH, width - self.TEXT_PADDING)
        if self.lbl_eng.cget("wraplength") != new_wrap:
            self.lbl_eng.config(wraplength=new_wrap)
            self.lbl_rus.config(wraplength=new_wrap)

    def save_geometry(self, event=None):
        """Сохраняет текущую геометрию в config"""
        cfg.set("USER", "SentWindowGeometry", self.geometry())

    def close_window(self):
        """
        Закрывает окно с анимацией fade-out и синхронизацией состояния.

        КРИТИЧНО: Использует withdraw() вместо destroy() для сохранения
        возможности повторного открытия через toggle кнопку.
        """
        # Если уже идет анимация - игнорируем повторный вызов
        if self._is_animating:
            return

        # Запускаем анимацию fade-out
        self._start_fade_out()

    def _start_fade_out(self):
        """Запускает анимацию постепенного исчезновения окна"""
        self._is_animating = True
        self._animate_alpha(1.0, self.FADE_OUT_END, self._on_fade_out_complete)

    def _on_fade_out_complete(self):
        """Callback после завершения анимации исчезновения"""
        self._is_animating = False

        # Скрываем окно
        self.withdraw()

        # Восстанавливаем полную прозрачность для следующего показа
        self.attributes("-alpha", 1.0)

        # Обновляем конфиг
        cfg.set("USER", "ShowSentenceWindow", False)

        # Синхронизируем toggle кнопку на главном окне
        self.main_window.btn_toggle_sent.sync_state()

    def show_animated(self):
        """
        Показывает окно с анимацией fade-in.

        Вызывается из MainWindow при включении через toggle кнопку.
        """
        # Если уже идет анимация - игнорируем
        if self._is_animating:
            return

        # Восстанавливаем геометрию
        self.geometry(cfg.get("USER", "SentWindowGeometry", "600x150+700+100"))

        # Устанавливаем начальную прозрачность
        self.attributes("-alpha", self.FADE_IN_START)

        # Показываем окно (невидимое)
        self.deiconify()

        # Запускаем анимацию появления
        self._is_animating = True
        self._animate_alpha(self.FADE_IN_START, 1.0, self._on_fade_in_complete)

    def _on_fade_in_complete(self):
        """Callback после завершения анимации появления"""
        self._is_animating = False

    def _animate_alpha(self, start_alpha, end_alpha, on_complete):
        """
        Универсальная функция анимации прозрачности окна.

        Args:
            start_alpha: Начальное значение alpha (0.0 - 1.0)
            end_alpha: Конечное значение alpha (0.0 - 1.0)
            on_complete: Callback функция после завершения
        """
        # Отменяем предыдущую анимацию если есть
        if self._animation_id:
            self.after_cancel(self._animation_id)

        delta = (end_alpha - start_alpha) / self.ANIMATION_STEPS
        current_step = [0]  # Используем list для mutable замыкания

        def step():
            current_step[0] += 1
            new_alpha = start_alpha + (delta * current_step[0])

            # Ограничиваем значение в пределах [0.0, 1.0]
            new_alpha = max(0.0, min(1.0, new_alpha))

            try:
                self.attributes("-alpha", new_alpha)
            except tk.TclError:
                # Окно было уничтожено во время анимации
                return

            if current_step[0] < self.ANIMATION_STEPS:
                # Продолжаем анимацию
                self._animation_id = self.after(self.ANIMATION_STEP_MS, step)
            else:
                # Анимация завершена
                self._animation_id = None
                if on_complete:
                    on_complete()

        # Запускаем первый шаг
        step()

    def show(self):
        """
        Показывает окно БЕЗ анимации (для обратной совместимости).

        Используется при инициализации приложения (_sync_initial_state).
        Для показа с анимацией используйте show_animated().
        """
        self.geometry(cfg.get("USER", "SentWindowGeometry", "600x150+700+100"))
        self.attributes("-alpha", 1.0)
        self.deiconify()

    def hide(self):
        """
        Скрывает окно БЕЗ анимации (для обратной совместимости).

        Для скрытия с анимацией используйте close_window().
        """
        cfg.set("USER", "SentWindowGeometry", self.geometry())
        cfg.set("USER", "ShowSentenceWindow", False)
        self.attributes("-alpha", 1.0)
        self.withdraw()
