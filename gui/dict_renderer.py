"""
Рендерер словарных данных для EnglishHelper.

Responsibilities:
- Парсинг и отображение данных из dictionaryapi.dev
- Объединение meanings с одинаковой частью речи
- Рендеринг определений, примеров, синонимов, антонимов
- Hover-переводы для примеров
- Кликабельные синонимы
- Организация контента по кастомным вкладкам
"""

import tkinter as tk
from typing import Dict, List, Optional, Callable
from gui.styles import COLORS, FONTS
from gui.scrollbar import CustomScrollbar


class CustomTabBar(tk.Frame):
    """
    Кастомная полоса вкладок с дизайном Serika Dark.

    Features:
    - Желтая акцентная линия под активной вкладкой
    - Hover эффекты для неактивных вкладок
    - Disabled состояние для пустых вкладок
    """

    def __init__(self, parent, tabs: List[str], on_tab_change: Callable):
        """
        Args:
            parent: Родительский frame
            tabs: Список названий вкладок
            on_tab_change: Callback при смене вкладки (получает index)
        """
        super().__init__(parent, bg=COLORS["bg_secondary"], height=40)
        self.pack_propagate(False)
        self.tabs = tabs
        self.on_tab_change = on_tab_change
        self.active_tab = None
        self.tab_buttons = []
        self.disabled_tabs = set()
        self._create_tabs()

    def _create_tabs(self):
        """Создаёт кнопки-вкладки"""
        for idx, tab_name in enumerate(self.tabs):
            # Контейнер для вкладки с нижней границей
            container = tk.Frame(self, bg=COLORS["bg_secondary"], highlightthickness=0)
            container.pack(side="left", fill="both", expand=True, padx=(0, 0), pady=(1, 0))
            btn = tk.Label(
                container,
                text=tab_name,
                font=FONTS["definition"],
                bg=COLORS["bg_secondary"],
                fg=COLORS["text_main"],
                padx=10,
                pady=5,
                cursor="hand2"
            )
            btn.pack(fill="both", expand=True)

            # Граница снизу (по умолчанию прозрачная)
            border = tk.Frame(container, height=1, bg=COLORS["bg_secondary"])
            border.pack(side="bottom", fill="x")

            btn.bind("<Button-1>", lambda e, i=idx: self._on_tab_click(i))
            btn.bind("<Enter>", lambda e, b=btn, i=idx: self._on_hover_enter(b, i))
            btn.bind("<Leave>", lambda e, b=btn, i=idx: self._on_hover_leave(b, i))

            self.tab_buttons.append((btn, border, container))

    def _on_tab_click(self, idx: int):
        """Обработка клика по вкладке"""
        if idx in self.disabled_tabs:
            return  # Игнорируем клики по disabled вкладкам
        if idx != self.active_tab:
            self.set_active_tab(idx)
            self.on_tab_change(idx)

    def set_active_tab(self, idx: int):
        """
        Устанавливает активную вкладку.

        Args:
            idx: Индекс вкладки
        """
        # Сброс предыдущей активной вкладки (ТОЛЬКО ЕСЛИ ЕСТЬ)
        if self.active_tab is not None:  # ← КРИТИЧНО: проверка на None
            old_btn, old_border, old_container = self.tab_buttons[self.active_tab]
            old_btn.config(
                bg=COLORS["bg_secondary"],
                fg=COLORS["text_main"],
                font=FONTS["definition"]
            )
            old_border.config(bg=COLORS["bg_secondary"])

        # Установка новой активной вкладки
        new_btn, new_border, new_container = self.tab_buttons[idx]
        new_btn.config(
            bg=COLORS["bg"],
            fg=COLORS["text_accent"],
            font=FONTS["definition"]
        )
        new_border.config(bg=COLORS["text_accent"])  # Желтая граница 1px

        self.active_tab = idx

    def set_tab_disabled(self, idx: int, disabled: bool):
        """
        Делает вкладку disabled/enabled.

        Args:
            idx: Индекс вкладки
            disabled: True = disabled, False = enabled
        """
        btn, border, container = self.tab_buttons[idx]
        if disabled:
            self.disabled_tabs.add(idx)
            btn.config(
                fg=COLORS["text_faint"],
                cursor="arrow"
            )
        else:
            self.disabled_tabs.discard(idx)
            btn.config(
                fg=COLORS["text_main"],
                cursor="hand2"
            )

    def _on_hover_enter(self, btn: tk.Label, idx: int):
        """Hover эффект для неактивных вкладок"""
        if idx != self.active_tab and idx not in self.disabled_tabs:
            btn.config(bg="#353739")  # Немного светлее

    def _on_hover_leave(self, btn: tk.Label, idx: int):
        """Уход курсора с неактивной вкладки"""
        if idx != self.active_tab:
            btn.config(bg=COLORS["bg_secondary"])


