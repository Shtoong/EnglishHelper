"""
Главное окно приложения EnglishHelper.

Отображает:
- Заголовок слова
- Перевод на русский
- Изображение ассоциации (фиксированная высота 20% окна)
- Прокручиваемый список определений и примеров
- Слайдер уровня словаря с popup превью
- Статус бар с кнопками управления

Architecture:
- Координирует работу компонентов (DictRenderer)
- Управляет layout и window state
- Обрабатывает callbacks из main.pyw
"""

import tkinter as tk
from PIL import Image, ImageTk, ImageDraw, ImageFont
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
    # 📍 НАСТРОЙКА КАРТИНКИ (меняй здесь в будущем):
    IMAGE_CONTAINER_HEIGHT_PERCENT = 0.20  # % от высоты окна
    IMAGE_CONTAINER_PADDING_X = 5  # Отступ слева/справа
    IMAGE_CONTAINER_PADDING_Y = 0   # Отступ сверху/снизу

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
        self.trans_cache = OrderedDict()
        self.hover_timer = None

        # Текущее слово (для защиты от устаревших обновлений)
        self.current_word = None
        self.current_image_word = None

        # Флаги для умного управления popup слайдера
        self._slider_was_moved = False
        self._popup_was_open_before_click = False

        # Callbacks устанавливаются из main.pyw
        self.search_callback = None
        self.clipboard_callback = None

        # ===== СОЗДАНИЕ КОМПОНЕНТОВ =====
        self.sent_window = SentenceWindow(self)
        self.tooltip = TranslationTooltip(self)
        self.popup = VocabPopup(self)

        # Инициализация UI (создаёт все виджеты)
        self._init_ui()

        # ===== СОЗДАНИЕ МЕНЕДЖЕРОВ =====
        self.dict_renderer = DictionaryRenderer(
            self.scrollable_frame,
            lambda: self.content_width,
            self._bind_hover_translation,
            self.on_synonym_click,
            self._on_synonym_enter,
            self._on_synonym_leave,
            self.canvas_scroll,
            self
        )

        # Финальная настройка
        self._bind_events()
        self._sync_initial_state()
        self.update_cache_button()

    @property
    def content_width(self) -> int:
        """Ширина области контента с учетом padding"""
        return self.winfo_width() - self.CONTENT_PADDING

    def _calculate_translation_font_size(self, text: str) -> int:
        """
        Подбирает размер шрифта чтобы текст влез в фиксированную высоту.

        Args:
            text: Текст перевода

        Returns:
            Размер шрифта (int) от MIN до MAX
        """
        from gui.styles import TRANSLATION_HEIGHT, TRANSLATION_MIN_FONT, TRANSLATION_MAX_FONT

        max_width = self.content_width

        # Пробуем размеры от максимального к минимальному (шаг -3)
        for size in range(TRANSLATION_MAX_FONT, TRANSLATION_MIN_FONT - 1, -3):
            # Временный Label для измерения (скрыт за экраном)
            temp_label = tk.Label(
                self,
                text=text,
                font=("Segoe UI", size),
                wraplength=max_width,
                justify='center',
                bg=COLORS["bg"]
            )
            # КРИТИЧНО: НЕ используем pack()! place() за границами экрана:
            temp_label.place(x=-9999, y=-9999)
            temp_label.update_idletasks()

            actual_height = temp_label.winfo_reqheight()
            temp_label.destroy()

            if actual_height <= TRANSLATION_HEIGHT:
                return size

        return TRANSLATION_MIN_FONT

    def _init_ui(self):
        """
        Инициализация всех UI элементов.

        КРИТИЧНО: Порядок создания элементов важен для правильного layout:
        1. Верхние элементы (top bar, translation, image)
        2. BOTTOM FRAME (слайдер + кнопки) - создаётся РАНЬШЕ scrollable content
        3. Scrollable content - заполняет оставшееся пространство
        """
        self._create_top_bar()
        self._create_translation_display()
        self._create_image_container()

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

    def _create_top_bar(self):
        """Верхняя панель: слово по центру, крестик поверх справа"""
        top_bar = tk.Frame(self, bg=COLORS["bg"], height=35)
        top_bar.pack(fill="x", pady=(10, 0))
        top_bar.pack_propagate(False)

        self.lbl_word = self._create_label(
            top_bar,
            text="English Helper",
            font_key="header",
            fg_key="text_main",
            wraplength=350
        )
        self.lbl_word.pack(expand=True)

        self.btn_close = self._create_label(
            top_bar,
            text="✕",
            font_key="header",
            fg_key="close_btn",
            cursor="hand2"
        )
        self.btn_close.config(font=FONTS["close_btn"])
        self.btn_close.place(relx=1.0, rely=0.5, anchor='e', x=-10)
        self.btn_close.bind("<Button-1>", lambda e: self.close_app())
        self.btn_close.lift()

    def _create_translation_display(self):
        """Область отображения перевода с фиксированной высотой"""
        from gui.styles import TRANSLATION_HEIGHT

        self.translation_container = tk.Frame(
            self,
            bg=COLORS["bg"],
            height=TRANSLATION_HEIGHT
        )
        self.translation_container.pack(fill='x', padx=5, pady=(0, 0))
        self.translation_container.pack_propagate(False)

        self.lbl_rus = tk.Label(
            self.translation_container,
            text="Ready",
            fg=COLORS["text_accent"],
            bg=COLORS["bg"],
            wraplength=self.DEFAULT_WRAPLENGTH,
            justify='center',
            font=("Segoe UI", 20)
        )
        self.lbl_rus.pack(expand=True)

    def _create_image_container(self):
        """
        Контейнер для изображения с фиксированной высотой = 25% окна.

        📍 НАСТРОЙКА ВНЕШНЕГО ВИДА:
        - Высота: IMAGE_CONTAINER_HEIGHT_PERCENT (25%)
        - Padding X: IMAGE_CONTAINER_PADDING_X (20px)
        - Padding Y: IMAGE_CONTAINER_PADDING_Y (5px)
        """
        # КРИТИЧНО: Используем update_idletasks() чтобы получить реальную высоту окна
        self.update_idletasks()

        # Вычисляем высоту контейнера: 25% от текущей высоты окна
        container_height = int(self.winfo_height() * self.IMAGE_CONTAINER_HEIGHT_PERCENT)

        # Создаём Frame-контейнер с фиксированной высотой
        self.img_frame = tk.Frame(
            self,
            bg=COLORS["bg"],
            height=container_height
        )
        self.img_frame.pack(
            fill="x",
            padx=self.IMAGE_CONTAINER_PADDING_X,
            pady=self.IMAGE_CONTAINER_PADDING_Y
        )
        self.img_frame.pack_propagate(False)  # КРИТИЧНО: запрещаем изменение высоты!

        # Label внутри для картинки (будет центрироваться)
        self.img_container = tk.Label(
            self.img_frame,
            bg=COLORS["bg"]
        )
        self.img_container.pack(expand=True)

    def _create_scrollable_content(self):
        """Прокручиваемая область"""
        self.scrollable_frame = tk.Frame(self, bg=COLORS["bg"])
        self.scrollable_frame.pack(fill="both", expand=True, padx=0, pady=1)

        self.canvas_scroll = None
        self.scrollbar = None

    def _create_vocab_slider(self):
        """Слайдер уровня словаря"""
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

        btn_minus = self._create_label(
            slider_area,
            text="<",
            fg_key="text_accent",
            cursor="hand2"
        )
        btn_minus.config(font=("Consolas", 12, "bold"))
        btn_minus.pack(side="left", padx=2)
        btn_minus.bind("<Button-1>", lambda e: self.change_level(-1))

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

        self.lbl_lvl_val = self._create_label(
            slider_area,
            text=str(self.vocab_var.get()),
            fg_key="text_header"
        )
        self.lbl_lvl_val.config(font=("Segoe UI", 9, "bold"))
        self.lbl_lvl_val.pack(side="left", padx=(5, 0))
        self.scale.config(command=lambda v: self.lbl_lvl_val.config(text=v))

    def _create_status_bar(self):
        """Нижняя панель статуса с кнопками управления"""
        status_bar = tk.Frame(self.bottom_frame, bg=COLORS["bg"])
        status_bar.pack(side="bottom", fill="x", pady=2)

        self.grip = ResizeGrip(
            status_bar,
            self.resize_window,
            self.save_size,
            COLORS["bg"],
            COLORS["resize_grip"]
        )
        self.grip.pack(side="right", anchor="se")

        self.lbl_status = tk.Label(
            status_bar,
            text="Waiting...",
            font=("Segoe UI", 7),
            bg=COLORS["bg"],
            fg=COLORS["text_faint"]
        )
        self.lbl_status.pack(side="right", padx=5)

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

        self.btn_cache = ActionButton(
            status_bar,
            "Cache --",
            self.clear_cache
        )
        self.btn_cache.pack(side="left", padx=(0, 10))

    def _bind_events(self):
        """Привязка событий"""
        self.bind("<Button-1>", self.start_move)
        self.bind("<B1-Motion>", self.do_move)
        self.bind("<ButtonRelease-1>", self.stop_move)

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
        """Обновление UI полными данными словаря"""
        if not full_data:
            self.dict_renderer.render(None)
        else:
            self.dict_renderer.render(full_data)

    # ===== IMAGE HANDLER =====

    def update_img_ui(self, path: Optional[str], source: str):
        """
        Обновление изображения с ресайзом под фиксированную высоту.

        Логика:
        - Вычисляем целевую высоту (25% окна - padding)
        - Ресайзим с сохранением пропорций
        - Центрируем в контейнере
        """
        if path:
            try:
                pil_img = Image.open(path)

                # Вычисляем целевую высоту (25% окна - padding)
                target_height = int(self.winfo_height() * self.IMAGE_CONTAINER_HEIGHT_PERCENT) - 20

                # Вычисляем ширину с сохранением aspect ratio
                aspect_ratio = pil_img.width / pil_img.height
                target_width = int(target_height * aspect_ratio)

                # Ресайз с сохранением пропорций
                pil_img = pil_img.resize(
                    (target_width, target_height),
                    Image.Resampling.LANCZOS
                )

                tki = ImageTk.PhotoImage(pil_img)
                self.img_container.config(
                    image=tki,
                    text="",
                    bg=COLORS["bg"]
                )
                self.img_container.image = tki
                self.sources["img"] = source

                # Сохраняем слово из имени файла
                import os
                filename = os.path.basename(path)
                word_from_path = os.path.splitext(filename)[0]
                self.current_image_word = word_from_path

            except Exception:
                self._show_no_image_placeholder()
                self.current_image_word = None
        else:
            self._show_no_image_placeholder()
            self.current_image_word = None

        self.refresh_status()

    def _show_no_image_placeholder(self):
        """
        Рисует серую рамку с текстом "No image" по центру.
        """
        try:
            # КРИТИЧНО: Используем update_idletasks() для получения актуальных размеров
            self.update_idletasks()

            # Размеры placeholder
            width = max(100, self.winfo_width() - (self.IMAGE_CONTAINER_PADDING_X * 2))
            height = max(50, int(self.winfo_height() * self.IMAGE_CONTAINER_HEIGHT_PERCENT) - 20)

            # Создаём пустую картинку с фоном окна
            img = Image.new("RGB", (width, height), COLORS["bg"])
            draw = ImageDraw.Draw(img)

            # Рисуем серую рамку (2px для видимости)
            draw.rectangle(
                [(1, 1), (width - 2, height - 2)],
                outline=COLORS["separator"],
                width=2  # Увеличено до 2px для лучшей видимости
            )

            # Пытаемся загрузить системный шрифт
            try:
                font = ImageFont.truetype("segoeui.ttf", 11)
            except:
                try:
                    font = ImageFont.truetype("arial.ttf", 11)
                except:
                    font = ImageFont.load_default()

            # Текст по центру
            text = "No image"

            # Получаем размеры текста
            bbox = draw.textbbox((0, 0), text, font=font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]

            text_x = (width - text_width) // 2
            text_y = (height - text_height) // 2

            # Рисуем текст
            draw.text(
                (text_x, text_y),
                text,
                fill=COLORS["text_faint"],
                font=font
            )

            # Конвертируем в PhotoImage
            tki = ImageTk.PhotoImage(img)
            self.img_container.config(image=tki, text="", bg=COLORS["bg"])
            self.img_container.image = tki

        except Exception:
            # Fallback на текстовый placeholder
            self.img_container.config(
                image="",
                text="No image",
                font=("Segoe UI", 10),
                fg=COLORS["text_faint"],
                bg=COLORS["bg"]
            )

        self.sources["img"] = "—"
        self.current_image_word = None

    # ===== STATUS =====

    @property
    def status_text(self) -> str:
        """Генерирует текст статуса"""
        return f"Tr: {self.sources['trans']} • Img: {self.sources['img']}"

    def refresh_status(self):
        """Обновляет строку статуса"""
        self.lbl_status.config(text=self.status_text)

    def update_trans_ui(self, data: Optional[Dict], source: str):
        """Обновление перевода с fallback и динамическим шрифтом"""
        from gui.styles import TRANSLATION_FALLBACK_FONT, TRANSLATION_MAX_LENGTH

        if data and data.get("rus"):
            translation_text = data["rus"]

            if len(translation_text) > TRANSLATION_MAX_LENGTH:
                translation_text = translation_text[:TRANSLATION_MAX_LENGTH - 3] + "..."

            font_size = self._calculate_translation_font_size(translation_text)

            self.lbl_rus.config(
                text=translation_text,
                fg=COLORS["text_accent"],
                font=("Segoe UI", font_size)
            )
            self.sources["trans"] = source
        else:
            current_word = self.lbl_word.cget("text")
            if current_word and current_word != "English Helper":
                fallback_text = f"({current_word})"
                font_size = self._calculate_translation_font_size(fallback_text)
            else:
                fallback_text = "No translation"
                font_size = TRANSLATION_FALLBACK_FONT

            self.lbl_rus.config(
                text=fallback_text,
                fg=COLORS["text_faint"],
                font=("Segoe UI", font_size)
            )
            self.sources["trans"] = "—"

        self.refresh_status()

    def reset_ui(self, word: str):
        """
        Сброс UI для нового слова с показом placeholders.

        Вызывается из WordProcessor перед запуском параллельных workers.
        """

        print("------- New word --------------------------------------------------------")

        # Запоминаем текущее слово (для защиты от устаревших обновлений)
        self.current_word = word

        # Заголовок с самим словом
        self.lbl_word.config(text=word)

        # Placeholder для перевода
        self.lbl_rus.config(
            text="Loading translation...",
            fg=COLORS["text_accent"],  # можно заменить на более бледный цвет, если есть
            font=("Segoe UI", 16)
        )

        # Placeholder / очистка изображения
        self.img_container.config(
            image="",
            text="",  # можно поставить "Loading image..." если хотите сразу текст
            bg=COLORS["bg"]
        )

        # Очищаем область словаря и показываем skeleton loader
        self.dict_renderer.clear()
        self._show_skeleton_loader()

        # Сбрасываем источники
        self.sources = {"trans": "...", "img": "..."}

        # Обновляем статусную строку и wrap перевода
        self.refresh_status()
        try:
            self.lbl_rus.config(wraplength=self.winfo_width() - 20)
        except Exception:
            pass

        # Обновляем состояние кнопки кэша, если она есть
        try:
            self.update_cache_button()
        except Exception:
            pass

    def _show_skeleton_loader(self):
        """
        Просто очищает область словаря (без графических полосок).
        """
        parent = getattr(self.dict_renderer, "parent", None)
        if parent:
            for w in parent.winfo_children():
                w.destroy()

            # Можно добавить простой текст, если хотите, или оставить пустым
            # import tkinter as tk
            # tk.Label(parent, text="Thinking...", font=("Segoe UI", 10), bg=COLORS["bg"], fg=COLORS["text_faint"]).pack(pady=20)

    # ===== WINDOW CONTROLS =====

    def resize_window(self, dx: int, dy: int):
        """Изменение размера окна"""
        from gui.styles import TRANSLATION_FALLBACK_FONT

        current_x = self.winfo_x()
        current_y = self.winfo_y()

        new_w = max(self.MIN_WINDOW_WIDTH, self.winfo_width() + dx)
        new_h = max(self.MIN_WINDOW_HEIGHT, self.winfo_height() + dy)

        self.geometry(f"{new_w}x{new_h}+{current_x}+{current_y}")

        # Пересчитываем шрифт перевода при resize (только для реального перевода)
        current_text = self.lbl_rus.cget("text")
        service_messages = ["Ready", "Loading...", "No translation"]
        is_service = any(msg in current_text for msg in service_messages)

        if current_text and not is_service:
            font_size = self._calculate_translation_font_size(current_text)
            self.lbl_rus.config(font=("Segoe UI", font_size))

        self.scrollable_frame.event_generate("<Configure>")

    def save_size(self):
        """Сохранение размера окна и обновление wraplength"""
        new_w = self.winfo_width()
        new_h = self.winfo_height()

        cfg.set("USER", "WindowWidth", new_w)
        cfg.set("USER", "WindowHeight", new_h)

        # Обновляем wraplength после завершения resize
        self.lbl_rus.config(wraplength=new_w - 20)
        self.lbl_word.config(wraplength=new_w - 50)

    def toggle_sentence_window(self, event=None):
        """Переключение окна предложений с анимацией"""
        current = cfg.get_bool("USER", "ShowSentenceWindow", True)
        new_state = not current

        if new_state:
            cfg.set("USER", "ShowSentenceWindow", True)
            self.sent_window.show_animated()
            self.btn_toggle_sent.sync_state()
        else:
            self.sent_window.close_window()

    def toggle_auto_pronounce(self, event=None):
        """Переключение автопроизношения"""
        current = cfg.get_bool("USER", "AutoPronounce", True)
        new_state = not current
        cfg.set("USER", "AutoPronounce", new_state)

        self.btn_toggle_pronounce.sync_state()

    # ===== VOCAB SLIDER =====

    def change_level(self, delta: int):
        """Изменение уровня словаря через стрелки"""
        new_val = self.vocab_var.get() + delta
        if 0 <= new_val <= 100:
            self.vocab_var.set(new_val)
            self.lbl_lvl_val.config(text=str(new_val))

            if self.popup and self.popup.winfo_viewable():
                self.popup.update_words(new_val)

            self.save_level()

    def save_level(self):
        """Сохранение уровня"""
        cfg.set("USER", "VocabLevel", self.vocab_var.get())

    def on_slider_press(self, event):
        """Обработка нажатия на ползунок слайдера"""
        self._popup_was_open_before_click = self.popup and self.popup.winfo_viewable()
        self._slider_was_moved = False
        self.dragging_allowed = False

        if not self._popup_was_open_before_click:
            x = self.winfo_x() + self.winfo_width() + 10
            y = self.winfo_y()
            self.popup.show_animated(x, y)

        self.after(10, self._update_popup_if_visible)

    def _update_popup_if_visible(self):
        """Обновляет popup если он открыт"""
        if self.popup and self.popup.winfo_viewable():
            self.popup.update_words(self.vocab_var.get())

    def on_slider_motion(self, event):
        """Обработка движения ползунка (drag)"""
        self._slider_was_moved = True

        self.lbl_lvl_val.config(text=str(self.vocab_var.get()))

        if self.popup and self.popup.winfo_viewable():
            self.popup.update_words(self.vocab_var.get())

    def on_slider_release(self, event):
        """Обработка отпускания кнопки мыши после взаимодействия со слайдером"""
        self.save_level()

        if self._popup_was_open_before_click and not self._slider_was_moved:
            if self.popup and self.popup.winfo_viewable():
                self.popup.close_animated()

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
        if hasattr(self, 'popup') and self.popup:
            self.popup.destroy()

        keyboard.unhook_all()
        self.destroy()
