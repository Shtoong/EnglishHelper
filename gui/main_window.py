"""
Главное окно приложения EnglishHelper.

Отображает:
- Заголовок слова
- Перевод на русский
- Изображение ассоциации
- Прокручиваемый список определений и примеров
- Слайдер уровня словаря с popup превью
- Статус бар с кнопками управления

Architecture:
- Координирует работу компонентов (DictRenderer)
- Управляет layout и window state
- Обрабатывает callbacks из main.pyw
"""

import tkinter as tk
from PIL import Image, ImageTk
import keyboard
import threading
import time
from typing import Dict, List, Optional, Callable
from collections import OrderedDict

from config import cfg, get_cache_size_mb, clear_cache
from gui.styles import COLORS, FONTS
from gui.components import ResizeGrip, TranslationTooltip
from gui.scrollbar import CustomScrollbar
from gui.popup import VocabPopup
from gui.sent_window import SentenceWindow
from gui.buttons import ToggleButton, ActionButton
from gui.dict_renderer import DictionaryRenderer
from network import fetch_sentence_translation


class MainWindow(tk.Tk):
    """
    Главное окно приложения.

    Responsibilities:
    - Window management (создание, перемещение, resize, закрытие)
    - Layout и UI creation
    - Координация компонентов (dict renderer, tooltip, etc)
    - Обработка callbacks из main.pyw
    - Vocab slider и popup управление
    """

    # ===== LAYOUT КОНСТАНТЫ =====
    IMAGE_MAX_HEIGHT = 250
    IMAGE_PADDING = 40
    CONTENT_PADDING = 60
    DEFAULT_WRAPLENGTH = 380
    MIN_WINDOW_WIDTH = 300
    MIN_WINDOW_HEIGHT = 400

    # ===== UI ПОВЕДЕНИЕ =====
    HOVER_DELAY_MS = 300
    MAX_TRANS_CACHE_SIZE = 500  # LRU limit для предотвращения memory leak

    def __init__(self):
        super().__init__()

        # Настройка окна
        self.overrideredirect(True)
        self.wm_attributes("-topmost", True)

        x = cfg.get("USER", "WindowX", "100")
        y = cfg.get("USER", "WindowY", "100")
        w = cfg.get("USER", "WindowWidth", "400")
        h = cfg.get("USER", "WindowHeight", "700")
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.configure(bg=COLORS["bg"])

        # Установка минимального размера окна
        self.minsize(self.MIN_WINDOW_WIDTH, self.MIN_WINDOW_HEIGHT)

        # ===== СОСТОЯНИЕ =====
        self.sources = {"trans": "wait", "img": "wait"}
        self.dragging_allowed = False
        self.trans_cache = OrderedDict()  # LRU cache для hover-переводов
        self.hover_timer = None

        # Флаги для умного управления popup слайдера
        self._slider_was_moved = False  # Отслеживает факт движения ползунка
        self._popup_was_open_before_click = False  # Запоминает состояние popup ДО клика

        # Callbacks устанавливаются из main.pyw
        self.search_callback = None
        self.clipboard_callback = None

        # ===== СОЗДАНИЕ КОМПОНЕНТОВ =====
        # Эти компоненты создаются ДО _init_ui т.к. нужны для инициализации менеджеров
        self.sent_window = SentenceWindow(self)
        self.tooltip = TranslationTooltip(self)
        self.popup = VocabPopup(self)

        # Инициализация UI (создаёт все виджеты)
        self._init_ui()

        # ===== СОЗДАНИЕ МЕНЕДЖЕРОВ =====
        # Создаются ПОСЛЕ _init_ui т.к. требуют ссылки на виджеты
        self.dict_renderer = DictionaryRenderer(
            self.scrollable_frame,
            lambda: self.content_width,
            self._bind_hover_translation,
            self.on_synonym_click,
            self._on_synonym_enter,
            self._on_synonym_leave,
            self.canvas_scroll
        )

        # Финальная настройка
        self._bind_events()
        self._sync_initial_state()
        self.update_cache_button()

    @property
    def content_width(self) -> int:
        """Ширина области контента с учетом padding"""
        return self.winfo_width() - self.CONTENT_PADDING

    def _init_ui(self):
        """
        Инициализация всех UI элементов.

        КРИТИЧНО: Порядок создания элементов важен для правильного layout:
        1. Верхние элементы (top bar, header, translation, image, separator)
        2. BOTTOM FRAME (слайдер + кнопки) - создаётся РАНЬШЕ scrollable content
        3. Scrollable content - заполняет оставшееся пространство

        Это предотвращает выталкивание bottom_frame за границы окна при показе картинки.
        """
        self._create_top_bar()
        self._create_word_header()
        self._create_translation_display()
        self._create_image_container()
        self._create_separator()

        # КРИТИЧНО: Создаём bottom_frame ДО scrollable_content
        self._create_vocab_slider()
        self._create_status_bar()

        # Scrollable content создаётся ПОСЛЕДНИМ
        self._create_scrollable_content()

    def _create_label(self, parent, text: str = "", font_key: str = "definition",
                      fg_key: str = "text_main", **kwargs) -> tk.Label:
        """Фабрика для создания стилизованных Label с дефолтными стилями"""
        defaults = {
            "font": FONTS[font_key],
            "bg": COLORS["bg"],
            "fg": COLORS[fg_key]
        }
        defaults.update(kwargs)
        return tk.Label(parent, text=text, **defaults)

    def _create_separator(self, width: int = 360) -> None:
        """Создаёт горизонтальный разделитель"""
        tk.Frame(
            self,
            height=1,
            bg=COLORS["separator"],
            width=width
        ).pack(pady=5)

    def _create_top_bar(self):
        """Верхняя панель с кнопкой закрытия"""
        top_bar = tk.Frame(self, bg=COLORS["bg"], height=30)
        top_bar.pack(fill="x", pady=(5, 0))

        btn_close = self._create_label(
            top_bar,
            text="✕",
            font_key="header",
            fg_key="close_btn",
            cursor="hand2"
        )
        btn_close.config(font=FONTS["close_btn"])
        btn_close.pack(side="right", padx=10)
        btn_close.bind("<Button-1>", lambda e: self.close_app())

    def _create_word_header(self):
        """Заголовок слова"""
        self.lbl_word = self._create_label(
            self,
            text="English Helper",
            font_key="header",
            fg_key="text_header"
        )
        self.lbl_word.pack(pady=(10, 5), anchor="center")

    def _create_translation_display(self):
        """Область отображения перевода"""
        self.lbl_rus = self._create_label(
            self,
            text="Ready",
            fg_key="text_accent",
            wraplength=self.DEFAULT_WRAPLENGTH,
            justify="center"
        )
        self.lbl_rus.config(font=FONTS["translation"])
        self.lbl_rus.pack(anchor="center", padx=10, pady=(5, 10))

    def _create_image_container(self):
        """Контейнер для изображения"""
        self.img_container = tk.Label(
            self,
            bg=COLORS["bg"]
        )
        self.img_container.pack(pady=5)

    def _create_scrollable_content(self):
        """
        Прокручиваемая область с определениями и кастомным scrollbar.

        КРИТИЧНО: Этот метод вызывается ПОСЛЕ _create_vocab_slider() и _create_status_bar(),
        чтобы scrollable content занял только оставшееся пространство между верхними
        элементами и нижним фреймом (который уже запакован с side="bottom").
        """
        scroll_container = tk.Frame(self, bg=COLORS["bg"])
        scroll_container.pack(fill="both", expand=True, padx=10, pady=5)

        self.canvas_scroll = tk.Canvas(
            scroll_container,
            bg=COLORS["bg"],
            highlightthickness=0
        )

        # Кастомный scrollbar
        self.scrollbar = CustomScrollbar(scroll_container, self.canvas_scroll)

        self.scrollable_frame = tk.Frame(self.canvas_scroll, bg=COLORS["bg"])

        self.scrollable_frame.bind("<Configure>", self._on_frame_configure)

        self.canvas_scroll.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas_scroll.configure(yscrollcommand=self.scrollbar.update)
        self.canvas_scroll.pack(side="left", fill="both", expand=True)

        # Используем локальные bind вместо bind_all
        self.canvas_scroll.bind("<MouseWheel>", self._on_mousewheel)
        self.scrollable_frame.bind("<MouseWheel>", self._on_mousewheel)

    def _create_vocab_slider(self):
        """
        Слайдер уровня словаря.

        КРИТИЧНО: Создаётся с side="bottom" ДО _create_scrollable_content(),
        чтобы всегда оставаться внизу окна независимо от размера картинки.
        """
        self.bottom_frame = tk.Frame(self, bg=COLORS["bg"])
        self.bottom_frame.pack(side="bottom", fill="x", padx=0, pady=0)

        slider_area = tk.Frame(self.bottom_frame, bg=COLORS["bg"])
        slider_area.pack(side="top", fill="x", padx=10, pady=(5, 0))

        self._create_label(
            slider_area,
            text="Vocab:",
            font_key="ui",
            fg_key="text_faint"
        ).pack(side="left")

        self.vocab_var = tk.IntVar(value=int(cfg.get("USER", "VocabLevel")))

        # Кнопки управления
        btn_minus = self._create_label(
            slider_area,
            text="<",
            fg_key="text_accent",
            cursor="hand2"
        )
        btn_minus.config(font=("Consolas", 12, "bold"))
        btn_minus.pack(side="left", padx=2)
        btn_minus.bind("<Button-1>", lambda e: self.change_level(-1))

        # Слайдер
        self.scale = tk.Scale(
            slider_area,
            from_=0,
            to=100,
            orient="horizontal",
            variable=self.vocab_var,
            showvalue=0,
            bg=COLORS["bg"],
            troughcolor=COLORS["bg_secondary"],
            activebackground=COLORS["text_accent"],
            bd=0,
            highlightthickness=0,
            length=150
        )
        self.scale.pack(side="left", padx=2, fill="x", expand=True)

        btn_plus = self._create_label(
            slider_area,
            text=">",
            fg_key="text_accent",
            cursor="hand2"
        )
        btn_plus.config(font=("Consolas", 12, "bold"))
        btn_plus.pack(side="left", padx=2)
        btn_plus.bind("<Button-1>", lambda e: self.change_level(1))

        # Отображение значения
        self.lbl_lvl_val = self._create_label(
            slider_area,
            text=str(self.vocab_var.get()),
            fg_key="text_header"
        )
        self.lbl_lvl_val.config(font=("Segoe UI", 9, "bold"))
        self.lbl_lvl_val.pack(side="left", padx=(5, 0))
        self.scale.config(command=lambda v: self.lbl_lvl_val.config(text=v))

    def _create_status_bar(self):
        """
        Нижняя панель статуса с кнопками управления.

        КРИТИЧНО: Создаётся внутри bottom_frame, который уже запакован с side="bottom".
        """
        status_bar = tk.Frame(self.bottom_frame, bg=COLORS["bg"])
        status_bar.pack(side="bottom", fill="x", pady=2)

        # Resize grip
        self.grip = ResizeGrip(
            status_bar,
            self.resize_window,
            self.save_size,
            COLORS["bg"],
            COLORS["resize_grip"]
        )
        self.grip.pack(side="right", anchor="se")

        # Статус
        self.lbl_status = tk.Label(
            status_bar,
            text="Waiting...",
            font=("Segoe UI", 7),
            bg=COLORS["bg"],
            fg=COLORS["text_faint"]
        )
        self.lbl_status.pack(side="right", padx=5)

        # Кнопки-переключатели
        self.btn_toggle_sent = ToggleButton(
            status_bar,
            "Sentence",
            "ShowSentenceWindow",
            self.toggle_sentence_window
        )
        self.btn_toggle_sent.pack(side="left", padx=(10, 5))

        self.btn_toggle_pronounce = ToggleButton(
            status_bar,
            "Pronunciation",
            "AutoPronounce",
            self.toggle_auto_pronounce
        )
        self.btn_toggle_pronounce.pack(side="left", padx=(0, 5))

        # Кнопка очистки кэша
        self.btn_cache = ActionButton(
            status_bar,
            "Cache --",
            self.clear_cache
        )
        self.btn_cache.pack(side="left", padx=(0, 10))

    def _bind_events(self):
        """Привязка событий"""
        # Перемещение окна
        self.bind("<Button-1>", self.start_move)
        self.bind("<B1-Motion>", self.do_move)
        self.bind("<ButtonRelease-1>", self.stop_move)

        # Popup слайдера - используем три отдельных обработчика для умного управления
        self.scale.bind("<ButtonPress-1>", self.on_slider_press)
        self.scale.bind("<B1-Motion>", self.on_slider_motion)
        self.scale.bind("<ButtonRelease-1>", self.on_slider_release)

    def _sync_initial_state(self):
        """Синхронизация UI с настройками при запуске"""
        if cfg.get_bool("USER", "ShowSentenceWindow", True):
            self.sent_window.show()
        else:
            self.sent_window.withdraw()

    # ===== CACHE MANAGEMENT =====

    def update_cache_button(self):
        """Запускает параллельный подсчет размера кэша"""
        threading.Thread(
            target=self._worker_update_cache_size,
            daemon=True
        ).start()

    def _worker_update_cache_size(self):
        """Worker для подсчета размера кэша"""
        size_mb = get_cache_size_mb()

        if size_mb >= 1000:
            text = f"Cache {size_mb / 1024:.1f}G"
        else:
            text = f"Cache {size_mb:.1f}M"

        self.after(0, lambda: self.btn_cache.config(text=text))

    def clear_cache(self, event=None):
        """Очищает кэш и обновляет кнопку"""
        self.btn_cache.config(text="Clearing...")

        threading.Thread(
            target=self._worker_clear_cache,
            daemon=True
        ).start()

    def _worker_clear_cache(self):
        """Worker для удаления файлов кэша"""
        deleted_count = clear_cache()

        self.after(0, lambda: self.btn_cache.config(text=f"Cleared ({deleted_count})"))
        time.sleep(1)

        self.after(0, lambda: self.update_cache_button())

    # ===== SCROLLBAR LOGIC =====

    def _on_mousewheel(self, event):
        """Прокрутка колёсиком мыши"""
        self.canvas_scroll.yview_scroll(int(-1 * (event.delta / 120)), "units")
        return "break"  # КРИТИЧНО: Останавливаем всплытие события

    def _on_frame_configure(self, event):
        """Обновление scrollregion при изменении размера scrollable_frame"""
        self.canvas_scroll.configure(scrollregion=self.canvas_scroll.bbox("all"))

    # ===== TOOLTIP LOGIC =====

    def _bind_hover_translation(self, widget: tk.Widget, text: str):
        """Универсальный биндинг hover-перевода для любого виджета"""
        widget.bind("<Enter>", lambda e: self._on_text_enter(e, text))
        widget.bind("<Leave>", self._on_text_leave)

    def _on_text_enter(self, event, text: str):
        """Обработка наведения на текст"""
        if text in self.trans_cache:
            self.tooltip.show_text(self.trans_cache[text], event.x_root, event.y_root)
            return

        if self.hover_timer:
            self.after_cancel(self.hover_timer)
        self.hover_timer = self.after(
            self.HOVER_DELAY_MS,
            lambda: self._fetch_and_show_tooltip(text, event.x_root, event.y_root)
        )

    def _on_text_leave(self, event):
        """Обработка ухода курсора с текста"""
        if self.hover_timer:
            self.after_cancel(self.hover_timer)
            self.hover_timer = None
        self.tooltip.hide()

    def _fetch_and_show_tooltip(self, text: str, x: int, y: int):
        """Загрузка и отображение тултипа"""
        self.tooltip.show_loading(x, y)
        threading.Thread(
            target=self._worker_tooltip_trans,
            args=(text, x, y),
            daemon=True
        ).start()

    def _worker_tooltip_trans(self, text: str, x: int, y: int):
        """Worker для загрузки перевода"""
        trans = fetch_sentence_translation(text)
        if trans:
            # LRU cache: удаляем самый старый элемент при переполнении
            if len(self.trans_cache) >= self.MAX_TRANS_CACHE_SIZE:
                self.trans_cache.popitem(last=False)

            self.trans_cache[text] = trans
            self.after(0, lambda: self.tooltip.update_text(trans))

    # ===== SYNONYM LOGIC =====

    def on_synonym_click(self, word: str):
        """Обработка клика по синониму"""
        if self.search_callback:
            self.search_callback(word)

    def _on_synonym_enter(self, event, text: str, widget: tk.Label):
        """Hover эффект для синонима"""
        self._on_text_enter(event, text)
        widget.config(bg=COLORS["text_accent"], fg=COLORS["bg"])

    def _on_synonym_leave(self, event, widget: tk.Label):
        """Уход курсора с синонима"""
        self._on_text_leave(event)
        widget.config(bg=COLORS["bg_secondary"], fg=COLORS["text_main"])

    # ===== DATA DISPLAY =====

    def update_full_data_ui(self, full_data: Optional[Dict]):
        """
        Обновление UI полными данными словаря.

        Делегирует рендеринг DictRenderer.
        После отрисовки принудительно обновляет scrollbar.
        """
        # Рендеринг через DictRenderer
        if not full_data or not full_data.get("meanings"):
            self.dict_renderer.render(None)
        else:
            self.dict_renderer.render(full_data)

        # КРИТИЧНО: Показываем scrollbar ТОЛЬКО после полной загрузки данных
        self.after_idle(self.scrollbar.force_update)

    # ===== IMAGE HANDLER =====

    def update_img_ui(self, path: Optional[str], source: str):
        """Обновление изображения с компактным placeholder"""
        if path:
            try:
                pil_img = Image.open(path)

                max_width = self.winfo_width() - self.IMAGE_PADDING
                pil_img.thumbnail((max_width, self.IMAGE_MAX_HEIGHT), Image.Resampling.BILINEAR)

                tki = ImageTk.PhotoImage(pil_img)
                self.img_container.config(
                    image=tki,
                    text="",
                    compound="center",
                    bg=COLORS["bg"]
                )
                self.img_container.image = tki
                self.sources["img"] = source
            except Exception:
                self._show_no_image_placeholder()
        else:
            self._show_no_image_placeholder()

        self.refresh_status()

    def _show_no_image_placeholder(self):
        """Компактный текстовый placeholder"""
        self.img_container.config(
            image="",
            text="No image",
            compound="center",
            font=("Segoe UI", 9),
            fg=COLORS["text_faint"],
            bg=COLORS["bg"]
        )
        self.sources["img"] = "—"

    # ===== STATUS =====

    @property
    def status_text(self) -> str:
        """Генерирует текст статуса"""
        return f"Tr: {self.sources['trans']} • Img: {self.sources['img']}"

    def refresh_status(self):
        """Обновляет строку статуса"""
        self.lbl_status.config(text=self.status_text)

    def update_trans_ui(self, data: Optional[Dict], source: str):
        """Обновление перевода с fallback"""
        if data and data.get("rus"):
            self.lbl_rus.config(
                text=data["rus"],
                fg=COLORS["text_accent"]
            )
            self.sources["trans"] = source
        else:
            current_word = self.lbl_word.cget("text")
            if current_word and current_word != "English Helper":
                self.lbl_rus.config(
                    text=f"({current_word})",
                    fg=COLORS["text_faint"]
                )
            else:
                self.lbl_rus.config(
                    text="No translation",
                    fg=COLORS["text_faint"]
                )
            self.sources["trans"] = "—"
        self.refresh_status()

    def reset_ui(self, word: str):
        """
        Сброс UI для нового слова.

        КРИТИЧНО: Вызывается ПЕРВЫМ перед загрузкой любых данных.
        Немедленно блокирует scrollbar чтобы он не появлялся во время загрузки.
        """
        # ПЕРВЫМ ДЕЛОМ: Блокируем scrollbar и скрываем его
        self.scrollbar.block_updates()

        self.lbl_word.config(text=word)
        self.lbl_rus.config(
            text="Loading...",
            fg=COLORS["text_accent"]
        )
        self.img_container.config(
            image="",
            text="",
            bg=COLORS["bg"]
        )

        # Очистка через менеджер
        self.dict_renderer.clear()

        self.sources = {"trans": "...", "img": "..."}
        self.refresh_status()

        self.lbl_rus.config(wraplength=self.winfo_width() - 20)
        self.update_cache_button()

        # Сброс позиции скролла в начало
        self.canvas_scroll.yview_moveto(0)

    # ===== WINDOW CONTROLS =====

    def resize_window(self, dx: int, dy: int):
        """Изменение размера окна"""
        current_x = self.winfo_x()
        current_y = self.winfo_y()

        new_w = max(self.MIN_WINDOW_WIDTH, self.winfo_width() + dx)
        new_h = max(self.MIN_WINDOW_HEIGHT, self.winfo_height() + dy)

        self.geometry(f"{new_w}x{new_h}+{current_x}+{current_y}")
        self.lbl_rus.config(wraplength=new_w - 20)
        self.scrollable_frame.event_generate("<Configure>")

    def save_size(self):
        """Сохранение размера окна"""
        cfg.set("USER", "WindowWidth", self.winfo_width())
        cfg.set("USER", "WindowHeight", self.winfo_height())

    def toggle_sentence_window(self, event=None):
        """Переключение окна предложений с анимацией"""
        current = cfg.get_bool("USER", "ShowSentenceWindow", True)
        new_state = not current

        if new_state:
            # Показываем окно С АНИМАЦИЕЙ
            cfg.set("USER", "ShowSentenceWindow", True)
            self.sent_window.show_animated()
            self.btn_toggle_sent.sync_state()
        else:
            # Скрываем окно С АНИМАЦИЕЙ через close_window()
            # (close_window сам обновит конфиг и синхронизирует кнопку)
            self.sent_window.close_window()

    def toggle_auto_pronounce(self, event=None):
        """Переключение автопроизношения"""
        current = cfg.get_bool("USER", "AutoPronounce", True)
        new_state = not current
        cfg.set("USER", "AutoPronounce", new_state)

        # Синхронизация визуального состояния кнопки
        self.btn_toggle_pronounce.sync_state()

    # ===== VOCAB SLIDER =====

    def change_level(self, delta: int):
        """
        Изменение уровня словаря через стрелки.

        Обновляет popup если он открыт (но НЕ закрывает его).
        """
        new_val = self.vocab_var.get() + delta
        if 0 <= new_val <= 100:
            self.vocab_var.set(new_val)
            self.lbl_lvl_val.config(text=str(new_val))

            # Обновляем popup если он открыт (не закрываем)
            if self.popup and self.popup.winfo_viewable():
                self.popup.update_words(new_val)

            self.save_level()

    def save_level(self):
        """Сохранение уровня"""
        cfg.set("USER", "VocabLevel", self.vocab_var.get())

    def on_slider_press(self, event):
        """
        Обработка нажатия на ползунок слайдера.

        Логика:
        1. Запоминаем был ли popup открыт ДО этого клика
        2. Открываем popup с анимацией если закрыт
        3. Обновляем содержимое (т.к. значение слайдера изменилось при клике)
        """
        # ПЕРВЫМ ДЕЛОМ: Запоминаем состояние popup ДО любых действий
        self._popup_was_open_before_click = self.popup and self.popup.winfo_viewable()
        self._slider_was_moved = False
        self.dragging_allowed = False

        # Открываем popup с анимацией только если закрыт
        if not self._popup_was_open_before_click:
            x = self.winfo_x() + self.winfo_width() + 10
            y = self.winfo_y()
            self.popup.show_animated(x, y)

        # ВСЕГДА обновляем содержимое popup (значение слайдера изменилось при клике)
        self.after(10, self._update_popup_if_visible)

    def _update_popup_if_visible(self):
        """
        Обновляет popup если он открыт.

        Вызывается через after() для синхронизации с обновлением значения слайдера.
        Защищён проверкой winfo_viewable() на случай если popup был закрыт
        до выполнения отложенного вызова.
        """
        if self.popup and self.popup.winfo_viewable():
            self.popup.update_words(self.vocab_var.get())

    def on_slider_motion(self, event):
        """
        Обработка движения ползунка (drag).

        КРИТИЧНО: Устанавливает флаг что было движение, чтобы отличить
        простой клик от драга.
        """
        self._slider_was_moved = True

        # Обновляем label со значением
        self.lbl_lvl_val.config(text=str(self.vocab_var.get()))

        # Обновляем popup если открыт (debounced через update_words)
        if self.popup and self.popup.winfo_viewable():
            self.popup.update_words(self.vocab_var.get())

    def on_slider_release(self, event):
        """
        Обработка отпускания кнопки мыши после взаимодействия со слайдером.

        Логика закрытия popup:
        - Закрываем с анимацией ТОЛЬКО если popup был открыт ДО клика И не было движения
        """
        # Сохраняем уровень всегда
        self.save_level()

        # Закрываем popup с анимацией только если он был открыт ДО клика И не было движения
        if self._popup_was_open_before_click and not self._slider_was_moved:
            if self.popup and self.popup.winfo_viewable():
                self.popup.close_animated()

        # Сбрасываем флаги для следующего взаимодействия
        self._slider_was_moved = False
        self._popup_was_open_before_click = False

    # ===== WINDOW DRAGGING =====

    def start_move(self, event):
        """Начало перемещения окна"""
        widget = event.widget

        no_drag = (tk.Button, tk.Scale, tk.Scrollbar, tk.Entry)
        if isinstance(widget, no_drag) or widget == self.grip:
            return

        try:
            if widget.cget("cursor") == "hand2":
                return
        except:
            pass

        self.dragging_allowed = True
        self.x = event.x
        self.y = event.y

    def do_move(self, event):
        """Перемещение окна"""
        if not self.dragging_allowed:
            return

        new_x = self.winfo_x() + (event.x - self.x)
        new_y = self.winfo_y() + (event.y - self.y)
        self.geometry(f"+{new_x}+{new_y}")

    def stop_move(self, event):
        """Завершение перемещения"""
        if self.dragging_allowed:
            cfg.set("USER", "WindowX", self.winfo_x())
            cfg.set("USER", "WindowY", self.winfo_y())
        self.dragging_allowed = False

    def close_app(self):
        """Закрытие приложения"""
        # Уничтожаем popup если существует
        if hasattr(self, 'popup') and self.popup:
            self.popup.destroy()

        keyboard.unhook_all()
        self.destroy()
