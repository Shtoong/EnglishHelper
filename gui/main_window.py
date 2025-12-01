"""
GUI главного окна EnglishHelper.

Основные компоненты:
- MainWindow: безрамочное топмост окно с кастомным resize
- TranslationTooltip: всплывающие подсказки с hover-переводами
- ResizeGrip: виджет для изменения размера окна

Оптимизации v2.2:
- Sequence number для защиты от race conditions
- LRU cache для переводов (предотвращение утечки памяти)
- Token validation для tooltip (предотвращение "зависших" подсказок)
- FIX: Комплексное решение mousewheel с отменой tooltip timer
- FIX: Mousewheel forwarding через tooltip window
- FIX: Mousewheel на всех hover-виджетах и синонимах
- Debouncing для обновления статуса
- Кэширование content_width при render
"""

import tkinter as tk
from PIL import Image, ImageTk
import keyboard
import sys
import os
import threading
import time
from typing import Dict, List, Optional, Tuple, Callable
from collections import OrderedDict

# Graceful degradation: playsound может отсутствовать
try:
    from playsound import playsound
    PLAYSOUND_AVAILABLE = True
except ImportError:
    playsound = None
    PLAYSOUND_AVAILABLE = False

# Импорты config на уровне модуля (оптимизация workers)
from config import cfg, AUDIO_DIR, get_cache_size_mb, clear_cache
from gui.styles import COLORS, FONTS
from gui.popup import VocabPopup
from gui.sent_window import SentenceWindow
from network import fetch_sentence_translation, download_and_cache_audio, get_audio_cache_path


class LRUCache:
    """
    Простой LRU кэш с ограничением размера.

    Используется для trans_cache чтобы предотвратить утечку памяти
    при работе с большим количеством слов.
    """

    def __init__(self, max_size: int = 200):
        self.cache = OrderedDict()
        self.max_size = max_size

    def get(self, key: str) -> Optional[str]:
        """Получить значение и переместить в конец (most recently used)"""
        if key not in self.cache:
            return None
        self.cache.move_to_end(key)
        return self.cache[key]

    def set(self, key: str, value: str) -> None:
        """Установить значение и удалить старейший элемент если превышен лимит"""
        if key in self.cache:
            self.cache.move_to_end(key)
        self.cache[key] = value
        if len(self.cache) > self.max_size:
            self.cache.popitem(last=False)

    def __contains__(self, key: str) -> bool:
        return key in self.cache

    def clear(self) -> None:
        """Очистить весь кэш"""
        self.cache.clear()


class ResizeGrip(tk.Label):
    """
    Виджет для изменения размера окна.

    Использует экранные координаты (x_root/y_root) для корректной работы
    при перетаскивании через границы окна.
    """

    def __init__(self, parent, resize_callback: Callable, finish_callback: Callable, bg: str, fg: str):
        super().__init__(parent, text="◢", font=("Arial", 10), bg=bg, fg=fg, cursor="sizing")
        self.resize_callback = resize_callback
        self.finish_callback = finish_callback
        self.bind("<Button-1>", self._start_resize)
        self.bind("<B1-Motion>", self._do_resize)
        self.bind("<ButtonRelease-1>", self._stop_resize)
        self._x = 0
        self._y = 0

    def _start_resize(self, event) -> str:
        """Запоминаем начальную позицию в экранных координатах"""
        self._x = event.x_root
        self._y = event.y_root
        return "break"

    def _do_resize(self, event) -> str:
        """Изменяем размер на основе дельты в экранных координатах"""
        dx = event.x_root - self._x
        dy = event.y_root - self._y
        self.resize_callback(dx, dy)
        self._x = event.x_root
        self._y = event.y_root
        return "break"

    def _stop_resize(self, event) -> str:
        """Завершаем изменение размера и сохраняем"""
        self.finish_callback()
        return "break"


