"""
Процессор слов для EnglishHelper.

Координирует параллельные потоки загрузки данных.

Architecture:
- 3 независимых потока (Яндекс, API, Аудио)
- ThreadPoolExecutor для ограничения потоков (защита от memory leak)
- State tracking для предотвращения race conditions (защита от старых данных)
- Прогрессивное обновление UI
"""

import threading
import time
import os
from typing import Optional, Dict
from concurrent.futures import ThreadPoolExecutor

from config import cfg
from vocab import is_word_too_simple
from network import (
    fetch_yandex_translation,
    fetch_google_translation,
    fetch_dictionary_meanings_only,
    load_full_dictionary_data,
    save_full_dictionary_data,
    load_translation_cache,
    save_translation_cache,
    get_google_tts_url,
    get_audio_cache_path,
    download_and_cache_audio,
    is_valid_audio_file,
    streaming_play_and_cache,
    _audio_play_lock
)

# Graceful degradation для playsound
try:
    from playsound import playsound
    PLAYSOUND_AVAILABLE = True
except ImportError:
    playsound = None
    PLAYSOUND_AVAILABLE = False


class WordProcessor:
    """
    Координирует параллельную загрузку данных для слова.

    Responsibilities:
    - Фильтрация простых слов (vocab level)
    - Параллельные потоки: перевод, meanings, аудио
    - State tracking для предотвращения устаревших обновлений
    - Thread pool management
    """

    # Thread pools с ограничением одновременных задач
    _translation_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="Translation")
    _dictionary_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="Dictionary")
    _audio_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="Audio")

    def __init__(self, main_window):
        """
        Args:
            main_window: Экземпляр MainWindow для UI обновлений
        """
        self.main_window = main_window

        # State tracking для предотвращения устаревших обновлений
        self._current_word_lock = threading.Lock()
        self._current_word = None

        # Флаг успешной загрузки meanings (чтобы таймаут не перетирал данные)
        self._meanings_loaded_event = threading.Event()

    def process_word(self, word: str, force: bool = False):
        """
        Запускает параллельную обработку слова.

        Args:
            word: Слово для обработки
            force: Если True, игнорирует фильтр "слишком простых" слов
        """
        threading.Thread(
            target=self._process_word_parallel,
            args=(word, force),
            daemon=True,
            name=f"Coordinator-{word}"
        ).start()

    def _process_word_parallel(self, word: str, force: bool = False):
        """
        Параллельная обработка слова: 3 потока.
        """
        # Получаем текущий уровень словаря
        try:
            vocab_level = int(self.main_window.vocab_var.get())
        except (ValueError, AttributeError):
            vocab_level = 10  # Fallback

        # Проверяем не слишком ли простое слово
        too_simple, cleaned_word = is_word_too_simple(word, vocab_level)

        if too_simple and not force:
            return  # Игнорируем простые слова

        if not cleaned_word:
            return

        # ===== STATE TRACKING =====
        with self._current_word_lock:
            if self._current_word == cleaned_word:
                return  # Уже обрабатываем это слово!
            self._current_word = cleaned_word
            self._meanings_loaded_event.clear()  # СБРОС ФЛАГА: новые данные ещё не загружены

        # Сбрасываем UI (показываем skeleton loaders)
        self.main_window.after(0, lambda: self.main_window.reset_ui(cleaned_word))

        # ═══════════════════════════════════════════════════════════════════
        # 🧵 ПОТОКИ ЗАГРУЗКИ
        # ═══════════════════════════════════════════════════════════════════
        self._translation_executor.submit(
            self._worker_translation_only,
            cleaned_word
        )

        self._dictionary_executor.submit(
            self._worker_dictionary_meanings,
            cleaned_word
        )

        if cfg.get_bool("USER", "AutoPronounce"):
            self._audio_executor.submit(
                self._worker_audio_sequential,
                cleaned_word
            )

        # ═══════════════════════════════════════════════════════════════════
        # TIMEOUT FALLBACK
        # ═══════════════════════════════════════════════════════════════════
        #threading.Thread(
        #    target=self._timeout_handler,
        #    args=(cleaned_word,),
        #    daemon=True,
        #    name=f"Timeout-{cleaned_word}"
        #).start()

    # ═══════════════════════════════════════════════════════════════════════
    # WORKERS
    # ═══════════════════════════════════════════════════════════════════════

    def _worker_translation_only(self, word: str):
        """Worker для загрузки ТОЛЬКО перевода."""
        # 1. Сначала пробуем кэш
        cached_trans = load_translation_cache(word)
        if cached_trans:
            with self._current_word_lock:
                if self._current_word != word: return
            self.main_window.after(
                0,
                lambda: self.main_window.update_trans_ui(
                    {"rus": cached_trans, "cached": True}, "Cache"
                )
            )
            return

        # 2. Пробуем Яндекс
        rus_trans = fetch_yandex_translation(word)

        # 3. Fallback на Google
        if not rus_trans:
            rus_trans = fetch_google_translation(word)

        if rus_trans:
            # УСПЕХ: Сохраняем и показываем
            with self._current_word_lock:
                if self._current_word != word: return

            save_translation_cache(word, rus_trans)

            self.main_window.after(
                0,
                lambda: self.main_window.update_trans_ui(
                    {"rus": rus_trans, "cached": False}, "API"
                )
            )
        else:
            # ОШИБКА: Перевода нет ни в Яндексе, ни в Google.
            # Сразу показываем прочерк.
            with self._current_word_lock:
                if self._current_word != word: return

            self.main_window.after(
                0,
                lambda: self.main_window.update_trans_ui(None, "—")
            )

    def _worker_dictionary_meanings(self, word: str):
        """Worker для загрузки meanings из DictionaryAPI."""
        full_data = load_full_dictionary_data(word)

        if not full_data:
            full_data = fetch_dictionary_meanings_only(word)
            if full_data:
                save_full_dictionary_data(word, full_data)

        with self._current_word_lock:
            if self._current_word != word:
                return

        if full_data:
            # УСПЕХ: Показываем данные
            self.main_window.after(
                0,
                lambda: self.main_window.update_full_data_ui(full_data)
            )
        else:
            # ОШИБКА: API не ответил.
            # Но мы должны передать САМО СЛОВО, чтобы DictRenderer
            # мог хотя бы показать формы (Lemminflect) и картинку.
            self.main_window.after(
                0,
                lambda: self.main_window.update_full_data_ui({
                    "word": word,  # <--- ВАЖНО: Передаем слово!
                    "meanings": []
                })
            )

    def _worker_audio_sequential(self, word: str):
        """Worker для аудио: делегирует всю работу в network."""
        from network import ensure_audio_ready, play_audio_safe

        # 1. Получаем файл (скачиваем или берем из кэша)
        audio_path = ensure_audio_ready(word)

        if not audio_path:
            return

        # 2. Проверяем, актуально ли еще слово (пока качали/ждали)
        with self._current_word_lock:
            if self._current_word != word:
                return

        # 3. Проигрываем
        play_audio_safe(audio_path)

    # ═══════════════════════════════════════════════════════════════════════
    # TIMEOUT HANDLER (ИСПРАВЛЕННЫЙ)
    # ═══════════════════════════════════════════════════════════════════════

    def _timeout_handler(self, word: str):
        """
        Показывает fallback UI при timeout (5 секунд).

        Срабатывает ТОЛЬКО если данные ещё не загрузились.
        """
        time.sleep(2)

        with self._current_word_lock:
            if self._current_word != word:
                return  # Уже другое слово

        # 1. Проверяем перевод (читаем текст лейбла)
        try:
            current_trans_text = self.main_window.lbl_rus.cget("text")
            if "Loading" in current_trans_text:
                self.main_window.after(
                    0,
                    lambda: self.main_window.update_trans_ui(None, "—")
                )
        except Exception:
            pass

        # 2. Проверяем meanings (проверяем ФЛАГ)
        # Если флаг НЕ поднят — значит данные так и не пришли
        if not self._meanings_loaded_event.is_set():
            self.main_window.after(
                0,
                lambda: self.main_window.update_full_data_ui({"meanings": []})
            )
