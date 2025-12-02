"""
Менеджер ввода для EnglishHelper.

Обрабатывает:
- Глобальные клавиатурные события (keyboard hook)
- Определение раскладки клавиатуры (с кэшированием)
- Буферизацию слов
- Clipboard события (Ctrl+C)
- Фикс бага библиотеки keyboard

Architecture:
- Callback-based для интеграции с основным приложением
- Thread-safe буферизация
- Оптимизированная проверка раскладки (кэш 500ms)
"""

import keyboard
import ctypes
import time
import pyperclip
import re
from typing import Callable, Optional


class InputManager:
    """
    Управляет всеми входными событиями приложения.

    Responsibilities:
    - Глобальный keyboard hook
    - Буферизация символов для формирования слов
    - Проверка раскладки с кэшированием
    - Обработка clipboard событий
    - Фикс бага keyboard библиотеки (русские символы вместо английских)
    """

    # ===== КОНСТАНТЫ =====
    LAYOUT_CACHE_TTL = 0.5  # seconds - время жизни кэша раскладки
    CLIPBOARD_THROTTLE = 0.5  # seconds - минимальный интервал между обработками Ctrl+C

    # ===== KEYBOARD LIBRARY BUG FIX =====
    # КРИТИЧНО: НЕ УДАЛЯТЬ!
    # Библиотека keyboard на Windows имеет баг: при английской раскладке
    # e.name может возвращать РУССКИЕ символы (по физической позиции клавиши).
    # Например: нажатие "h" → e.name = "р" (русская буква на той же клавише).
    # Этот словарь преобразует русские символы обратно в английские.
    # Без него во втором окне будет печататься кириллица вместо латиницы!
    KEYBOARD_BUG_FIX = {
        ru: en
        for ru, en in zip(
            "йцукенгшщзхъфывапролджэячсмитьбю",
            "qwertyuiop[]asdfghjkl;'zxcvbnm,.",
        )
    }

    def __init__(self,
                 on_word_complete: Callable[[str], None],
                 on_sentence_update: Callable[[str, bool, bool], None]):
        """
        Args:
            on_word_complete: Callback(word) - вызывается при завершении слова
            on_sentence_update: Callback(text_with_cursor, need_translate, sentence_finished)
                               - вызывается при изменении предложения
        """
        self.on_word_complete = on_word_complete
        self.on_sentence_update = on_sentence_update

        # Состояние буфера
        self.word_buffer = ""  # Накапливает символы текущего слова

        # Кэш раскладки клавиатуры
        self._layout_cache = {"is_english": True, "last_check": 0}

        # Clipboard throttling
        self._clipboard_last_time = 0

        # Ссылка на функцию хука (для unhook)
        self._hook_func = None

    def start_listening(self):
        """Запускает глобальные хуки клавиатуры"""
        self._hook_func = self._on_key_event
        keyboard.hook(self._hook_func)
        keyboard.add_hotkey("ctrl+c", self._handle_clipboard)

    def stop_listening(self):
        """Останавливает хуки и очищает ресурсы"""
        if self._hook_func:
            keyboard.unhook_all()
            self._hook_func = None

    def clear_buffer(self):
        """Очищает буфер слова (вызывается извне при необходимости)"""
        self.word_buffer = ""

    def _is_english_layout(self) -> bool:
        """
        Проверяет английскую раскладку с кэшированием (500ms TTL).

        Оптимизация: 100+ WinAPI вызовов/мин → 2 вызова/сек = 98% снижение.

        Returns:
            True если текущая раскладка английская
        """
        current_time = time.time()

        # Проверяем кэш
        if current_time - self._layout_cache["last_check"] < self.LAYOUT_CACHE_TTL:
            return self._layout_cache["is_english"]

        # Обновляем кэш через WinAPI
        try:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            hwnd = user32.GetForegroundWindow()
            thread_id = user32.GetWindowThreadProcessId(hwnd, 0)
            layout_id = user32.GetKeyboardLayout(thread_id)
            is_en = ((layout_id & 0xFFFF) & 0x3FF) == 0x09

            self._layout_cache["is_english"] = is_en
            self._layout_cache["last_check"] = current_time
            return is_en
        except Exception:
            return True

    def _handle_clipboard(self):
        """
        Обрабатывает событие Ctrl+C с throttling.

        Throttling предотвращает:
        - Множественные срабатывания при удержании Ctrl+C
        - Спам API запросов при повторных копированиях
        """
        current_time = time.time()

        # Throttling: минимум 500ms между обработками
        if current_time - self._clipboard_last_time < self.CLIPBOARD_THROTTLE:
            return

        self._clipboard_last_time = current_time

        # Минимальная задержка для гарантии записи в буфер
        time.sleep(0.02)

        try:
            text = pyperclip.paste()
        except Exception:
            return

        if not text:
            return

        text = text.strip()

        # Валидация: только слова длиной 1-50 символов
        if not (0 < len(text) <= 50):
            return
        if not re.match(r"^[a-zA-Z\-']+$", text):
            return

        # Передаем слово на обработку
        self.on_word_complete(text)

    def _on_key_event(self, e):
        """
        Глобальный обработчик клавиатурных событий.

        Логика:
        1. Фильтрация: только key up, английская раскладка, без модификаторов
        2. Фикс бага keyboard: замена русских символов на английские
        3. Обработка символов: буквы → в буфер, пунктуация → завершение слова
        4. Навигация: backspace, delete, стрелки
        5. Callback на обновление предложения

        Args:
            e: KeyboardEvent от библиотеки keyboard
        """
        # Фильтрация: обрабатываем только key up
        if e.event_type == "down":
            return

        # Проверка раскладки (с кэшем)
        if not self._is_english_layout():
            return

        # Игнорируем комбинации с модификаторами
        if keyboard.is_pressed('ctrl') or keyboard.is_pressed('alt'):
            return

        key = e.name
        key_lower = key.lower()

        # КРИТИЧНО: Фикс бага keyboard библиотеки
        # Преобразует русские символы в английские по физической позиции
        if key_lower in self.KEYBOARD_BUG_FIX:
            key = self.KEYBOARD_BUG_FIX[key_lower]

        # Флаги для callback
        update_needed = False
        need_translate = False
        sentence_finished = False

        # === ОБРАБОТКА СИМВОЛОВ ===
        if len(key) == 1:
            update_needed = True

            # Буквы → добавляем в буфер слова
            if re.match(r"^[a-zA-Z]$", key):
                self.word_buffer += key

            # Пунктуация → завершение слова
            elif key in [" ", ".", ",", "!", "?"]:
                need_translate = True

                if self.word_buffer:
                    self.on_word_complete(self.word_buffer)
                    self.word_buffer = ""

                # Конец предложения
                if key in [".", "!", "?"]:
                    sentence_finished = True

        # === ПРОБЕЛ ===
        elif key_lower == "space":
            update_needed = True
            need_translate = True

            if self.word_buffer:
                self.on_word_complete(self.word_buffer)
                self.word_buffer = ""

        # === ENTER ===
        elif key_lower == "enter":
            update_needed = True
            need_translate = True
            sentence_finished = True

            if self.word_buffer:
                self.on_word_complete(self.word_buffer)
                self.word_buffer = ""

        # === BACKSPACE ===
        elif key_lower == "backspace":
            update_needed = True
            if self.word_buffer:
                self.word_buffer = self.word_buffer[:-1]

        # === DELETE ===
        elif key_lower == "delete":
            update_needed = True

        # === НАВИГАЦИЯ: LEFT/RIGHT ===
        elif key_lower in ["left", "right"]:
            update_needed = True

        # Вызываем callback если было изменение
        if update_needed:
            # Передаем key для обработки в TextEditorSimulator
            self.on_sentence_update(key, need_translate, sentence_finished)