class TranslationTooltip:
    """
    Всплывающая подсказка с переводом и анимацией загрузки.

    Features:
    - Spinner анимация во время загрузки
    - Автоматическое позиционирование рядом с курсором
    - Thread-safe обновление из worker потоков
    - Token validation для предотвращения race conditions
    - FIX: Mousewheel forwarding для предотвращения зависаний скролла
    """

    def __init__(self, parent):
        self.parent = parent
        self.tip_window = None
        self.label = None
        self.animation_id = None
        self.spinner_chars = ["|", "/", "-", "\\"]

    def _create_window(self, x: int, y: int) -> None:
        """
        Создаёт топмост окно tooltip.

        FIX: Добавлен mousewheel forwarding для предотвращения
        перехвата событий скролла tooltip window.
        """
        if self.tip_window:
            return

        x += 15
        y += 15

        self.tip_window = tk.Toplevel(self.parent)
        self.tip_window.wm_overrideredirect(True)
        self.tip_window.wm_geometry(f"+{x}+{y}")
        self.tip_window.wm_attributes("-topmost", True)

        # FIX: Пробрасываем mousewheel через tooltip window к parent
        def forward_mousewheel(e):
            """
            Перенаправляет событие mousewheel в главное окно.
            Предотвращает зависание скролла когда tooltip перекрывает контент.
            """
            self.parent.event_generate("<MouseWheel>",
                                      delta=e.delta,
                                      x=e.x_root,
                                      y=e.y_root,
                                      when="now")
            return "break"

        self.tip_window.bind("<MouseWheel>", forward_mousewheel)

        frame = tk.Frame(
            self.tip_window,
            bg=COLORS["bg_secondary"],
            highlightbackground=COLORS["text_accent"],
            highlightthickness=1
        )
        frame.pack()

        # FIX: Bind на frame тоже
        frame.bind("<MouseWheel>", forward_mousewheel)

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

        # FIX: Bind на label тоже (полное покрытие)
        self.label.bind("<MouseWheel>", forward_mousewheel)

    def show_loading(self, x: int, y: int) -> None:
        """Показывает анимированный spinner загрузки"""
        self.hide()
        self._create_window(x, y)
        self._animate(0)

    def show_text(self, text: str, x: int, y: int) -> None:
        """Показывает готовый текст перевода"""
        self.hide()
        self._create_window(x, y)
        self.label.config(text=text)

    def update_text(self, text: str) -> None:
        """Обновляет текст существующего tooltip (thread-safe)"""
        if self.tip_window and self.label:
            self._stop_animation()
            self.label.config(text=text)

    def _animate(self, step: int) -> None:
        """
        Рекурсивная анимация spinner.

        FIX: Добавлена проверка существования tip_window в начале
        для предотвращения memory leak при быстрых hover событиях.
        """
        if not self.tip_window:
            return

        char = self.spinner_chars[step % len(self.spinner_chars)]
        self.label.config(text=f"{char} Translating...")
        self.animation_id = self.parent.after(100, lambda: self._animate(step + 1))

    def _stop_animation(self) -> None:
        """Останавливает анимацию и отменяет scheduled callbacks"""
        if self.animation_id:
            self.parent.after_cancel(self.animation_id)
            self.animation_id = None

    def hide(self) -> None:
        """Скрывает tooltip и очищает ресурсы"""
        self._stop_animation()
        if self.tip_window:
            self.tip_window.destroy()
            self.tip_window = None
            self.label = None


