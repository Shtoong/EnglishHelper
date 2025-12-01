import tkinter as tk
from gui.styles import COLORS, FONTS
from config import cfg
import vocab


class VocabPopup(tk.Toplevel):
    """
    Всплывающее окно с превью игнорируемых слов.

    Автоматически подстраивается под высоту главного окна и показывает
    максимальное количество слов без скроллинга.

    Features:
    - Динамическая высота = высота главного окна
    - Адаптивное количество отображаемых слов
    - Использование единой цветовой схемы приложения
    - Прямой порядок сортировки (от меньшего ранга к большему)
    - Многоточие в начале списка для индикации продолжения
    """

    # ===== КОНСТАНТЫ LAYOUT =====
    WINDOW_WIDTH = 220  # Фиксированная ширина окна
    HEADER_HEIGHT = 35  # Высота заголовка (с pady)
    VERTICAL_PADDING = 30  # Суммарный вертикальный padding (запас)
    LINE_HEIGHT = 13  # Высота одной строки текста (Consolas 8pt + межстрочный интервал)
    MIN_VISIBLE_LINES = 10  # Минимум строк даже для маленького окна
    MAX_VISIBLE_LINES = 100  # Максимум строк для огромного окна
    TEXT_WIDGET_PADDING = 10  # Внутренние отступы Text widget (pady=10 в pack)
    BOTTOM_MARGIN = 15  # Дополнительный запас снизу для предотвращения обрезки

    def __init__(self, parent):
        """
        Инициализация popup окна.

        Args:
            parent: Главное окно приложения (MainWindow)
        """
        super().__init__(parent)
        self.parent = parent

        # ===== НАСТРОЙКА ОКНА =====
        self.overrideredirect(True)
        self.wm_attributes("-topmost", True)
        self.configure(bg=COLORS["bg"])

        # ===== СОЗДАНИЕ UI =====
        self._create_ui()

    def _create_ui(self):
        """Создание элементов интерфейса"""
        # Контейнер с border
        frame = tk.Frame(
            self,
            bg=COLORS["bg"],
            highlightbackground=COLORS["text_accent"],
            highlightthickness=2
        )
        frame.pack(fill="both", expand=True)

        # Заголовок
        tk.Label(
            frame,
            text="Ignored (Known Words):",
            font=("Segoe UI", 9, "bold"),
            bg=COLORS["bg"],
            fg=COLORS["text_accent"]
        ).pack(pady=(5, 2))

        # Текстовое поле для списка слов
        self.text_box = tk.Text(
            frame,
            width=35,
            height=1,  # Временное значение, будет пересчитано
            font=FONTS["console"],
            bg=COLORS["bg"],
            bd=0,
            fg=COLORS["text_faint"],
            padx=5,
            pady=5,
            wrap="none"  # Отключаем перенос строк для точного расчёта
        )
        self.text_box.pack(padx=10, pady=(0, 10), fill="both", expand=True)
        self.text_box.config(state="disabled")

    def show(self, x: int, y: int):
        """
        Показывает popup окно с правильной высотой.

        Args:
            x: X координата для размещения окна
            y: Y координата для размещения окна
        """
        # Безопасное получение высоты главного окна с fallback на конфиг
        parent_height = self.parent.winfo_height()

        # Fallback: если родитель ещё не отрисован (height == 1)
        if parent_height <= 1:
            parent_height = int(cfg.get("USER", "WindowHeight", "700"))

        # Устанавливаем геометрию
        self.geometry(f"{self.WINDOW_WIDTH}x{parent_height}+{x}+{y}")

        # Форсируем отрисовку для корректного winfo_height()
        self.update_idletasks()

        # Пересчитываем высоту Text widget
        visible_lines = self._calculate_visible_lines()
        self.text_box.config(height=visible_lines)

        # Показываем окно
        self.deiconify()

    def _calculate_visible_lines(self) -> int:
        """
        Вычисляет максимальное количество строк, помещающихся в окно без скроллинга.

        Returns:
            Количество строк текста

        Формула:
            available_height = window_height - header - all_paddings - bottom_margin
            visible_lines = available_height / line_height

        Учитываются все отступы:
            - Заголовок с pady
            - Border frame (highlightthickness=2)
            - Text widget padx/pady
            - Нижний margin для предотвращения обрезки

        Ограничения:
            MIN_VISIBLE_LINES <= result <= MAX_VISIBLE_LINES
        """
        window_height = self.winfo_height()

        # Вычисляем доступное пространство для текста
        # Учитываем все отступы:
        # - HEADER_HEIGHT: заголовок + его pady(5,2)
        # - VERTICAL_PADDING: общий запас (border, padx frame и т.д.)
        # - TEXT_WIDGET_PADDING: внутренние отступы Text (pady=5 * 2)
        # - BOTTOM_MARGIN: дополнительный запас снизу
        available_height = (
                window_height
                - self.HEADER_HEIGHT
                - self.VERTICAL_PADDING
                - (self.TEXT_WIDGET_PADDING * 2)
                - self.BOTTOM_MARGIN
        )

        # Количество строк
        visible_lines = int(available_height / self.LINE_HEIGHT)

        # Применяем ограничения
        visible_lines = max(self.MIN_VISIBLE_LINES, visible_lines)
        visible_lines = min(self.MAX_VISIBLE_LINES, visible_lines)

        return visible_lines

    def update_words(self, level: int):
        """
        Обновляет список игнорируемых слов на основе уровня слайдера.

        Args:
            level: Значение слайдера от 0 до 100

        Логика:
            - level=0:   cutoff=0     → "None (Show All)"
            - level>0:   Показывает последние N слов перед cutoff с многоточием сверху

        Формат вывода при level > 0:
            ...
            1971. macquarie
            1972. shouting
            1973. pta
            ...
            2000. wilder

        Многоточие в начале указывает, что список игнорируемых слов продолжается выше.
        """
        # Динамический расчёт границы на основе размера словаря
        cutoff_rank = int(level * vocab.VOCAB_SIZE / 100)

        if cutoff_rank == 0:
            content = "None (Show All)"
        else:
            # Вычисляем максимальное количество слов для текущей высоты
            max_words = self._calculate_visible_lines()

            # Резервируем одну строку для многоточия в начале
            # (если start > 0, т.е. есть слова выше начала списка)
            max_words_for_list = max_words - 1

            # Берём последние N слов перед границей
            start = max(0, cutoff_rank - max_words_for_list)
            end = cutoff_rank

            # Получаем слайс из глобального отсортированного списка
            words_slice = vocab.SORTED_WORDS[start:end]

            # Генерируем ранги (нумерация с 1, а не с 0)
            ranks_slice = range(start + 1, end + 1)

            # Объединяем ранги со словами в прямом порядке
            zipped = list(zip(ranks_slice, words_slice))

            # Форматируем строки вида "1. the"
            lines = [f"{r}. {w}" for r, w in zipped]

            # Добавляем многоточие в начало если есть слова выше
            if start > 0:
                lines.insert(0, "...")

            content = "\n".join(lines)

        # Обновляем содержимое текстового поля
        self.text_box.config(state="normal")
        self.text_box.delete("1.0", "end")
        self.text_box.insert("1.0", content)
        self.text_box.config(state="disabled")
