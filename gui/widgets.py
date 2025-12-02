"""
Переиспользуемые UI виджеты для EnglishHelper.

Содержит компоненты, которые используются в нескольких окнах приложения.
"""

import tkinter as tk


class ResizeGrip(tk.Label):
    """
    Виджет для изменения размера окна (resize handle).

    Отображается как символ "◢" в правом нижнем углу окна.
    При перетаскивании изменяет размер родительского окна.

    Args:
        parent: Родительское окно
        resize_callback: Функция вызываемая при изменении размера (dx, dy)
        finish_callback: Функция вызываемая при завершении изменения размера
        bg: Цвет фона
        fg: Цвет текста (символа ◢)
    """

    def __init__(self, parent, resize_callback, finish_callback, bg, fg):
        super().__init__(
            parent,
            text="◢",
            font=("Arial", 10),
            bg=bg,
            fg=fg,
            cursor="sizing"
        )
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