class MainWindow(tk.Tk):
    """
    Главное окно приложения EnglishHelper.

    Архитектура:
    - Безрамочное окно с topmost
    - Кастомный resize grip
    - Прокручиваемый контент с автоматическим scrollbar
    - Параллельные worker потоки для I/O операций
    - Hover-переводы с кэшированием (LRU)
    - Защита от race conditions через sequence numbers
    - FIX: Комплексное решение проблем mousewheel
    """

    # ===== UI КОНСТАНТЫ =====
    IMAGE_MAX_HEIGHT = 250
    IMAGE_PADDING = 40
    CONTENT_PADDING = 60
    DEFAULT_WRAPLENGTH = 380
    TRANSLATION_PADDING = 20
    MAX_SYNONYMS = 5
    HOVER_DELAY_MS = 300
    MIN_WINDOW_WIDTH = 300
    MIN_WINDOW_HEIGHT = 400
    TRANS_CACHE_SIZE = 200  # Максимальный размер LRU кэша переводов

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

        # Состояние UI
        self.sources = {"trans": "wait", "img": "wait"}
        self.dragging_allowed = False
        self.popup = None
        self.current_audio_urls = [None, None]
        self.hover_timer = None
        self.search_callback = None

        # LRU кэш для переводов (предотвращает утечку памяти)
        self.trans_cache = LRUCache(max_size=self.TRANS_CACHE_SIZE)

        # Thread-safe флаг для cache update
        self._cache_update_lock = threading.Lock()

        # Sequence number для защиты от race conditions
        self._current_word_seq = 0
        self._word_seq_lock = threading.Lock()

        # Token для tooltip validation (предотвращает "зависшие" tooltips)
        self._tooltip_token = 0

        # Debouncing для статуса (оптимизация)
        self._status_update_pending = False

        # Создание виджетов
        self.sent_window = SentenceWindow(self)
        self.tooltip = TranslationTooltip(self)

        self._init_ui()
        self._bind_events()
        self._sync_initial_state()
        self.update_cache_button()

    @property
    def content_width(self) -> int:
        """Ширина области контента с учетом padding"""
        return self.winfo_width() - self.CONTENT_PADDING

    def _init_ui(self) -> None:
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

        # КРИТИЧНО: bottom_frame создаётся ДО scrollable_content
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

    def _create_top_bar(self) -> None:
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

    def _create_word_header(self) -> None:
        """Заголовок слова с фонетикой и аудио"""
        self.lbl_word = self._create_label(
            self,
            text="English Helper",
            font_key="header",
            fg_key="text_header"
        )
        self.lbl_word.pack(pady=(10, 5), anchor="center")

        # Фрейм с фонетикой и кнопками аудио
        phonetic_frame = tk.Frame(self, bg=COLORS["bg"])
        phonetic_frame.pack(anchor="center", pady=5)

        self.lbl_phonetic = self._create_label(
            phonetic_frame,
            font_key="phonetic",
            fg_key="text_phonetic"
        )
        self.lbl_phonetic.pack(side="left", padx=5)

        self.btn_audio_us = self._create_audio_button(phonetic_frame, "🔊 US", 0)
        self.btn_audio_uk = self._create_audio_button(phonetic_frame, "🔊 UK", 1)

    def _create_audio_button(self, parent, text: str, index: int) -> tk.Label:
        """Создает кнопку воспроизведения аудио"""
        btn = tk.Label(
            parent,
            text=text,
            font=FONTS["audio_btn"],
            bg=COLORS["button_bg"],
            fg=COLORS["text_main"],
            cursor="hand2",
            padx=5,
            pady=2
        )
        btn.pack(side="left", padx=2)
        btn.bind("<Button-1>", lambda e: self.play_audio(index))
        return btn

    def _create_translation_display(self) -> None:
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

    def _create_image_container(self) -> None:
        """Контейнер для изображения"""
        self.img_container = tk.Label(
            self,
            bg=COLORS["bg"]
        )
        self.img_container.pack(pady=5)

    def _create_separator(self) -> None:
        """Горизонтальный разделитель"""
        tk.Frame(
            self,
            height=1,
            bg=COLORS["separator"],
            width=360
        ).pack(pady=5)

    def _create_scrollable_content(self) -> None:
        """
        Прокручиваемая область с определениями.

        КРИТИЧНО: Этот метод вызывается ПОСЛЕ _create_vocab_slider() и _create_status_bar(),
        чтобы scrollable content занял только оставшееся пространство между верхними
        элементами и нижним фреймом (который уже запакован с side="bottom").

        FIX: Mousewheel binding на трёх уровнях для 100% покрытия:
        1. scroll_container - работает над пустыми областями контейнера
        2. canvas_scroll - работает над scrollbar и canvas
        3. scrollable_frame - работает над всем контентом (Label, Frame, etc)
        """
        scroll_container = tk.Frame(self, bg=COLORS["bg"])
        scroll_container.pack(fill="both", expand=True, padx=10, pady=5)

        self.canvas_scroll = tk.Canvas(
            scroll_container,
            bg=COLORS["bg"],
            highlightthickness=0
        )
        self.scrollbar = tk.Scrollbar(
            scroll_container,
            orient="vertical",
            command=self.canvas_scroll.yview
        )
        self.scrollable_frame = tk.Frame(self.canvas_scroll, bg=COLORS["bg"])

        self.scrollable_frame.bind("<Configure>", self._on_frame_configure)
        self.canvas_scroll.bind("<Configure>", self._on_canvas_configure)

        self.canvas_scroll.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas_scroll.configure(yscrollcommand=self.scrollbar.set)
        self.canvas_scroll.pack(side="left", fill="both", expand=True)

        # FIX: Трёхуровневый bind для mousewheel (оптимальное решение)
        # Уровень 1: Контейнер (работает над пустыми областями)
        scroll_container.bind("<MouseWheel>", self._on_mousewheel)

        # Уровень 2: Canvas (работает над scrollbar и canvas)
        self.canvas_scroll.bind("<MouseWheel>", self._on_mousewheel)

        # Уровень 3: Scrollable frame (работает над всем контентом)
        self.scrollable_frame.bind("<MouseWheel>", self._on_mousewheel)

    def _create_vocab_slider(self) -> None:
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

    def _create_status_bar(self) -> None:
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
        self.btn_toggle_sent = self._create_toggle_button(
            status_bar,
            "Sentence",
            self.toggle_sentence_window,
            "ShowSentenceWindow"
        )
        self.btn_toggle_sent.pack(side="left", padx=(10, 5))

        self.btn_toggle_pronounce = self._create_toggle_button(
            status_bar,
            "Pronunciation",
            self.toggle_auto_pronounce,
            "AutoPronounce"
        )
        self.btn_toggle_pronounce.pack(side="left", padx=(0, 5))

        # Кнопка очистки кэша
        self.btn_cache = self._create_toggle_button(
            status_bar,
            "Cache --",
            self.clear_cache,
            None
        )
        self.btn_cache.pack(side="left", padx=(0, 10))

    def _create_toggle_button(self, parent, text: str, command: Callable,
                              config_key: Optional[str]) -> tk.Label:
        """Создает кнопку-переключатель с hover эффектом"""
        btn = tk.Label(
            parent,
            text=text,
            font=("Segoe UI", 8),
            bg=COLORS["bg_secondary"],
            fg=COLORS["text_main"],
            cursor="hand2",
            padx=8,
            pady=3,
            relief="flat"
        )
        btn.bind("<Button-1>", command)

        # Hover эффект
        def on_enter(e):
            btn.config(bg=COLORS["text_accent"], fg=COLORS["bg"])

        def on_leave(e):
            if config_key:
                self._update_toggle_button_style(btn, config_key)
            else:
                btn.config(bg=COLORS["bg_secondary"], fg=COLORS["text_main"])

        btn.bind("<Enter>", on_enter)
        btn.bind("<Leave>", on_leave)

        # Установить начальный стиль
        if config_key:
            self._update_toggle_button_style(btn, config_key)
        else:
            btn.config(bg=COLORS["bg_secondary"], fg=COLORS["text_main"])

        return btn

    def _update_toggle_button_style(self, button: tk.Label, config_key: str) -> None:
        """Обновляет стиль кнопки-переключателя"""
        is_enabled = cfg.get_bool("USER", config_key, True)
        button.config(
            bg=COLORS["text_accent"] if is_enabled else COLORS["bg_secondary"],
            fg=COLORS["bg"] if is_enabled else COLORS["text_faint"]
        )

    def _bind_events(self) -> None:
        """Привязка событий"""
        # Перемещение окна
        self.bind("<Button-1>", self.start_move)
        self.bind("<B1-Motion>", self.do_move)
        self.bind("<ButtonRelease-1>", self.stop_move)

        # Popup слайдера
        self.scale.bind("<ButtonPress-1>", self.show_popup)
        self.scale.bind("<B1-Motion>", self.move_popup)
        self.scale.bind("<ButtonRelease-1>", self.hide_popup_and_save)

    def _sync_initial_state(self) -> None:
        """Синхронизация UI с настройками при запуске"""
        if cfg.get_bool("USER", "ShowSentenceWindow", True):
            self.sent_window.deiconify()
        else:
            self.sent_window.withdraw()

    # ===== SEQUENCE NUMBER MANAGEMENT =====

    def _get_next_word_seq(self) -> int:
        """
        Получить следующий sequence number для нового слова.

        Thread-safe инкремент для защиты от race conditions.
        """
        with self._word_seq_lock:
            self._current_word_seq += 1
            return self._current_word_seq

    def _is_current_word(self, seq: int) -> bool:
        """Проверить актуальность sequence number"""
        return seq == self._current_word_seq

    # ===== CACHE MANAGEMENT =====

    def update_cache_button(self) -> None:
        """
        Запускает параллельный подсчет размера кэша.

        Thread-safe через Lock.
        """
        with self._cache_update_lock:
            threading.Thread(
                target=self._worker_update_cache_size,
                daemon=True
            ).start()

    def _worker_update_cache_size(self) -> None:
        """Worker для подсчета размера кэша"""
        size_mb = get_cache_size_mb()

        if size_mb >= 1000:
            text = f"Cache {size_mb / 1024:.1f}G"
        else:
            text = f"Cache {size_mb:.1f}M"

        self.after(0, lambda: self.btn_cache.config(text=text))

    def clear_cache(self, event=None) -> None:
        """Очищает кэш и обновляет кнопку"""
        self.btn_cache.config(text="Clearing...")

        threading.Thread(
            target=self._worker_clear_cache,
            daemon=True
        ).start()

    def _worker_clear_cache(self) -> None:
        """Worker для удаления файлов кэша"""
        deleted_count = clear_cache()

        self.after(0, lambda: self.btn_cache.config(text=f"Cleared ({deleted_count})"))
        time.sleep(1)

        self.after(0, lambda: self.update_cache_button())

    # ===== SCROLLBAR LOGIC =====

    def _on_mousewheel(self, event) -> str:
        """
        Обработка скролла колесом мыши.

        FIX v2.2: Комплексная защита от зависания:
        1. Отменяем tooltip timer (предотвращает блокировку после 300ms)
        2. Скрываем tooltip если открыт (освобождаем focus)
        3. Принудительно обновляем scroll region (гарантируем актуальность bbox)
        4. Проверяем boundary limits (не скроллим за пределы)
        5. Блокируем event propagation (один вызов вместо трёх)
        """
        # FIX 1: Отменяем tooltip timer при скролле
        # КРИТИЧНО: Tooltip timer блокирует события через 300ms после hover
        if self.hover_timer:
            self.after_cancel(self.hover_timer)
            self.hover_timer = None

        # FIX 2: Скрываем tooltip если открыт
        # КРИТИЧНО: Tooltip window может перехватывать focus и блокировать события
        self.tooltip.hide()

        # FIX 3: Принудительное обновление scroll region
        # Гарантирует что bbox("all") актуален после render новых виджетов
        self.canvas_scroll.configure(scrollregion=self.canvas_scroll.bbox("all"))

        # FIX 4: Проверяем boundary limits
        current_view = self.canvas_scroll.yview()
        delta = int(-1 * (event.delta / 120))

        # Блокируем скролл за пределы контента
        if delta < 0 and current_view[0] <= 0.0:
            return "break"  # Уже в начале, не скроллим вверх
        if delta > 0 and current_view[1] >= 1.0:
            return "break"  # Уже в конце, не скроллим вниз

        # Выполняем скролл
        self.canvas_scroll.yview_scroll(delta, "units")

        # FIX 5: Блокируем event propagation
        # Предотвращает множественные вызовы от трёх bind
        return "break"

    def _on_frame_configure(self, event) -> None:
        """Обновление scroll region при изменении контента"""
        self.canvas_scroll.configure(scrollregion=self.canvas_scroll.bbox("all"))
        self._check_scroll_needed()

    def _on_canvas_configure(self, event) -> None:
        """Обновление scrollbar при изменении размера canvas"""
        self._check_scroll_needed()

    def _check_scroll_needed(self) -> None:
        """Показывает/скрывает scrollbar при необходимости"""
        bbox = self.canvas_scroll.bbox("all")
        if bbox and bbox[3] > self.canvas_scroll.winfo_height():
            self.scrollbar.pack(side="right", fill="y")
        else:
            self.scrollbar.pack_forget()

    # ===== TOOLTIP LOGIC =====

    def _bind_hover_translation(self, widget: tk.Widget, text: str) -> None:
        """
        Универсальный биндинг hover-перевода для любого виджета.

        FIX: Добавлен mousewheel binding для предотвращения зависаний.
        КРИТИЧНО: Label с hover binding должен пробрасывать mousewheel,
        иначе скролл не работает когда курсор над текстом.
        """
        widget.bind("<Enter>", lambda e: self._on_text_enter(e, text))
        widget.bind("<Leave>", self._on_text_leave)

        # FIX: КРИТИЧНО! Пробрасываем mousewheel через виджет
        widget.bind("<MouseWheel>", self._on_mousewheel)

    def _on_text_enter(self, event, text: str) -> None:
        """Обработка наведения на текст"""
        # Проверяем LRU кэш
        cached_trans = self.trans_cache.get(text)
        if cached_trans:
            self.tooltip.show_text(cached_trans, event.x_root, event.y_root)
            return

        if self.hover_timer:
            self.after_cancel(self.hover_timer)

        # Инкрементируем token для новой tooltip операции
        self._tooltip_token += 1
        current_token = self._tooltip_token

        self.hover_timer = self.after(
            self.HOVER_DELAY_MS,
            lambda: self._fetch_and_show_tooltip(text, event.x_root, event.y_root, current_token)
        )

    def _on_text_leave(self, event) -> None:
        """Обработка ухода курсора с текста"""
        if self.hover_timer:
            self.after_cancel(self.hover_timer)
            self.hover_timer = None
        self.tooltip.hide()

    def _fetch_and_show_tooltip(self, text: str, x: int, y: int, token: int) -> None:
        """Загрузка и отображение тултипа с token validation"""
        self.tooltip.show_loading(x, y)
        threading.Thread(
            target=self._worker_tooltip_trans,
            args=(text, x, y, token),
            daemon=True
        ).start()

    def _worker_tooltip_trans(self, text: str, x: int, y: int, token: int) -> None:
        """
        Worker для загрузки перевода.

        FIX: Добавлен token validation для предотвращения race conditions.
        """
        trans = fetch_sentence_translation(text)

        # Проверяем актуальность token перед обновлением UI
        if trans and token == self._tooltip_token:
            self.trans_cache.set(text, trans)
            self.after(0, lambda: self.tooltip.update_text(trans))

    # ===== SYNONYM LOGIC =====

    def on_synonym_click(self, word: str) -> None:
        """Обработка клика по синониму"""
        if self.search_callback:
            self.search_callback(word)

    def _on_synonym_enter(self, event, text: str, widget: tk.Label) -> None:
        """Hover эффект для синонима"""
        self._on_text_enter(event, text)
        widget.config(bg=COLORS["text_accent"], fg=COLORS["bg"])

    def _on_synonym_leave(self, event, widget: tk.Label) -> None:
        """Уход курсора с синонима"""
        self._on_text_leave(event)
        widget.config(bg=COLORS["bg_secondary"], fg=COLORS["text_main"])

    # ===== DATA DISPLAY =====

    def update_full_data_ui(self, full_data: Optional[Dict], seq: int) -> None:
        """
        Обновление UI полными данными словаря.

        FIX: Добавлена проверка sequence number для защиты от race conditions.
        """
        # Игнорируем устаревшие данные
        if not self._is_current_word(seq):
            return

        # Очистка
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()
        self.current_audio_urls = [None, None]

        # Проверка наличия meanings
        if not full_data or not full_data.get("meanings"):
            self._create_label(
                self.scrollable_frame,
                text="No detailed data available",
                fg_key="text_faint"
            ).pack(pady=10)
            self.lbl_phonetic.config(text="")

            # Скрываем кнопки аудио
            self.btn_audio_us.config(fg=COLORS["text_faint"])
            self.btn_audio_uk.config(fg=COLORS["text_faint"])
            return

        # Обработка фонетики и аудио
        self._process_phonetics(full_data.get("phonetics", []))

        # Кэшируем content_width для оптимизации (избегаем множественных winfo_width())
        current_content_width = self.content_width

        # Отображение meanings
        self._render_meanings(full_data.get("meanings", []), current_content_width)

    def _process_phonetics(self, phonetics: List[Dict]) -> None:
        """Обработка фонетической информации"""
        if not phonetics:
            self.lbl_phonetic.config(text="")
            self.btn_audio_us.config(fg=COLORS["text_faint"])
            self.btn_audio_uk.config(fg=COLORS["text_faint"])
            return

        # Извлекаем текст фонетики
        p_text = next((p["text"] for p in phonetics if p.get("text")), "")
        self.lbl_phonetic.config(text=p_text)

        # Извлекаем URL аудио
        us_url, uk_url = self._extract_audio_urls(phonetics)
        self.current_audio_urls = [us_url, uk_url]

        # Обновляем состояние кнопок
        self.btn_audio_us.config(
            fg=COLORS["text_main"] if us_url else COLORS["text_faint"]
        )
        self.btn_audio_uk.config(
            fg=COLORS["text_main"] if uk_url else COLORS["text_faint"]
        )

    def _extract_audio_urls(self, phonetics: List[Dict]) -> Tuple[Optional[str], Optional[str]]:
        """Извлекает US и UK аудио URL с приоритетом"""
        us = next(
            (p["audio"] for p in phonetics if "-us.mp3" in p.get("audio", "").lower() or "en-US" in p.get("audio", "")),
            None)
        uk = next(
            (p["audio"] for p in phonetics if "-uk.mp3" in p.get("audio", "").lower() or "en-GB" in p.get("audio", "")),
            None)

        if not us or not uk:
            available = [p["audio"] for p in phonetics if p.get("audio")]
            us = us or (available[0] if len(available) > 0 else None)
            uk = uk or (available[1] if len(available) > 1 else None)

        return us, uk

    def _render_meanings(self, meanings: List[Dict], content_width: int) -> None:
        """
        Отрисовка meanings (части речи, определения, примеры, синонимы).

        FIX: content_width передаётся как аргумент для оптимизации.
        """
        for meaning in meanings:
            # Часть речи
            pos = meaning.get("partOfSpeech", "")
            self._create_label(
                self.scrollable_frame,
                text=pos,
                font_key="pos",
                fg_key="text_pos",
                anchor="w"
            ).pack(fill="x", pady=(10, 5))

            # Определения и примеры
            self._render_definitions(meaning.get("definitions", []), content_width)

            # Синонимы
            self._render_synonyms(meaning.get("synonyms", []))

            # Разделитель
            tk.Frame(
                self.scrollable_frame,
                height=1,
                bg=COLORS["separator"],
                width=360
            ).pack(pady=5)

    def _render_definitions(self, definitions: List[Dict], content_width: int) -> None:
        """
        Отрисовка определений и примеров.

        FIX: content_width передаётся как аргумент для оптимизации.
        """
        for i, defn in enumerate(definitions, 1):
            # Определение
            def_text = f"{i}. {defn.get('definition', '')}"
            lbl_def = self._create_label(
                self.scrollable_frame,
                text=def_text,
                wraplength=content_width,
                justify="left",
                anchor="w"
            )
            lbl_def.pack(fill="x", padx=10, pady=2)
            self._bind_hover_translation(lbl_def, defn.get('definition', ''))

            # Пример
            if defn.get("example"):
                ex_text = f'   "{defn["example"]}"'
                lbl_ex = self._create_label(
                    self.scrollable_frame,
                    text=ex_text,
                    font_key="example",
                    fg_key="text_accent",
                    wraplength=content_width,
                    justify="left",
                    anchor="w"
                )
                lbl_ex.pack(fill="x", padx=10, pady=(0, 5))
                self._bind_hover_translation(lbl_ex, defn.get("example", ""))

    def _render_synonyms(self, synonyms: List[str]) -> None:
        """
        Отрисовка синонимов в виде тегов.

        FIX: Добавлен mousewheel binding на syn_frame и каждый synonym tag
        для предотвращения зависаний при скролле над синонимами.
        """
        if not synonyms:
            return

        syn_frame = tk.Frame(self.scrollable_frame, bg=COLORS["bg"])
        syn_frame.pack(fill="x", padx=10, pady=(5, 10))

        # FIX: КРИТИЧНО! Mousewheel на syn_frame
        syn_frame.bind("<MouseWheel>", self._on_mousewheel)

        tk.Label(
            syn_frame,
            text="Syn:",
            font=FONTS["synonym_label"],
            bg=COLORS["bg"],
            fg=COLORS["text_faint"]
        ).pack(side="left", anchor="n")

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

            tag.bind(
                "<Enter>",
                lambda e, t=syn, w=tag: self._on_synonym_enter(e, t, w)
            )
            tag.bind(
                "<Leave>",
                lambda e, w=tag: self._on_synonym_leave(e, w)
            )
            tag.bind(
                "<Button-1>",
                lambda e, w=syn: self.on_synonym_click(w)
            )

            # FIX: КРИТИЧНО! Mousewheel на каждом synonym tag
            # Без этого скролл не работает когда курсор над синонимом
            tag.bind("<MouseWheel>", self._on_mousewheel)

    # ===== AUDIO PLAYER =====

    def play_audio(self, index: int) -> None:
        """Воспроизведение аудио по индексу (0=US, 1=UK)"""
        if not PLAYSOUND_AVAILABLE:
            return

        if index < len(self.current_audio_urls):
            url = self.current_audio_urls[index]
            if not url:
                return
            threading.Thread(
                target=self._play_audio_worker,
                args=(url,),
                daemon=True
            ).start()

    def _play_audio_worker(self, url: str) -> None:
        """Worker для загрузки и воспроизведения аудио (для кнопок US/UK)"""
        if not PLAYSOUND_AVAILABLE or playsound is None:
            return

        try:
            if "translate.google.com" in url:
                from urllib.parse import parse_qs, urlparse
                parsed = urlparse(url)
                params = parse_qs(parsed.query)
                word = params.get('q', [''])[0]
                accent = "us" if "en-US" in url else "uk"
                cache_path = get_audio_cache_path(word, accent)
            else:
                filename = url.split("/")[-1] or f"audio_{abs(hash(url))}.mp3"
                if not filename.endswith(".mp3"):
                    filename += ".mp3"
                cache_path = os.path.join(AUDIO_DIR, filename)

            if not os.path.exists(cache_path):
                download_and_cache_audio(url, cache_path)

            if os.path.exists(cache_path):
                playsound(cache_path)
        except (IOError, OSError, ValueError, KeyError):
            # Известные ошибки — молча игнорируем (graceful degradation)
            pass

    # ===== IMAGE HANDLER =====

    def update_img_ui(self, path: Optional[str], source: str, seq: int) -> None:
        """
        Обновление изображения с компактным placeholder.

        FIX: Добавлена проверка sequence number для защиты от race conditions.
        """
        # Игнорируем устаревшие данные
        if not self._is_current_word(seq):
            return

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
            except (IOError, OSError):
                self._show_no_image_placeholder()
        else:
            self._show_no_image_placeholder()

        self._schedule_status_update()

    def _show_no_image_placeholder(self) -> None:
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

    def _schedule_status_update(self) -> None:
        """
        Планирует обновление статуса через after_idle (debouncing).

        FIX: Предотвращает множественные обновления при одновременной
        загрузке перевода и изображения.
        """
        if self._status_update_pending:
            return
        self._status_update_pending = True
        self.after_idle(self._do_status_update)

    def _do_status_update(self) -> None:
        """Выполняет отложенное обновление статуса"""
        self.refresh_status()
        self._status_update_pending = False

    def refresh_status(self) -> None:
        """Обновляет строку статуса"""
        status_text = f"Tr: {self.sources['trans']} • Img: {self.sources['img']}"
        self.lbl_status.config(text=status_text)

    def update_trans_ui(self, data: Optional[Dict], source: str, seq: int) -> None:
        """
        Обновление перевода с fallback.

        FIX: Добавлена проверка sequence number для защиты от race conditions.
        """
        # Игнорируем устаревшие данные
        if not self._is_current_word(seq):
            return

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

        self._schedule_status_update()

    def reset_ui(self, word: str) -> int:
        """
        Сброс UI для нового слова.

        FIX: Возвращает sequence number для передачи в workers.

        Returns:
            Sequence number для текущего слова
        """
        # Получаем новый sequence number
        seq = self._get_next_word_seq()

        self.lbl_word.config(text=word)
        self.lbl_phonetic.config(text="")
        self.lbl_rus.config(
            text="Loading...",
            fg=COLORS["text_accent"]
        )
        self.img_container.config(
            image="",
            text="",
            bg=COLORS["bg"]
        )
        self.current_audio_urls = [None, None]

        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()

        self.sources = {"trans": "...", "img": "..."}
        self.refresh_status()

        self.lbl_rus.config(wraplength=self.winfo_width() - self.TRANSLATION_PADDING)
        self.update_cache_button()

        return seq

    # ===== WINDOW CONTROLS =====

    def resize_window(self, dx: int, dy: int) -> None:
        """Изменение размера окна"""
        current_x = self.winfo_x()
        current_y = self.winfo_y()

        new_w = max(self.MIN_WINDOW_WIDTH, self.winfo_width() + dx)
        new_h = max(self.MIN_WINDOW_HEIGHT, self.winfo_height() + dy)

        self.geometry(f"{new_w}x{new_h}+{current_x}+{current_y}")

        self.lbl_rus.config(wraplength=new_w - self.TRANSLATION_PADDING)
        self.scrollable_frame.event_generate("<Configure>")

    def save_size(self) -> None:
        """Сохранение размера окна"""
        cfg.set("USER", "WindowWidth", self.winfo_width())
        cfg.set("USER", "WindowHeight", self.winfo_height())

    def _toggle_setting(self, config_key: str, button: tk.Label,
                        on_enable: Optional[Callable] = None,
                        on_disable: Optional[Callable] = None) -> None:
        """Универсальный toggle для любой настройки"""
        current = cfg.get_bool("USER", config_key, True)
        new_state = not current
        cfg.set("USER", config_key, new_state)

        if new_state and on_enable:
            on_enable()
        elif not new_state and on_disable:
            on_disable()

        self._update_toggle_button_style(button, config_key)

    def toggle_sentence_window(self, event=None) -> None:
        """Переключение окна предложений"""
        current = cfg.get_bool("USER", "ShowSentenceWindow", True)
        new_state = not current
        cfg.set("USER", "ShowSentenceWindow", new_state)

        if new_state:
            self.sent_window.deiconify()
        else:
            self.sent_window.withdraw()

        self._update_toggle_button_style(self.btn_toggle_sent, "ShowSentenceWindow")

    def toggle_auto_pronounce(self, event=None) -> None:
        """Переключение автопроизношения"""
        self._toggle_setting("AutoPronounce", self.btn_toggle_pronounce)

    # ===== VOCAB SLIDER =====

    def change_level(self, delta: int) -> None:
        """Изменение уровня словаря"""
        new_val = self.vocab_var.get() + delta
        if 0 <= new_val <= 100:
            self.vocab_var.set(new_val)
            self.lbl_lvl_val.config(text=str(new_val))
            self.save_level()

    def save_level(self) -> None:
        """Сохранение уровня"""
        cfg.set("USER", "VocabLevel", self.vocab_var.get())

    def show_popup(self, event) -> None:
        """Показать popup с ignored words"""
        self.dragging_allowed = False
        if not self.popup:
            self.popup = VocabPopup(self)

        # Позиционируем справа от главного окна
        x = self.winfo_x() + self.winfo_width() + 10
        y = self.winfo_y()

        self.popup.show(x, y)
        self.update_popup_content()

    def move_popup(self, event) -> None:
        """Обновление popup при движении слайдера"""
        self.lbl_lvl_val.config(text=str(self.vocab_var.get()))
        self.update_popup_content()

    def update_popup_content(self) -> None:
        """Обновление содержимого popup"""
        if self.popup:
            self.popup.update_words(self.vocab_var.get())

    def hide_popup_and_save(self, event) -> None:
        """Скрытие popup и сохранение"""
        if self.popup:
            self.popup.destroy()
            self.popup = None
        self.save_level()

    # ===== WINDOW DRAGGING =====

    def start_move(self, event) -> None:
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

    def do_move(self, event) -> None:
        """Перемещение окна"""
        if not self.dragging_allowed:
            return

        new_x = self.winfo_x() + (event.x - self.x)
        new_y = self.winfo_y() + (event.y - self.y)
        self.geometry(f"+{new_x}+{new_y}")

    def stop_move(self, event) -> None:
        """Завершение перемещения"""
        if self.dragging_allowed:
            cfg.set("USER", "WindowX", self.winfo_x())
            cfg.set("USER", "WindowY", self.winfo_y())
        self.dragging_allowed = False

    def close_app(self) -> None:
        """Закрытие приложения"""
        keyboard.unhook_all()
        self.destroy()
        sys.exit(0)
