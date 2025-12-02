"""
Кастомный scrollbar для Tkinter через Canvas.

Обеспечивает полный контроль над внешним видом:
- Узкий минималистичный дизайн (8px желоб, 4px бегунок)
- Hover эффекты
- Автоматическое скрытие когда весь контент виден (опционально)
- Drag & drop перетаскивание бегунка
- Клик по желобу для прыжка к позиции
- Блокировка автообновлений во время загрузки контента
- Изоляция событий (не конфликтует с перемещением окна)
- Режим always_visible для окон где scrollbar должен быть всегда
"""

import tkinter as tk
from gui.styles import COLORS


class CustomScrollbar:
    """
    Кастомный scrollbar реализованный через Canvas.

    Преимущества перед tk.Scrollbar:
    - Полный контроль над цветами и размерами
    - Hover эффекты
    - Современный минималистичный вид
    - Кроссплатформенная консистентность
    - Управление видимостью во время загрузки данных
    - Изоляция событий от родительского окна
    """

    # ===== КОНСТАНТЫ ДИЗАЙНА =====
    CANVAS_WIDTH = 8  # Ширина желоба scrollbar
    THUMB_WIDTH = 4  # Ширина бегунка
    THUMB_PADDING = 2  # Отступы бегунка от краёв (слева/справа)
    MIN_THUMB_HEIGHT = 20  # Минимальная высота бегунка в пикселях

    def __init__(self, parent, canvas_scroll, always_visible=False):
        """
        Args:
            parent: Родительский контейнер для размещения scrollbar
            canvas_scroll: Canvas который нужно скроллить
            always_visible: Если True, scrollbar всегда виден (даже если контент влезает)
        """
        self.canvas_scroll = canvas_scroll
        self.always_visible = always_visible

        # Создание Canvas для scrollbar
        self.scrollbar_canvas = tk.Canvas(
            parent,
            width=self.CANVAS_WIDTH,
            bg=COLORS["bg_secondary"],  # Цвет желоба (тёмный)
            highlightthickness=0,
            bd=0
        )

        # Состояние
        self.thumb = None  # ID прямоугольника бегунка
        self._dragging = False  # Флаг активного перетаскивания
        self._drag_start_y = 0  # Y координата начала drag
        self._update_blocked = False  # Блокировка автообновлений во время загрузки

        # Привязка событий
        self._bind_events()

    def _bind_events(self):
        """Привязывает обработчики событий мыши с изоляцией от родительского окна"""
        self.scrollbar_canvas.bind("<Button-1>", self._on_click)
        self.scrollbar_canvas.bind("<B1-Motion>", self._on_drag)
        self.scrollbar_canvas.bind("<ButtonRelease-1>", self._on_release)
        self.scrollbar_canvas.bind("<Enter>", self._on_enter)
        self.scrollbar_canvas.bind("<Leave>", self._on_leave)

    def pack(self, **kwargs):
        """Proxy для pack() метода Canvas"""
        self.scrollbar_canvas.pack(**kwargs)

    def pack_forget(self):
        """Proxy для pack_forget() метода Canvas"""
        self.scrollbar_canvas.pack_forget()

    def winfo_ismapped(self):
        """Proxy для winfo_ismapped() метода Canvas"""
        return self.scrollbar_canvas.winfo_ismapped()

    def block_updates(self):
        """
        Блокирует автоматические обновления scrollbar.

        Вызывается ПЕРЕД началом загрузки нового слова чтобы:
        1. Немедленно скрыть scrollbar
        2. Предотвратить его появление во время частичной загрузки данных

        Разблокировка происходит автоматически в force_update().
        """
        self._update_blocked = True
        self.hide()

    def hide(self):
        """
        Принудительно скрывает scrollbar.

        Используется при сбросе UI для нового слова,
        чтобы избежать визуальных артефактов.
        """
        # Удаляем бегунок если существует
        if self.thumb:
            self.scrollbar_canvas.delete(self.thumb)
            self.thumb = None

        # Скрываем Canvas
        self.pack_forget()

    def update(self, first, last):
        """
        Обновляет позицию и размер бегунка.

        Вызывается автоматически через yscrollcommand.

        Args:
            first: Начальная позиция видимой области (0.0 - 1.0)
            last: Конечная позиция видимой области (0.0 - 1.0)
        """
        # КРИТИЧНО: Игнорируем автоматические обновления во время загрузки
        # Это предотвращает появление scrollbar до завершения рендеринга
        if self._update_blocked:
            return

        first = float(first)
        last = float(last)

        # Удаляем старый бегунок
        if self.thumb:
            self.scrollbar_canvas.delete(self.thumb)
            self.thumb = None

        # Если весь контент виден - скрываем scrollbar (если не always_visible)
        if first <= 0.0 and last >= 1.0:
            if not self.always_visible:
                self.pack_forget()
                return
            # Если always_visible - продолжаем отрисовку бегунка

        # Показываем scrollbar если скрыт
        if not self.winfo_ismapped():
            self.pack(side="right", fill="y")

        # Рассчитываем размер и позицию бегунка
        canvas_height = self.scrollbar_canvas.winfo_height()
        thumb_height = max(self.MIN_THUMB_HEIGHT, int(canvas_height * (last - first)))
        thumb_y = int(canvas_height * first)

        # Рисуем бегунок (узкий прямоугольник с отступами)
        self.thumb = self.scrollbar_canvas.create_rectangle(
            self.THUMB_PADDING,  # x1
            thumb_y,  # y1
            self.THUMB_PADDING + self.THUMB_WIDTH,  # x2
            thumb_y + thumb_height,  # y2
            fill=COLORS["text_faint"],  # Серый цвет
            outline="",  # Без обводки
            tags="thumb"
        )

    def force_update(self):
        """
        Принудительное обновление scrollbar после отрисовки контента.

        Вызывается через after_idle() чтобы гарантировать что:
        1. Все виджеты отрисованы
        2. Canvas пересчитал scrollregion
        3. Геометрия всех элементов известна

        Автоматически разблокирует обновления и показывает scrollbar если нужно.
        """
        # Разблокируем обновления
        self._update_blocked = False

        # Обновляем scrollregion
        self.canvas_scroll.configure(scrollregion=self.canvas_scroll.bbox("all"))

        # Получаем текущие границы видимой области
        first, last = self.canvas_scroll.yview()

        # КРИТИЧНО: Явно вызываем update() с новыми значениями
        # Без этого scrollbar не появится т.к. update() просто вернётся после разблокировки
        self.update(first, last)

    def _on_click(self, event):
        """
        Обработка клика по scrollbar.

        - Клик по бегунку: начало перетаскивания
        - Клик по желобу: прыжок к позиции

        КРИТИЧНО: return "break" останавливает всплытие события к родительскому окну,
        предотвращая конфликт с drag-перемещением окна.
        """
        # Проверяем клик по бегунку
        item = self.scrollbar_canvas.find_closest(event.x, event.y)
        if item and "thumb" in self.scrollbar_canvas.gettags(item[0]):
            self._dragging = True
            self._drag_start_y = event.y
        else:
            # Клик по желобу - прыжок к позиции
            canvas_height = self.scrollbar_canvas.winfo_height()
            fraction = event.y / canvas_height
            self.canvas_scroll.yview_moveto(fraction)

        # Останавливаем всплытие события
        return "break"

    def _on_drag(self, event):
        """
        Обработка перетаскивания бегунка мышью.

        КРИТИЧНО: return "break" предотвращает перемещение окна при drag scrollbar.
        """
        if not self._dragging:
            return "break"

        # Вычисляем дельту и скроллим
        delta_y = event.y - self._drag_start_y
        canvas_height = self.scrollbar_canvas.winfo_height()

        # Получаем текущую позицию скролла
        current_pos = self.canvas_scroll.yview()[0]

        # Вычисляем новую позицию
        scroll_fraction = delta_y / canvas_height
        new_pos = current_pos + scroll_fraction

        # Применяем скролл
        self.canvas_scroll.yview_moveto(new_pos)
        self._drag_start_y = event.y

        # Останавливаем всплытие события
        return "break"

    def _on_release(self, event):
        """
        Завершение перетаскивания бегунка.

        КРИТИЧНО: return "break" предотвращает обработку события родительским окном.
        """
        self._dragging = False
        return "break"

    def _on_enter(self, event):
        """Hover эффект: бегунок становится чуть светлее"""
        if self.thumb:
            self.scrollbar_canvas.itemconfig(
                self.thumb,
                fill=COLORS["text_main"]  # Светлее при hover
            )

    def _on_leave(self, event):
        """Возврат к обычному цвету при уходе курсора"""
        if self.thumb:
            self.scrollbar_canvas.itemconfig(
                self.thumb,
                fill=COLORS["text_faint"]  # Обратно к серому
            )
