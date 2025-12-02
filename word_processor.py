"""
Процессор слов для EnglishHelper.

Обрабатывает:
- Фильтрацию простых слов по уровню словаря
- Параллельную загрузку данных (перевод, изображение, словарь)
- Координацию workers
- Кэш проверку перед API запросами
"""

import threading
from typing import Optional
from vocab import is_word_too_simple
from network import (
    fetch_word_translation,
    fetch_image,
    fetch_full_dictionary_data,
    load_full_dictionary_data,
    check_cache_only,
    get_google_tts_url,
    get_audio_cache_path,
    streaming_play_and_cache
)
from config import cfg
import os
import time

# Graceful degradation для playsound
try:
    from playsound import playsound

    PLAYSOUND_AVAILABLE = True
except ImportError:
    playsound = None
    PLAYSOUND_AVAILABLE = False


class WordProcessor:
    """
    Обрабатывает слова: фильтрация, загрузка данных, обновление UI.

    Responsibilities:
    - Проверка "слишком простых" слов
    - Параллельная загрузка: перевод, изображение, словарь
    - Координация workers
    - Автопроизношение слов
    - Интеграция с MainWindow для UI обновлений
    """

    def __init__(self, main_window):
        """
        Args:
            main_window: Экземпляр MainWindow для UI обновлений
        """
        self.main_window = main_window

    def process_word(self, word: str):
        """
        Обрабатывает слово асинхронно в отдельном потоке.

        Args:
            word: Слово для обработки
        """
        threading.Thread(
            target=self._process_word_parallel,
            args=(word,),
            daemon=True
        ).start()

    def _process_word_parallel(self, word: str):
        """
        Параллельная обработка слова: перевод + изображение + словарь.

        Логика:
        1. Проверка "слишком простое" на основе vocab level
        2. Сброс UI для нового слова
        3. Быстрая проверка кэша перевода
        4. Параллельные запуски workers

        Args:
            word: Исходное слово
        """
        # Получаем текущий уровень словаря
        vocab_level = int(self.main_window.vocab_var.get())

        # Проверяем не слишком ли простое слово
        too_simple, lemmatized = is_word_too_simple(word, vocab_level)

        if too_simple:
            return  # Игнорируем простые слова

        # Сбрасываем UI для нового слова
        self.main_window.after(0, lambda: self.main_window.reset_ui(lemmatized))

        # Быстрая проверка кэша перевода
        cached_translation = check_cache_only(lemmatized)

        if cached_translation:
            # Есть в кэше → немедленное отображение
            self.main_window.after(
                0,
                lambda: self.main_window.update_trans_ui(cached_translation, "Cache")
            )
        else:
            # Нет в кэше → запускаем загрузку
            threading.Thread(
                target=self._worker_translation,
                args=(lemmatized,),
                daemon=True
            ).start()

        # Параллельные загрузки изображения и словарных данных
        threading.Thread(
            target=self._worker_image,
            args=(lemmatized,),
            daemon=True
        ).start()

        threading.Thread(
            target=self._worker_full_dictionary,
            args=(lemmatized,),
            daemon=True
        ).start()

    def _worker_translation(self, word: str):
        """
        Worker для загрузки перевода слова.

        Args:
            word: Лемматизированное слово
        """
        result = fetch_word_translation(word)

        # Обновляем UI в главном потоке
        self.main_window.after(
            0,
            lambda: self.main_window.update_trans_ui(
                result or {},
                "API" if result and not result.get("cached") else "—"
            )
        )

    def _worker_image(self, word: str):
        """
        Worker для загрузки изображения.

        Args:
            word: Лемматизированное слово
        """
        image_path, source = fetch_image(word)

        # Обновляем UI в главном потоке
        self.main_window.after(
            0,
            lambda: self.main_window.update_img_ui(image_path, source)
        )

    def _worker_full_dictionary(self, word: str):
        """
        Worker для загрузки полных словарных данных + автопроизношение.

        Args:
            word: Лемматизированное слово
        """
        # Проверяем кэш
        full_data = load_full_dictionary_data(word)

        # Если нет в кэше - загружаем
        if not full_data:
            full_data = fetch_full_dictionary_data(word)

        # Обновляем UI
        self.main_window.after(
            0,
            lambda: self.main_window.update_full_data_ui(full_data)
        )

        # Автопроизношение в отдельном потоке
        if cfg.get_bool("USER", "AutoPronounce"):
            threading.Thread(
                target=self._instant_auto_pronounce,
                args=(word,),
                daemon=True
            ).start()

    def _instant_auto_pronounce(self, word: str):
        """
        Автоматическое произношение слова (только Google TTS US).

        Оптимизировано: активное ожидание файла до 2 секунд.

        Args:
            word: Слово для произношения
        """
        if not PLAYSOUND_AVAILABLE or playsound is None:
            return

        try:
            cache_path = get_audio_cache_path(word, "us")

            # Активное ожидание готовности файла (до 2 секунд)
            max_wait = 20  # 20 × 0.1s = 2 секунды
            for attempt in range(max_wait):
                if os.path.exists(cache_path) and os.path.getsize(cache_path) > 1000:
                    try:
                        playsound(cache_path)
                        return
                    except Exception:
                        break
                time.sleep(0.1)

            # Fallback: streaming воспроизведение
            url = get_google_tts_url(word, "us")
            streaming_play_and_cache(url, cache_path)

        except Exception:
            pass  # Graceful degradation
