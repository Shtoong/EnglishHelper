"""
Рендеринг словарных данных для EnglishHelper.

Обрабатывает:
- Отрисовку meanings (части речи, определения, примеры)
- Отрисовку синонимов с интерактивностью
- Placeholder при отсутствии данных
"""

import tkinter as tk
from typing import Dict, List, Optional, Callable
from gui.styles import COLORS, FONTS


class DictionaryRenderer:
    """
    Отрисовывает словарные данные в scrollable frame.

    Responsibilities:
    - Парсинг структуры meanings из API
    - Создание UI элементов (labels, frames)
    - Привязка hover эффектов через callbacks
    - Управление интерактивными синонимами

    Dependencies:
    - parent_frame: куда рендерить
    - content_width_callback: для wraplength
    - hover_callback: для биндинга hover-переводов
    - synonym_click_callback: для кликов по синонимам
    """

    # Константы рендеринга
    MAX_SYNONYMS = 5  # Максимум синонимов для отображения

    def __init__(self,
                 parent_frame: tk.Frame,
                 content_width_callback: Callable[[], int],
                 hover_callback: Callable[[tk.Widget, str], None],
                 synonym_click_callback: Callable[[str], None],
                 synonym_enter_callback: Callable[[object, str, tk.Label], None],
                 synonym_leave_callback: Callable[[object, tk.Label], None]):
        """
        Args:
            parent_frame: Frame куда рендерить словарные данные
            content_width_callback: Функция возвращающая доступную ширину контента
            hover_callback: Callback для биндинга hover-перевода на виджет
            synonym_click_callback: Callback для клика по синониму
            synonym_enter_callback: Callback для hover синонима
            synonym_leave_callback: Callback для leave синонима
        """
        self.parent_frame = parent_frame
        self.get_content_width = content_width_callback
        self.bind_hover = hover_callback
        self.on_synonym_click = synonym_click_callback
        self.on_synonym_enter = synonym_enter_callback
        self.on_synonym_leave = synonym_leave_callback

    def render(self, full_data: Optional[Dict]) -> None:
        """
        Рендерит полные данные словаря в parent_frame.

        Очищает предыдущее содержимое и создаёт новое на основе данных.

        Args:
            full_data: Словарные данные из API (или None если нет данных)
        """
        # Очистка предыдущего контента
        self.clear()

        # Рендеринг на основе наличия данных
        if not full_data or not full_data.get("meanings"):
            self._render_no_data_placeholder()
        else:
            self._render_meanings(full_data.get("meanings", []))

    def clear(self) -> None:
        """Очищает все дочерние виджеты из parent_frame"""
        for widget in self.parent_frame.winfo_children():
            widget.destroy()

    def _render_no_data_placeholder(self) -> None:
        """Отрисовывает placeholder когда нет словарных данных"""
        tk.Label(
            self.parent_frame,
            text="No detailed data available",
            font=FONTS["definition"],
            bg=COLORS["bg"],
            fg=COLORS["text_faint"]
        ).pack(pady=10)

    def _render_meanings(self, meanings: List[Dict]) -> None:
        """
        Отрисовывает meanings (части речи, определения, примеры, синонимы).

        Структура для каждого meaning:
        - Part of speech (заголовок)
        - Definitions (нумерованный список с примерами)
        - Synonyms (интерактивные теги)
        - Separator (горизонтальная линия)

        Args:
            meanings: Список meanings объектов из API
        """
        for meaning in meanings:
            # Часть речи (noun, verb, adjective, etc)
            pos = meaning.get("partOfSpeech", "")
            tk.Label(
                self.parent_frame,
                text=pos,
                font=FONTS["pos"],
                bg=COLORS["bg"],
                fg=COLORS["text_pos"],
                anchor="w"
            ).pack(fill="x", pady=(10, 5))

            # Определения и примеры
            self._render_definitions(meaning.get("definitions", []))

            # Синонимы
            self._render_synonyms(meaning.get("synonyms", []))

            # Разделитель между meanings
            tk.Frame(
                self.parent_frame,
                height=1,
                bg=COLORS["separator"],
                width=360
            ).pack(pady=5)

    def _render_definitions(self, definitions: List[Dict]) -> None:
        """
        Отрисовывает список определений с примерами.

        Формат:
        1. Definition text
           "Example sentence"
        2. Another definition
           "Another example"

        Hover эффекты:
        - На definition → показать перевод
        - На example → показать перевод

        Args:
            definitions: Список definition объектов
        """
        for i, defn in enumerate(definitions, 1):
            # Определение (нумерованное)
            def_text = f"{i}. {defn.get('definition', '')}"
            lbl_def = tk.Label(
                self.parent_frame,
                text=def_text,
                font=FONTS["definition"],
                bg=COLORS["bg"],
                fg=COLORS["text_main"],
                wraplength=self.get_content_width(),
                justify="left",
                anchor="w"
            )
            lbl_def.pack(fill="x", padx=10, pady=2)

            # Биндинг hover-перевода на определение
            self.bind_hover(lbl_def, defn.get('definition', ''))

            # Пример (если есть)
            if defn.get("example"):
                ex_text = f'   "{defn["example"]}"'
                lbl_ex = tk.Label(
                    self.parent_frame,
                    text=ex_text,
                    font=FONTS["example"],
                    bg=COLORS["bg"],
                    fg=COLORS["text_accent"],
                    wraplength=self.get_content_width(),
                    justify="left",
                    anchor="w"
                )
                lbl_ex.pack(fill="x", padx=10, pady=(0, 5))

                # Биндинг hover-перевода на пример
                self.bind_hover(lbl_ex, defn.get("example", ""))

    def _render_synonyms(self, synonyms: List[str]) -> None:
        """
        Отрисовывает синонимы как интерактивные теги.

        Features:
        - Максимум MAX_SYNONYMS синонимов
        - Hover эффект (подсветка + tooltip с переводом)
        - Клик → поиск синонима как нового слова

        Layout: [Syn:] [tag1] [tag2] [tag3] ...

        Args:
            synonyms: Список синонимов
        """
        if not synonyms:
            return

        # Контейнер для синонимов
        syn_frame = tk.Frame(self.parent_frame, bg=COLORS["bg"])
        syn_frame.pack(fill="x", padx=10, pady=(5, 10))

        # Label "Syn:"
        tk.Label(
            syn_frame,
            text="Syn:",
            font=FONTS["synonym_label"],
            bg=COLORS["bg"],
            fg=COLORS["text_faint"]
        ).pack(side="left", anchor="n")

        # Теги синонимов (ограничиваем количество)
        for syn in synonyms[:self.MAX_SYNONYMS]:
            tag = tk.Label(
                syn_frame,
                text=syn,
                font=FONTS["synonym"],
                bg=COLORS["bg_secondary"],
                fg=COLORS["text_main"],
                padx=6,
                pady=2,
                cursor="hand2"
            )
            tag.pack(side="left", padx=3)

            # Биндинг событий для интерактивности
            tag.bind(
                "<Enter>",
                lambda e, t=syn, w=tag: self.on_synonym_enter(e, t, w)
            )
            tag.bind(
                "<Leave>",
                lambda e, w=tag: self.on_synonym_leave(e, w)
            )
            tag.bind(
                "<Button-1>",
                lambda e, w=syn: self.on_synonym_click(w)
            )
