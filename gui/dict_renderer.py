"""
Рендерер словарных данных для EnglishHelper.

Responsibilities:
- Парсинг и отображение данных из dictionaryapi.dev
- Объединение meanings с одинаковой частью речи
- Рендеринг определений, примеров, синонимов, антонимов
- Hover-переводы для примеров
- Кликабельные синонимы
"""

import tkinter as tk
from typing import Dict, List, Optional, Callable
from gui.styles import COLORS, FONTS


class DictionaryRenderer:
    """
    Управляет рендерингом словарных данных в scrollable frame.

    Оптимизации:
    - Переиспользование виджетов при возможности
    - Lazy rendering для больших списков
    - Минимум вложенных frames
    """

    def __init__(self,
                 parent_frame: tk.Frame,
                 get_content_width: Callable[[], int],
                 bind_hover_translation: Callable[[tk.Widget, str], None],
                 on_synonym_click: Callable[[str], None],
                 on_synonym_enter: Callable,
                 on_synonym_leave: Callable,
                 canvas_scroll: tk.Canvas):
        """
        Args:
            parent_frame: Scrollable frame для рендеринга
            get_content_width: Функция получения ширины контента
            bind_hover_translation: Функция привязки hover-перевода
            on_synonym_click: Callback для клика по синониму
            on_synonym_enter: Callback для hover на синониме
            on_synonym_leave: Callback для leave с синонима
            canvas_scroll: Canvas для управления прокруткой
        """
        self.parent = parent_frame
        self.get_content_width = get_content_width
        self.bind_hover_translation = bind_hover_translation
        self.on_synonym_click = on_synonym_click
        self.on_synonym_enter = on_synonym_enter
        self.on_synonym_leave = on_synonym_leave
        self.canvas_scroll = canvas_scroll

    def clear(self):
        """Очищает все виджеты из scrollable frame"""
        for widget in self.parent.winfo_children():
            widget.destroy()

    def render(self, full_data: Optional[Dict]):
        """
        Рендерит полные словарные данные.

        Args:
            full_data: Данные от dictionaryapi.dev или None
        """
        self.clear()

        if not full_data or not full_data.get("meanings"):
            self._render_no_data()
            return

        meanings = full_data.get("meanings", [])

        # КРИТИЧНО: Объединяем meanings с одинаковой частью речи перед рендерингом
        merged_meanings = self._merge_meanings_by_pos(meanings)

        # Рендерим объединённые meanings
        for meaning in merged_meanings:
            self._render_meaning(meaning)

    def _merge_meanings_by_pos(self, meanings: List[Dict]) -> List[Dict]:
        """
        Объединяет meanings с одинаковой частью речи.

        Логика:
        - Группирует по partOfSpeech
        - Сохраняет порядок первого появления части речи
        - Объединяет definitions[] (сквозная нумерация)
        - Объединяет synonyms[] и antonyms[] без дубликатов (case-insensitive)
        - Скрывает блоки с пустыми definitions[]

        Args:
            meanings: Список meanings от API

        Returns:
            Список объединённых meanings с уникальными partOfSpeech
        """
        merged = {}  # {partOfSpeech: {definitions: [], synonyms: [], antonyms: []}}
        order = []   # Сохраняем порядок первого появления

        for meaning in meanings:
            pos = meaning.get("partOfSpeech", "unknown")

            if pos not in merged:
                order.append(pos)
                merged[pos] = {
                    "partOfSpeech": pos,
                    "definitions": [],
                    "synonyms": [],
                    "antonyms": []
                }

            # Объединяем definitions (сохраняем порядок API)
            merged[pos]["definitions"].extend(meaning.get("definitions", []))

            # Объединяем synonyms (без дубликатов, case-insensitive)
            existing_synonyms_lower = [s.lower() for s in merged[pos]["synonyms"]]
            for syn in meaning.get("synonyms", []):
                if syn.lower() not in existing_synonyms_lower:
                    merged[pos]["synonyms"].append(syn)
                    existing_synonyms_lower.append(syn.lower())

            # Объединяем antonyms (без дубликатов, case-insensitive)
            existing_antonyms_lower = [a.lower() for a in merged[pos]["antonyms"]]
            for ant in meaning.get("antonyms", []):
                if ant.lower() not in existing_antonyms_lower:
                    merged[pos]["antonyms"].append(ant)
                    existing_antonyms_lower.append(ant.lower())

        # Возвращаем в порядке первого появления, пропуская пустые definitions
        result = []
        for pos in order:
            if merged[pos]["definitions"]:  # Скрываем блоки с пустыми definitions
                result.append(merged[pos])

        return result

    def _render_no_data(self):
        """Рендерит placeholder при отсутствии данных"""
        lbl = tk.Label(
            self.parent,
            text="No dictionary data",
            font=FONTS["definition"],
            bg=COLORS["bg"],
            fg=COLORS["text_faint"]
        )
        lbl.pack(pady=20)

    def _render_meaning(self, meaning: Dict):
        """
        Рендерит один блок meaning (часть речи + определения + синонимы/антонимы).

        Args:
            meaning: Объединённый meaning блок
        """
        part_of_speech = meaning.get("partOfSpeech", "")
        definitions = meaning.get("definitions", [])
        synonyms = meaning.get("synonyms", [])
        antonyms = meaning.get("antonyms", [])

        # Пропускаем если нет определений (защита на случай пустого блока)
        if not definitions:
            return

        # Заголовок части речи
        if part_of_speech and part_of_speech != "unknown":
            lbl_pos = tk.Label(
                self.parent,
                text=part_of_speech.upper(),
                font=FONTS["pos"],
                bg=COLORS["bg"],
                fg=COLORS["text_accent"]
            )
            lbl_pos.pack(anchor="w", padx=10, pady=(10, 5))

            # КРИТИЧНО: Привязываем mousewheel к заголовку части речи
            lbl_pos.bind("<MouseWheel>", self._on_label_mousewheel)

        # Рендерим определения (сквозная нумерация)
        for idx, definition in enumerate(definitions, start=1):
            self._render_definition(definition, idx)

        # Синонимы (объединённый список под всеми определениями)
        if synonyms:
            self._render_synonyms(synonyms)

        # Антонимы (объединённый список под всеми определениями)
        if antonyms:
            self._render_antonyms(antonyms)

    def _render_definition(self, definition: Dict, index: int):
        """
        Рендерит одно определение с примером.

        Args:
            definition: Блок определения от API
            index: Номер определения (сквозная нумерация)
        """
        def_text = definition.get("definition", "")
        example = definition.get("example", "")

        if not def_text:
            return

        # Фрейм для определения
        def_frame = tk.Frame(self.parent, bg=COLORS["bg"])
        def_frame.pack(fill="x", padx=10, pady=2)

        # КРИТИЧНО: Привязываем mousewheel к Frame определения
        def_frame.bind("<MouseWheel>", self._on_label_mousewheel)

        # Номер определения
        lbl_num = tk.Label(
            def_frame,
            text=f"{index}.",
            font=FONTS["definition"],
            bg=COLORS["bg"],
            fg=COLORS["text_accent"]
        )
        lbl_num.pack(side="left", anchor="nw", padx=(0, 5))

        # КРИТИЧНО: Привязываем mousewheel к номеру определения
        lbl_num.bind("<MouseWheel>", self._on_label_mousewheel)

        # Текст определения
        lbl_def = tk.Label(
            def_frame,
            text=def_text,
            font=FONTS["definition"],
            bg=COLORS["bg"],
            fg=COLORS["text_main"],
            wraplength=self.get_content_width() - 40,
            justify="left",
            anchor="w"
        )
        lbl_def.pack(side="left", fill="x", expand=True, anchor="nw")

        # КРИТИЧНО: Привязываем mousewheel к Label определения
        lbl_def.bind("<MouseWheel>", self._on_label_mousewheel)

        # КРИТИЧНО: Привязываем hover-перевод к Label определения
        self.bind_hover_translation(lbl_def, def_text)

        # Пример (с hover-переводом)
        if example:
            # Фрейм для примера — такой же как для определения
            example_frame = tk.Frame(self.parent, bg=COLORS["bg"])
            example_frame.pack(fill="x", padx=10, pady=(0, 5))

            # КРИТИЧНО: Привязываем mousewheel к Frame примера
            example_frame.bind("<MouseWheel>", self._on_label_mousewheel)

            # Пустой Label для отступа (такой же как номер определения)
            lbl_example_indent = tk.Label(
                example_frame,
                text="",
                font=FONTS["definition"],
                bg=COLORS["bg"],
                width=len(f"{index}.")
            )
            lbl_example_indent.pack(side="left", anchor="nw", padx=(0, 5))

            # КРИТИЧНО: Привязываем mousewheel к отступу примера
            lbl_example_indent.bind("<MouseWheel>", self._on_label_mousewheel)

            # Текст примера
            lbl_example = tk.Label(
                example_frame,
                text=example,
                font=(FONTS["definition"][0], FONTS["definition"][1], "italic"),
                bg=COLORS["bg"],
                fg=COLORS["text_faint"],
                wraplength=self.get_content_width() - 40,
                justify="left",
                anchor="w"
            )
            lbl_example.pack(side="left", fill="x", expand=True, anchor="nw")

            # Привязываем hover-перевод для примера
            self.bind_hover_translation(lbl_example, example)

            # КРИТИЧНО: Привязываем mousewheel к Label примера
            lbl_example.bind("<MouseWheel>", self._on_label_mousewheel)

    def _render_synonyms(self, synonyms: List[str]):
        """
        Рендерит список синонимов (объединённых из всех блоков) с переносом на новые строки.

        Args:
            synonyms: Список синонимов без дубликатов
        """
        if not synonyms:
            return

        # Основной контейнер
        syn_frame = tk.Frame(self.parent, bg=COLORS["bg"])
        syn_frame.pack(fill="x", padx=10, pady=(8, 2))

        # КРИТИЧНО: Привязываем mousewheel к Frame синонимов
        syn_frame.bind("<MouseWheel>", self._on_label_mousewheel)

        # Заголовок в первой строке, первой колонке
        lbl_syn_title = tk.Label(
            syn_frame,
            text="Synonyms:",
            font=FONTS["definition"],
            bg=COLORS["bg"],
            fg=COLORS["text_faint"]
        )
        lbl_syn_title.grid(row=0, column=0, sticky="w", padx=(0, 5))

        # КРИТИЧНО: Привязываем mousewheel к заголовку
        lbl_syn_title.bind("<MouseWheel>", self._on_label_mousewheel)

        # Создаём синонимы в grid для переноса
        available_width = self.get_content_width() - 100
        current_width = 0
        row = 0
        col = 1

        # Временный Label для измерения ширины
        temp_label = tk.Label(syn_frame, font=FONTS["definition"])

        for idx, syn in enumerate(synonyms[:20]):
            # Измеряем ширину синонима
            temp_label.config(text=syn)
            temp_label.update_idletasks()
            word_width = temp_label.winfo_reqwidth() + 20

            # Проверяем перенос
            if current_width + word_width > available_width and col > 1:
                row += 1
                col = 1
                current_width = 0

            # Создаём Label для синонима
            lbl_syn = tk.Label(
                syn_frame,
                text=syn,
                font=FONTS["definition"],
                bg=COLORS["bg"],
                fg=COLORS["text_accent"],
                cursor="hand2",
                padx=5
            )
            lbl_syn.grid(row=row, column=col, sticky="w")

            # Привязываем события - ТОЛЬКО наши обработчики, без bind_hover_translation
            lbl_syn.bind("<Button-1>", lambda e, word=syn: self.on_synonym_click(word))
            lbl_syn.bind("<Enter>", lambda e, word=syn, btn=lbl_syn: self._on_synonym_hover_enter(e, word, btn))
            lbl_syn.bind("<Leave>", lambda e, btn=lbl_syn: self._on_synonym_hover_leave(e, btn))
            lbl_syn.bind("<MouseWheel>", self._on_label_mousewheel)

            current_width += word_width
            col += 1

        temp_label.destroy()

    def _render_antonyms(self, antonyms: List[str]):
        """
        Рендерит список антонимов (объединённых из всех блоков) с переносом на новые строки.

        Args:
            antonyms: Список антонимов без дубликатов
        """
        if not antonyms:
            return

        # Основной контейнер
        ant_frame = tk.Frame(self.parent, bg=COLORS["bg"])
        ant_frame.pack(fill="x", padx=10, pady=(8, 2))

        # КРИТИЧНО: Привязываем mousewheel к Frame антонимов
        ant_frame.bind("<MouseWheel>", self._on_label_mousewheel)

        # Заголовок в первой строке, первой колонке
        lbl_ant_title = tk.Label(
            ant_frame,
            text="Antonyms:",
            font=FONTS["definition"],
            bg=COLORS["bg"],
            fg=COLORS["text_faint"]
        )
        lbl_ant_title.grid(row=0, column=0, sticky="w", padx=(0, 5))

        # КРИТИЧНО: Привязываем mousewheel к заголовку
        lbl_ant_title.bind("<MouseWheel>", self._on_label_mousewheel)

        # Создаём антонимы в grid для переноса
        available_width = self.get_content_width() - 100
        current_width = 0
        row = 0
        col = 1

        # Временный Label для измерения ширины
        temp_label = tk.Label(ant_frame, font=FONTS["definition"])

        for idx, ant in enumerate(antonyms[:20]):
            # Измеряем ширину антонима
            temp_label.config(text=ant)
            temp_label.update_idletasks()
            word_width = temp_label.winfo_reqwidth() + 20

            # Проверяем перенос
            if current_width + word_width > available_width and col > 1:
                row += 1
                col = 1
                current_width = 0

            # Создаём Label для антонима
            lbl_ant = tk.Label(
                ant_frame,
                text=ant,
                font=FONTS["definition"],
                bg=COLORS["bg"],
                fg=COLORS["text_accent"],
                cursor="hand2",
                padx=5
            )
            lbl_ant.grid(row=row, column=col, sticky="w")

            # Привязываем события - ТОЛЬКО наши обработчики, без bind_hover_translation
            lbl_ant.bind("<Button-1>", lambda e, word=ant: self.on_synonym_click(word))
            lbl_ant.bind("<Enter>", lambda e, word=ant, btn=lbl_ant: self._on_synonym_hover_enter(e, word, btn))
            lbl_ant.bind("<Leave>", lambda e, btn=lbl_ant: self._on_synonym_hover_leave(e, btn))
            lbl_ant.bind("<MouseWheel>", self._on_label_mousewheel)

            current_width += word_width
            col += 1

        temp_label.destroy()

    def _on_synonym_hover_enter(self, event, word: str, label: tk.Label):
        """
        Обработка наведения на синоним/антоним - желтый фон, черный текст.

        Args:
            event: Событие Enter
            word: Слово для перевода
            label: Label виджет
        """
        # Меняем цвет на желтый фон + черный текст
        label.config(bg="#FFD700", fg="#000000")

        # Вызываем оригинальный hover callback (если нужен)
        self.on_synonym_enter(event, word, label)

    def _on_synonym_hover_leave(self, event, label: tk.Label):
        """
        Обработка ухода курсора с синонима/антонима - возврат к исходным цветам.

        Args:
            event: Событие Leave
            label: Label виджет
        """
        # Возвращаем исходные цвета
        label.config(bg=COLORS["bg"], fg=COLORS["text_accent"])

    def _on_label_mousewheel(self, event):
        """
        Обработчик mousewheel для всех Label внутри scrollable frame.
        Перенаправляет событие на canvas для корректной прокрутки.

        Args:
            event: MouseWheel событие
        """
        self.canvas_scroll.yview_scroll(int(-1 * (event.delta / 120)), "units")
        return "break"  # Останавливаем всплытие события