class CustomNotebook(tk.Frame):
    """
    Кастомный Notebook с табами и content area.

    Responsibilities:
    - Управление переключением вкладок
    - Хранение content frames для каждой вкладки
    - Координация между tab bar и content area
    """

    def __init__(self, parent):
        super().__init__(parent, bg=COLORS["bg"])
        self.tabs_data = {}  # {idx: frame}
        self.current_frame = None

        # Создаём tab bar
        self.tab_bar = CustomTabBar(
            self,
            ["NOUN", "VERB", "ADJECTIVE", "ADVERB", "OTHER"],
            self._on_tab_change
        )
        self.tab_bar.pack(side="top", fill="x")

        # Content area
        self.content_area = tk.Frame(self, bg=COLORS["bg"])
        self.content_area.pack(side="top", fill="both", expand=True)

    def add_tab(self, idx: int, content_frame: tk.Frame, disabled: bool = False):
        """
        Добавляет вкладку.

        Args:
            idx: Индекс вкладки
            content_frame: Frame с содержимым вкладки
            disabled: True если вкладка пустая
        """
        self.tabs_data[idx] = content_frame
        content_frame.pack_forget()  # Скрываем по умолчанию
        if disabled:
            self.tab_bar.set_tab_disabled(idx, True)

    def show_tab(self, idx: int):
        """
        Показывает вкладку.

        Args:
            idx: Индекс вкладки
        """
        # Скрываем текущий frame
        if self.current_frame:
            self.current_frame.pack_forget()

        # Показываем новый frame
        self.current_frame = self.tabs_data[idx]
        self.current_frame.pack(in_=self.content_area, fill="both", expand=True)

        # Обновляем tab bar
        self.tab_bar.set_active_tab(idx)

    def _on_tab_change(self, idx: int):
        """Callback при смене вкладки"""
        self.show_tab(idx)


