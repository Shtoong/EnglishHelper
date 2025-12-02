"""
Переиспользуемые UI компоненты для EnglishHelper.

Содержит:
- ResizeGrip: Виджет изменения размера окна
- TranslationTooltip: Всплывающая подсказка с переводом и анимацией загрузки
"""

import tkinter as tk
from gui.styles import COLORS, FONTS
from network import fetch_sentence_translation
import threading


class ResizeGrip(tk.Label):
    """
    Виджет для изменения размера окна.

    Отображает символ ◢ в правом нижнем углу окна.
    Поддерживает drag для resize с сохранением через callback.
    """

    def __init__(self, parent, resize_callback, finish_callback, bg, fg):
        """
        Args:
            parent: Родительский виджет
            resize_callback: Функция(dx, dy) вызываемая при перетаскивании
            finish_callback: Функция() вызываемая при завершении resize
            bg: Цвет фона
            fg: Цвет текста (символа ◢)
        """
        super().__init__(parent, text="◢", font=("Arial", 10), bg=bg, fg=fg, cursor="sizing")
        self.resize_callback = resize_callback
        self.finish_callback = finish_callback
        self.bind("<Button-1>", self._start_resize)
        self.bind("<B1-Motion>", self._do_resize)
        self.bind("<ButtonRelease-1>", self._stop_resize)
        self._x = 0
        self._y = 0

    def _start_resize(self, event):
        """Запоминаем начальную позицию в экранных координатах"""
        self._x = event.x_root
        self._y = event.y_root
        return "break"

    def _do_resize(self, event):
        """Изменяем размер на основе дельты в экранных координатах"""
        dx = event.x_root - self._x
        dy = event.y_root - self._y
        self.resize_callback(dx, dy)
        self._x = event.x_root
        self._y = event.y_root
        return "break"

    def _stop_resize(self, event):
        """Завершаем изменение размера и сохраняем"""
        self.finish_callback()
        return "break"


class TranslationTooltip:
    """
    Всплывающая подсказка с переводом.

    Features:
    - Анимированный спиннер во время загрузки
    - Автоматическая загрузка перевода в worker-потоке
    - Позиционирование относительно курсора
    """

    def __init__(self, parent):
        """
        Args:
            parent: Родительское окно (для app.after() вызовов)
        """
        self.parent = parent
        self.tip_window = None
        self.label = None
        self.animation_id = None
        self.spinner_chars = ["|", "/", "-", "\\"]

    def _create_window(self, x, y):
        """Создаёт всплывающее окно с рамкой"""
        if self.tip_window:
            return

        x += 15
        y += 15

        self.tip_window = tk.Toplevel(self.parent)
        self.tip_window.wm_overrideredirect(True)
        self.tip_window.wm_geometry(f"+{x}+{y}")
        self.tip_window.wm_attributes("-topmost", True)

        frame = tk.Frame(
            self.tip_window,
            bg=COLORS["bg_secondary"],
            highlightbackground=COLORS["text_accent"],
            highlightthickness=1
        )
        frame.pack()

        self.label = tk.Label(
            frame,
            text="",
            justify='left',
            bg=COLORS["bg_secondary"],
            fg=COLORS["text_main"],
            font=FONTS["tooltip"],
            wraplength=300,
            padx=8,
            pady=4
        )
        self.label.pack()

    def show_loading(self, x, y):
        """Показывает окно с анимированным спиннером"""
        self.hide()
        self._create_window(x, y)
        self._animate(0)

    def show_text(self, text, x, y):
        """Показывает окно с готовым текстом"""
        self.hide()
        self._create_window(x, y)
        self.label.config(text=text)

    def update_text(self, text):
        """Обновляет текст в существующем окне (останавливает анимацию)"""
        if self.tip_window and self.label:
            self._stop_animation()
            self.label.config(text=text)

    def _animate(self, step):
        """Анимация спиннера загрузки"""
        if not self.tip_window:
            return
        char = self.spinner_chars[step % len(self.spinner_chars)]
        self.label.config(text=f"{char} Translating...")
        self.animation_id = self.parent.after(100, lambda: self._animate(step + 1))

    def _stop_animation(self):
        """Останавливает анимацию"""
        if self.animation_id:
            self.parent.after_cancel(self.animation_id)
            self.animation_id = None

    def hide(self):
        """Скрывает и уничтожает окно"""
        self._stop_animation()
        if self.tip_window:
            self.tip_window.destroy()
            self.tip_window = None
            self.label = None
