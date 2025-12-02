"""
Popup окно для отображения vocab словаря.

Показывает:
- 100 слов до cutoff (ignored, бледные)
- Разделительная черта
- 100 слов после cutoff (active, яркие)

Features:
- Debounced обновление при движении слайдера
- Auto-scroll к разделителю при обновлении
- Кликабельные слова для поиска
- Синхронизация высоты с главным окном
"""

import tkinter as tk
from typing import Optional, Callable
from gui.styles import COLORS, FONTS
from gui.scrollbar import CustomScrollbar
from vocab import get_word_range


class VocabPopup(tk.Toplevel):
    """
    Popup окно для vocab словаря.

    Responsibilities:
    - Отображение диапазона слов вокруг cutoff
    - Debounced обновление списка при движении слайдера
    - Кликабельные слова для поиска в главном окне
    - Автоматическая прокрутка к разделителю
    """

    # ===== КОНСТАНТЫ =====
    WINDOW_WIDTH = 300
    WORDS_BEFORE_CUTOFF = 100
    WORDS_AFTER_CUTOFF = 100
    DEBOUNCE_DELAY_MS = 300  # Задержка перед обновлением списка
    BORDER_COLOR = "#FFD700"  # Желтая рамка

    def __init__(self, master):
        super().__init__(master)
        self.main_window = master

        # Настройка окна
        self.overrideredirect(True)
        self.wm_attributes("-topmost", True)
        self.configure(
            bg=COLORS["bg"],
            highlightthickness=2,
            highlightbackground=self.BORDER_COLOR,
            highlightcolor=self.BORDER_COLOR
        )

        # Состояние
        self._update_timer: Optional[int] = None
        self._current_cutoff = -1
        self.search_callback: Optional[Callable[[str], None]] = None

        # ===== ВЕРХНЯЯ ПАНЕЛЬ =====
        self._create_top_bar()

        # ===== SCROLLABLE CONTENT =====
        self._create_scrollable_content()

        # Скрываем окно до первого вызова
        self.withdraw()

    def _create_top_bar(self):
        """Создает верхнюю панель с заголовком и крестиком"""
        top_bar = tk.Frame(self, bg=COLORS["bg"], height=30)
        top_bar.pack(fill="x", pady=(5, 0))

        # Заголовок
        lbl_title = tk.Label(
            top_bar,
            text="Words",
            font=FONTS["ui"],
            bg=COLORS["bg"],
            fg=COLORS["text_main"]
        )
        lbl_title.pack(side="left", padx=10)

        # Кнопка закрытия
        btn_close = tk.Label(
            top_bar,
            text="✕",
            font=FONTS.get("close_btn", ("Segoe UI", 11, "bold")),
            bg=COLORS["bg"],
            fg=COLORS["close_btn"],
            cursor="hand2"
        )
        btn_close.pack(side="right", padx=10)
        btn_close.bind("<Button-1>", lambda e: self.close())

    def _create_scrollable_content(self):
        """Создает прокручиваемую область со списком слов"""
        scroll_container = tk.Frame(self, bg=COLORS["bg"])
        scroll_container.pack(fill="both", expand=True, padx=10, pady=5)

        # Canvas для прокрутки
        self.canvas = tk.Canvas(
            scroll_container,
            bg=COLORS["bg"],
            highlightthickness=0
        )

        # Кастомный scrollbar с always_visible=True
        # ИЗМЕНЕНО: Добавлен параметр always_visible=True для постоянной видимости
        self.scrollbar = CustomScrollbar(scroll_container, self.canvas, always_visible=True)
        self.scrollbar.pack(side="right", fill="y")

        # Frame для списка слов
        self.scrollable_frame = tk.Frame(self.canvas, bg=COLORS["bg"])

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )

        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.update)
        self.canvas.pack(side="left", fill="both", expand=True)

        # КРИТИЧНО: Используем локальные bindings вместо bind_all
        # чтобы не конфликтовать с главным окном
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.scrollable_frame.bind("<MouseWheel>", self._on_mousewheel)
        self.bind("<MouseWheel>", self._on_mousewheel)

    def _on_mousewheel(self, event):
        """Прокрутка колёсиком мыши (локальная для popup)"""
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        return "break"  # КРИТИЧНО: Останавливаем всплытие события

    def update_words(self, vocab_level: int):
        """
        Обновляет список слов с debounce.

        Args:
            vocab_level: Уровень из слайдера (0-100)
        """
        # Вычисляем cutoff из vocab_level
        cutoff = int(vocab_level * 20000 / 100)

        # Предотвращаем дублирующие обновления
        if self._current_cutoff == cutoff:
            return

        # Отменяем предыдущий таймер
        if self._update_timer is not None:
            self.after_cancel(self._update_timer)

        # Создаём новый таймер
        self._update_timer = self.after(
            self.DEBOUNCE_DELAY_MS,
            lambda: self._execute_update(cutoff)
        )

    def _execute_update(self, cutoff: int):
        """
        Фактическое обновление списка слов.

        Args:
            cutoff: Граница между ignored и active (rank)
        """
        self._current_cutoff = cutoff
        self._update_timer = None

        # Получаем слова из vocab
        # Вариант A: 100 слов ДО cutoff (ignored) | separator | 100 слов ПОСЛЕ cutoff (active)
        ignored, active = get_word_range(
            cutoff,
            self.WORDS_BEFORE_CUTOFF,
            self.WORDS_AFTER_CUTOFF
        )

        # Рендерим список
        self._render_word_list(ignored, active)

        # Прокручиваем к разделителю и обновляем scrollbar
        self.after_idle(self._scroll_to_separator)
        self.after_idle(lambda: self.after(50, self._force_scrollbar_update))

    def _force_scrollbar_update(self):
        """Принудительное обновление scrollbar с проверкой готовности"""
        # Убеждаемся что геометрия полностью готова
        self.canvas.update_idletasks()
        self.scrollbar.force_update()

    def _render_word_list(self, ignored: list[tuple[str, int]], active: list[tuple[str, int]]):
        """
        Рендерит список слов с разделителем.

        Args:
            ignored: Список (word, rank) для ignored слов (бледные)
            active: Список (word, rank) для active слов (яркие)
        """
        # Очищаем предыдущий список
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()

        # Рендерим ignored слова (бледные)
        for word, rank in ignored:
            self._create_word_label(word, rank, "#666666")

        # Рендерим разделитель (только если есть оба списка)
        if ignored and active:
            self.separator = tk.Frame(
                self.scrollable_frame,
                height=2,
                bg=COLORS["separator"]
            )
            self.separator.pack(fill="x", pady=5, padx=10)
        elif ignored:
            # Cutoff в конце - разделитель внизу
            self.separator = tk.Frame(
                self.scrollable_frame,
                height=2,
                bg=COLORS["separator"]
            )
            self.separator.pack(fill="x", pady=5, padx=10)
        elif active:
            # Cutoff в начале - разделитель вверху
            self.separator = tk.Frame(
                self.scrollable_frame,
                height=2,
                bg=COLORS["separator"]
            )
            self.separator.pack(fill="x", pady=5, padx=10)
        else:
            # Пустой список - нет разделителя
            self.separator = None

        # Рендерим active слова (яркие)
        for word, rank in active:
            self._create_word_label(word, rank, "#CCCCCC")

    def _create_word_label(self, word: str, rank: int, color: str):
        """
        Создает кликабельный label для слова.

        Формат: "xxxxx   word" с выравниванием числа вправо.

        Args:
            word: Слово для отображения
            rank: Ранг слова в словаре (0-based)
            color: Цвет текста
        """
        # Формат: "  453   hello" с выравниванием номера вправо на 5 символов
        display_text = f"{rank + 1:>5}   {word}"

        lbl = tk.Label(
            self.scrollable_frame,
            text=display_text,
            font=FONTS["definition"],  # Размер как у definitions в главном окне
            bg=COLORS["bg"],
            fg=color,
            cursor="hand2",
            anchor="w"
        )
        lbl.pack(fill="x", padx=10, pady=1)

        # КРИТИЧНО: Используем default argument для захвата значений word и color
        # Без этого все labels будут использовать последние значения из цикла

        # Клик → поиск слова (САМЫМ ПЕРВЫМ, чтобы не конфликтовать с hover)
        lbl.bind("<Button-1>", lambda e, w=word: self._on_word_click(w))

        # Hover эффект (ПОСЛЕ клика, чтобы не блокировать его)
        lbl.bind("<Enter>", lambda e, c=color, label=lbl: self._on_hover_enter(label, c))
        lbl.bind("<Leave>", lambda e, c=color, label=lbl: self._on_hover_leave(label, c))

    def _on_hover_enter(self, label: tk.Label, original_color: str):
        """
        Hover enter эффект.

        Args:
            label: Label widget
            original_color: Оригинальный цвет текста (для восстановления)
        """
        label.config(bg=COLORS["text_accent"], fg=COLORS["bg"])

    def _on_hover_leave(self, label: tk.Label, original_color: str):
        """
        Hover leave эффект.

        Args:
            label: Label widget
            original_color: Оригинальный цвет текста для восстановления
        """
        label.config(bg=COLORS["bg"], fg=original_color)

    def _on_word_click(self, word: str):
        """
        Обработка клика по слову.

        Args:
            word: Слово для поиска
        """
        if self.search_callback:
            self.search_callback(word)

    def _scroll_to_separator(self):
        """
        Прокручивает canvas так, чтобы separator был по центру окна.

        КРИТИЧНО: Вызывается через after_idle после рендеринга,
        т.к. требуется готовая геометрия всех виджетов.
        """
        if not self.separator:
            return

        # Форсируем обновление геометрии
        self.canvas.update_idletasks()

        # Получаем позицию separator в scrollable_frame
        sep_y = self.separator.winfo_y()
        canvas_height = self.canvas.winfo_height()

        # Получаем полную высоту scrollregion
        scroll_region = self.canvas.cget("scrollregion")
        if not scroll_region:
            return

        total_height = float(scroll_region.split()[3])

        # Вычисляем целевую позицию (separator по центру)
        target_y = (sep_y - canvas_height / 2) / total_height
        target_y = max(0.0, min(1.0, target_y))

        # Прокручиваем
        self.canvas.yview_moveto(target_y)

    def sync_height_with_main(self):
        """
        Синхронизирует высоту popup с главным окном.

        Вызывается при открытии popup.
        """
        main_height = self.main_window.winfo_height()
        self.geometry(f"{self.WINDOW_WIDTH}x{main_height}")

    def show_at_position(self, x: int, y: int):
        """
        Показывает popup в заданной позиции.

        Args:
            x: X координата
            y: Y координата
        """
        # Синхронизируем высоту
        self.sync_height_with_main()

        # Устанавливаем позицию
        main_height = self.main_window.winfo_height()
        self.geometry(f"{self.WINDOW_WIDTH}x{main_height}+{x}+{y}")

        # Показываем окно
        self.deiconify()

    def close(self):
        """Закрывает popup (скрывает через withdraw)"""
        self.withdraw()