class DictionaryRenderer:
    """
    Управляет рендерингом словарных данных в scrollable frame.

    Оптимизации:
    - Переиспользование виджетов при возможности
    - Lazy rendering для больших списков
    - Минимум вложенных frames
    - Кастомные вкладки по частям речи
    """

    # Константы для группировки частей речи
    MAJOR_POS = {"noun", "verb", "adjective", "adverb"}
    POS_ORDER = ["noun", "verb", "adjective", "adverb", "other"]
    POS_LABELS = {
        "noun": "NOUN",
        "verb": "VERB",
        "adjective": "ADJECTIVE",
        "adverb": "ADVERB",
        "other": "OTHER"
    }

    # Примеры словоформ (placeholder для lemminflect)
    FORMS_EXAMPLES = {
        "noun": ["Base: cat", "Plural: cats"],
        "verb": ["Base: go", "Past: went", "Past Participle: gone", "Gerund: going"],
        "adjective": ["Base: big", "Comparative: bigger", "Superlative: biggest"],
        "adverb": ["Base: quickly", "Comparative: more quickly"],
        "other": ["Form: that"]
    }

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
            canvas_scroll: Canvas для управления прокруткой (legacy, не используется)
        """
        self.parent = parent_frame
        self.get_content_width = get_content_width
        self.bind_hover_translation = bind_hover_translation
        self.on_synonym_click = on_synonym_click
        self.on_synonym_enter = on_synonym_enter
        self.on_synonym_leave = on_synonym_leave
        self.canvas_scroll = canvas_scroll  # Legacy, не используется

    def clear(self):
        """Очищает все виджеты из scrollable frame"""
        for widget in self.parent.winfo_children():
            widget.destroy()

    def render(self, full_data: Optional[Dict]):
        """
        Рендерит полные словарные данные во вкладках.

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

        # ВСЕГДА создаём вкладки
        self._render_notebook(merged_meanings)

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
        order = []  # Сохраняем порядок первого появления

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

    def _group_meanings(self, merged_meanings: List[Dict]) -> Dict[str, Optional[Dict]]:
        """
        Группирует meanings по категориям вкладок.

        Returns:
            Dict с ключами из POS_ORDER, значения — meaning или None
        """
        grouped = {pos: None for pos in self.POS_ORDER}
        other_meanings = []

        for meaning in merged_meanings:
            pos = meaning.get("partOfSpeech", "").lower()
            if pos in self.MAJOR_POS:
                grouped[pos] = meaning
            else:
                # Собираем все "другие" части речи
                other_meanings.append(meaning)

        # Если есть "другие" части речи, создаём combined meaning
        if other_meanings:
            grouped["other"] = {
                "partOfSpeech": "other",
                "meanings": other_meanings  # Список meanings для рендеринга
            }

        return grouped

    def _get_first_active_index(self, merged_meanings: List[Dict]) -> int:
        """
        Определяет индекс первой активной вкладки.

        Args:
            merged_meanings: Список объединённых meanings

        Returns:
            Индекс первой активной вкладки
        """
        if not merged_meanings:
            return 0

        first_pos = merged_meanings[0].get("partOfSpeech", "").lower()
        if first_pos in self.MAJOR_POS:
            return self.POS_ORDER.index(first_pos)
        else:
            # Если первая часть речи в OTHER
            return self.POS_ORDER.index("other")

    def _render_notebook(self, merged_meanings: List[Dict]):
        """
        Создаёт кастомный Notebook с вкладками по частям речи.

        КРИТИЧНО: Всегда создаёт все 5 вкладок в фиксированном порядке.

        Args:
            merged_meanings: Список объединённых meanings
        """
        # Создаём кастомный notebook
        notebook = CustomNotebook(self.parent)
        notebook.pack(fill="both", expand=True)

        # Группируем meanings
        grouped = self._group_meanings(merged_meanings)

        # Создаём все 5 вкладок
        for idx, pos in enumerate(self.POS_ORDER):
            tab_frame = tk.Frame(notebook.content_area, bg=COLORS["bg"])

            if grouped[pos] is not None:
                # Активная вкладка с данными
                self._create_active_tab_content(tab_frame, grouped[pos], pos)
                notebook.add_tab(idx, tab_frame, disabled=False)
            else:
                # Disabled вкладка с placeholder
                self._create_disabled_tab_content(tab_frame, pos)
                notebook.add_tab(idx, tab_frame, disabled=True)

        # Показываем первую активную вкладку
        first_active_index = self._get_first_active_index(merged_meanings)
        notebook.show_tab(first_active_index)

    def _create_active_tab_content(self, tab_parent: tk.Frame, meaning: Dict, pos: str):
        """
        Создаёт содержимое активной вкладки.

        Структура:
        1. Блок словоформ (фиксированный)
        2. Разделитель
        3. Scrollable блок с определениями

        Args:
            tab_parent: Frame вкладки
            meaning: Объединённый meaning блок
            pos: Часть речи (для примеров форм)
        """
        # Блок 1: Forms (фиксированный)
        forms_frame = tk.Frame(tab_parent, bg=COLORS["bg"])
        forms_frame.pack(fill="x", padx=10, pady=(10, 5))
        self._render_forms_block(forms_frame, pos)

        # Separator
        tk.Frame(tab_parent, height=1, bg=COLORS["separator"]).pack(fill="x", padx=10, pady=5)

        # Блок 2: Scrollable content
        scroll_container = tk.Frame(tab_parent, bg=COLORS["bg"])
        scroll_container.pack(fill="both", expand=True, padx=10, pady=5)

        # Создаём Canvas + Scrollbar для этой вкладки
        canvas = tk.Canvas(scroll_container, bg=COLORS["bg"], highlightthickness=0)
        scrollbar = CustomScrollbar(scroll_container, canvas)
        scrollable_frame = tk.Frame(canvas, bg=COLORS["bg"])

        scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.update)
        canvas.pack(side="left", fill="both", expand=True)

        # Привязываем mousewheel к этому canvas
        canvas.bind("<MouseWheel>", lambda e: self._on_tab_mousewheel(e, canvas))
        scrollable_frame.bind("<MouseWheel>", lambda e: self._on_tab_mousewheel(e, canvas))

        # Рендерим определения
        if pos == "other":
            # Для OTHER рендерим все meanings с заголовками
            self._render_other_content(scrollable_frame, canvas, meaning)
        else:
            # Для обычных частей речи рендерим как обычно
            self._render_scrollable_content(scrollable_frame, canvas, meaning)

    def _create_disabled_tab_content(self, tab_parent: tk.Frame, pos: str):
        """
        Создаёт placeholder для пустой вкладки.

        Args:
            tab_parent: Frame вкладки
            pos: Часть речи
        """
        lbl = tk.Label(
            tab_parent,
            text=f"No {self.POS_LABELS[pos].lower()} definitions",
            font=FONTS["definition"],
            bg=COLORS["bg"],
            fg=COLORS["text_faint"]
        )
        lbl.pack(expand=True)

    def _render_forms_block(self, parent: tk.Frame, pos: str):
        """
        Рендерит блок словоформ (placeholder).

        Args:
            parent: Frame для рендеринга
            pos: Часть речи
        """
        # Заголовок
        lbl_title = tk.Label(
            parent,
            text="Forms:",
            font=FONTS["definition"],
            bg=COLORS["bg"],
            fg=COLORS["text_main"],
            anchor="w"
        )
        lbl_title.pack(anchor="w", pady=(0, 5))

        # Примеры форм
        forms = self.FORMS_EXAMPLES.get(pos, ["Form: example"])
        for form in forms:
            lbl_form = tk.Label(
                parent,
                text=f"  {form}",
                font=FONTS["definition"],
                bg=COLORS["bg"],
                fg=COLORS["text_main"],
                anchor="w"
            )
            lbl_form.pack(anchor="w", pady=1)

    def _render_scrollable_content(self, scrollable_frame: tk.Frame, canvas: tk.Canvas, meaning: Dict):
        """
        Рендерит определения, синонимы, антонимы внутри scrollable frame вкладки.

        Args:
            scrollable_frame: Frame для рендеринга
            canvas: Canvas для mousewheel
            meaning: Объединённый meaning блок
        """
        definitions = meaning.get("definitions", [])
        synonyms = meaning.get("synonyms", [])
        antonyms = meaning.get("antonyms", [])

        # Рендерим определения (сквозная нумерация, без заголовка части речи)
        for idx, definition in enumerate(definitions, start=1):
            self._render_definition(scrollable_frame, canvas, definition, idx)

        # Синонимы (объединённый список под всеми определениями)
        if synonyms:
            self._render_synonyms(scrollable_frame, canvas, synonyms)

        # Антонимы (объединённый список под всеми определениями)
        if antonyms:
            self._render_antonyms(scrollable_frame, canvas, antonyms)

    def _render_other_content(self, scrollable_frame: tk.Frame, canvas: tk.Canvas, other_meaning: Dict):
        """
        Рендерит содержимое вкладки OTHER с заголовками для каждой части речи.

        Args:
            scrollable_frame: Frame для рендеринга
            canvas: Canvas для mousewheel
            other_meaning: Dict с ключом "meanings" содержащим список meanings
        """
        meanings_list = other_meaning.get("meanings", [])

        for meaning in meanings_list:
            pos = meaning.get("partOfSpeech", "unknown")

            # Заголовок части речи
            lbl_pos = tk.Label(
                scrollable_frame,
                text=pos.upper(),
                font=FONTS["pos"],
                bg=COLORS["bg"],
                fg=COLORS["text_accent"]
            )
            lbl_pos.pack(anchor="w", padx=10, pady=(10, 5))
            lbl_pos.bind("<MouseWheel>", lambda e, c=canvas: self._on_tab_mousewheel(e, c))

            # Рендерим определения этой части речи
            self._render_scrollable_content(scrollable_frame, canvas, meaning)

    def _render_definition(self, parent: tk.Frame, canvas: tk.Canvas, definition: Dict, index: int):
        """
        Рендерит одно определение с примером.

        Args:
            parent: Frame для рендеринга
            canvas: Canvas для mousewheel
            definition: Блок определения от API
            index: Номер определения (сквозная нумерация)
        """
        def_text = definition.get("definition", "")
        example = definition.get("example", "")

        if not def_text:
            return

        # Фрейм для определения
        def_frame = tk.Frame(parent, bg=COLORS["bg"])
        def_frame.pack(fill="x", padx=10, pady=2)

        # КРИТИЧНО: Привязываем mousewheel к Frame определения
        def_frame.bind("<MouseWheel>", lambda e: self._on_tab_mousewheel(e, canvas))

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
        lbl_num.bind("<MouseWheel>", lambda e: self._on_tab_mousewheel(e, canvas))

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
        lbl_def.bind("<MouseWheel>", lambda e: self._on_tab_mousewheel(e, canvas))

        # КРИТИЧНО: Привязываем hover-перевод к Label определения
        self.bind_hover_translation(lbl_def, def_text)

        # Пример (с hover-переводом)
        if example:
            # Фрейм для примера — такой же как для определения
            example_frame = tk.Frame(parent, bg=COLORS["bg"])
            example_frame.pack(fill="x", padx=10, pady=(0, 5))

            # КРИТИЧНО: Привязываем mousewheel к Frame примера
            example_frame.bind("<MouseWheel>", lambda e: self._on_tab_mousewheel(e, canvas))

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
            lbl_example_indent.bind("<MouseWheel>", lambda e: self._on_tab_mousewheel(e, canvas))

            # Текст примера (курсивом)
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
            lbl_example.bind("<MouseWheel>", lambda e: self._on_tab_mousewheel(e, canvas))

    def _render_synonyms(self, parent: tk.Frame, canvas: tk.Canvas, synonyms: List[str]):
        """
        Рендерит список синонимов (объединённых из всех блоков) с переносом на новые строки.

        Args:
            parent: Frame для рендеринга
            canvas: Canvas для mousewheel
            synonyms: Список синонимов без дубликатов
        """
        if not synonyms:
            return

        # Основной контейнер
        syn_frame = tk.Frame(parent, bg=COLORS["bg"])
        syn_frame.pack(fill="x", padx=10, pady=(8, 2))

        # КРИТИЧНО: Привязываем mousewheel к Frame синонимов
        syn_frame.bind("<MouseWheel>", lambda e: self._on_tab_mousewheel(e, canvas))

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
        lbl_syn_title.bind("<MouseWheel>", lambda e: self._on_tab_mousewheel(e, canvas))

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
            lbl_syn.bind("<MouseWheel>", lambda e, c=canvas: self._on_tab_mousewheel(e, c))

            current_width += word_width
            col += 1

        temp_label.destroy()

    def _render_antonyms(self, parent: tk.Frame, canvas: tk.Canvas, antonyms: List[str]):
        """
        Рендерит список антонимов (объединённых из всех блоков) с переносом на новые строки.

        Args:
            parent: Frame для рендеринга
            canvas: Canvas для mousewheel
            antonyms: Список антонимов без дубликатов
        """
        if not antonyms:
            return

        # Основной контейнер
        ant_frame = tk.Frame(parent, bg=COLORS["bg"])
        ant_frame.pack(fill="x", padx=10, pady=(8, 2))

        # КРИТИЧНО: Привязываем mousewheel к Frame антонимов
        ant_frame.bind("<MouseWheel>", lambda e: self._on_tab_mousewheel(e, canvas))

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
        lbl_ant_title.bind("<MouseWheel>", lambda e: self._on_tab_mousewheel(e, canvas))

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
            lbl_ant.bind("<MouseWheel>", lambda e, c=canvas: self._on_tab_mousewheel(e, c))

            current_width += word_width
            col += 1

        temp_label.destroy()

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

    def _on_tab_mousewheel(self, event, canvas: tk.Canvas):
        """
        Обработчик mousewheel для Canvas внутри вкладки.

        Перенаправляет событие на соответствующий canvas для корректной прокрутки.
        КРИТИЧНО: Проверяет необходимость прокрутки перед выполнением.

        Args:
            event: MouseWheel событие
            canvas: Canvas вкладки
        """
        # Получаем границы видимой области
        view = canvas.yview()

        # Проверяем нужна ли прокрутка
        # Если весь контент виден (view[0] == 0.0 и view[1] >= 1.0), игнорируем событие
        if view[0] <= 0.0 and view[1] >= 1.0:
            return "break"  # Контент полностью виден, прокрутка не нужна

        # Выполняем прокрутку
        canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        return "break"  # Останавливаем всплытие события

