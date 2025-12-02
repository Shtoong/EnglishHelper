"""
Менеджер предложений для EnglishHelper.

Обрабатывает:
- Обновление отображения предложений в SentenceWindow
- Отложенный перевод с debounce (100ms)
- Thread-safe управление таймером перевода
- Визуализация курсора
"""

import threading
from typing import Optional
from network import fetch_sentence_translation
from editor import TextEditorSimulator


class SentenceManager:
    """
    Управляет отображением и переводом предложений.

    Responsibilities:
    - Синхронизация английского текста с курсором
    - Debounced перевод (предотвращение спама API)
    - Thread-safe таймер управление
    - Интеграция с SentenceWindow
    """

    # ===== КОНСТАНТЫ =====
    TRANSLATION_DELAY = 0.1  # seconds - задержка перед переводом

    def __init__(self, sentence_window, editor: TextEditorSimulator):
        """
        Args:
            sentence_window: Экземпляр SentenceWindow для UI обновлений
            editor: Экземпляр TextEditorSimulator для управления текстом
        """
        self.sentence_window = sentence_window
        self.editor = editor

        # Thread-safe управление таймером перевода
        self._translation_lock = threading.Lock()
        self._translation_timer: Optional[threading.Timer] = None

        # КРИТИЧНО: Флаг состояния - было ли предыдущее предложение завершено
        # Нужен для корректной очистки редактора при следующем символе
        self._previous_sentence_finished = False

    def update_display(self, key_name: str, trigger_translation: bool, sentence_finished: bool):
        """
        Обновляет отображение предложения и запускает перевод при необходимости.

        Args:
            key_name: Имя нажатой клавиши (для TextEditorSimulator)
            trigger_translation: True если нужен отложенный перевод
            sentence_finished: True если предложение завершено (для автопроизношения)

        Логика:
        1. Обрабатываем клавишу через TextEditorSimulator
        2. Обновляем английский текст с курсором (немедленно)
        3. Запускаем отложенный перевод если trigger_translation=True
        """
        # Обрабатываем клавишу в редакторе
        self._process_key_in_editor(key_name, sentence_finished)

        # Обновляем английский текст с курсором
        eng_display = self.editor.get_text_with_cursor()
        self.sentence_window.after_idle(
            lambda: self.sentence_window.lbl_eng.config(text=eng_display)
        )

        # Запускаем отложенный перевод
        if trigger_translation:
            self._schedule_translation(sentence_finished)

    def _process_key_in_editor(self, key_name: str, sentence_finished: bool):
        """
        Обрабатывает нажатие клавиши в TextEditorSimulator.

        Args:
            key_name: Имя клавиши от keyboard библиотеки
            sentence_finished: True если предложение завершено
        """
        key_lower = key_name.lower()

        # Обработка обычных символов
        if len(key_name) == 1:
            # Очистка редактора при начале нового предложения
            # Используем СОХРАНЕННЫЙ флаг из предыдущего вызова
            if self._previous_sentence_finished and key_name not in [" ", ".", "!", "?", ","]:
                self.editor.clear()
                self._previous_sentence_finished = False  # Сбрасываем флаг после очистки

            self.editor.insert(key_name)

        # Обработка специальных клавиш
        elif key_lower == "space":
            self.editor.insert(" ")

        elif key_lower == "enter":
            # Enter только добавляет перевод строки
            # Редактор НЕ очищается - очистка произойдет при следующем печатном символе
            self.editor.insert("\n")

        elif key_lower == "backspace":
            self.editor.backspace()

        elif key_lower == "delete":
            self.editor.delete()

        elif key_lower == "left":
            self.editor.move_left()

        elif key_lower == "right":
            self.editor.move_right()

        # КРИТИЧНО: Сохраняем состояние завершения предложения для следующего вызова
        # Если текущая клавиша завершила предложение (Enter или . ! ?) -
        # запоминаем это, чтобы при СЛЕДУЮЩЕМ печатном символе очистить редактор
        if sentence_finished:
            self._previous_sentence_finished = True

    def _schedule_translation(self, sentence_finished: bool):
        """
        Планирует отложенный перевод с debounce.

        Debounce предотвращает множественные API вызовы при быстрой печати.
        Таймер отменяется и пересоздаётся при каждом новом запросе.

        Args:
            sentence_finished: Флаг завершения предложения (для будущей автоозвучки)
        """
        with self._translation_lock:
            # Отменяем предыдущий таймер если есть
            if self._translation_timer is not None:
                self._translation_timer.cancel()

            # Создаём новый таймер
            self._translation_timer = threading.Timer(
                self.TRANSLATION_DELAY,
                lambda: self._execute_translation(sentence_finished)
            )
            self._translation_timer.start()

    def _execute_translation(self, sentence_finished: bool):
        """
        Выполняет фактический перевод предложения.

        Запускается в отдельном потоке после debounce задержки.

        Args:
            sentence_finished: Флаг завершения предложения
        """
        clean_text = self.editor.get_text().strip()

        if clean_text:
            # Загружаем перевод
            translated = fetch_sentence_translation(clean_text)

            # Обновляем UI в главном потоке
            self.sentence_window.after(
                0,
                lambda: self.sentence_window.lbl_rus.config(text=translated)
            )

            # TODO: Здесь будет автопроизношение при sentence_finished=True
            # if sentence_finished and cfg.get_bool("USER", "AutoSpeakSentence", False):
            #     self.sentence_window.after(100, lambda: self.sentence_window.play_sentence())
        else:
            # Пустой текст → показываем placeholder
            self.sentence_window.after(
                0,
                lambda: self.sentence_window.lbl_rus.config(text="...")
            )

    def cancel_pending_translation(self):
        """
        Отменяет ожидающий перевод.

        Используется при закрытии приложения или сбросе состояния.
        """
        with self._translation_lock:
            if self._translation_timer is not None:
                self._translation_timer.cancel()
                self._translation_timer = None

    def translate_now(self, text: str):
        """
        Форсирует немедленный перевод без debounce.

        Args:
            text: Текст для перевода
        """
        if not text.strip():
            return

        translated = fetch_sentence_translation(text)
        self.sentence_window.after(
            0,
            lambda: self.sentence_window.lbl_rus.config(text=translated)
        )
