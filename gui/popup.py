import tkinter as tk
from gui.styles import COLORS, FONTS
import vocab  # Импортируем весь модуль для доступа к VOCAB_SIZE и SORTED_WORDS


class VocabPopup(tk.Toplevel):
    """
    Всплывающее окно с превью игнорируемых слов.

    Показывает последние 30 слов перед границей cutoff,
    которые будут игнорироваться при текущем уровне слайдера.
    """

    def __init__(self, parent):
        super().__init__(parent)
        self.overrideredirect(True)
        self.wm_attributes("-topmost", True)
        self.wm_attributes("-alpha", 0.95)
        self.configure(bg=COLORS["bg"])

        frame = tk.Frame(
            self,
            bg=COLORS["bg"],
            highlightbackground=COLORS["close_btn"],
            highlightthickness=2
        )
        frame.pack(fill="both", expand=True)

        tk.Label(
            frame,
            text="Ignored (Known Words):",
            font=("Segoe UI", 9, "bold"),
            bg=COLORS["bg"],
            fg=COLORS["close_btn"]
        ).pack(pady=(5, 2))

        self.text_box = tk.Text(
            frame,
            width=35,
            height=32,
            font=FONTS["console"],
            bg=COLORS["bg"],
            bd=0,
            fg="#586E75"
        )
        self.text_box.pack(padx=10, pady=5)
        self.text_box.config(state="disabled")

    def update_words(self, level):
        """
        Обновляет список игнорируемых слов на основе уровня слайдера.

        Args:
            level: Значение слайдера от 0 до 100

        Логика:
            - level=0:   cutoff=0     → показываем "None (Show All)"
            - level=10:  cutoff=2000  → показываем слова 1971-2000
            - level=50:  cutoff=10000 → показываем слова 9971-10000
            - level=100: cutoff=20000 → показываем слова 19971-20000
        """
        # Динамический расчёт границы на основе размера словаря
        cutoff_rank = int(level * vocab.VOCAB_SIZE / 100)

        if cutoff_rank == 0:
            content = "None (Show All)"
        else:
            # Берём последние 30 слов перед границей
            start = max(0, cutoff_rank - 30)
            end = cutoff_rank

            # Получаем слайс из глобального отсортированного списка
            words_slice = vocab.SORTED_WORDS[start:end]

            # Генерируем ранги (нумерация с 1, а не с 0)
            ranks_slice = range(start + 1, end + 1)

            # Объединяем ранги со словами и переворачиваем (показываем от cutoff вниз)
            zipped = list(zip(ranks_slice, words_slice))
            zipped = zipped[::-1]

            # Форматируем строки вида "19999. word"
            lines = [f"{r}. {w}" for r, w in zipped]
            content = "\n".join(lines)

        # Обновляем содержимое текстового поля
        self.text_box.config(state="normal")
        self.text_box.delete("1.0", "end")
        self.text_box.insert("1.0", content)
        self.text_box.config(state="disabled")
