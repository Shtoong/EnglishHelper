"""
Управление аудио воспроизведением для EnglishHelper.

Обрабатывает:
- Извлечение аудио URL из phonetics данных
- Обновление UI состояния кнопок US/UK
- Воспроизведение аудио в фоновом потоке
"""

import tkinter as tk
import os
import threading
from typing import List, Dict, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from gui.styles import COLORS
from network import download_and_cache_audio, get_audio_cache_path
from config import AUDIO_DIR

# Graceful degradation для playsound
try:
    from playsound import playsound

    PLAYSOUND_AVAILABLE = True
except ImportError:
    playsound = None
    PLAYSOUND_AVAILABLE = False


class AudioManager:
    """
    Управляет аудио компонентами главного окна.

    Responsibilities:
    - Парсинг phonetics данных из API
    - Управление состоянием кнопок US/UK (enabled/disabled)
    - Воспроизведение аудио по клику

    Thread Safety:
    - Воспроизведение в отдельном потоке (не блокирует UI)
    - UI обновления безопасны (вызываются синхронно)
    """

    def __init__(self,
                 phonetic_label: tk.Label,
                 us_button: tk.Label,
                 uk_button: tk.Label):
        """
        Args:
            phonetic_label: Label для отображения фонетической транскрипции
            us_button: Кнопка воспроизведения US акцента
            uk_button: Кнопка воспроизведения UK акцента
        """
        self.lbl_phonetic = phonetic_label
        self.btn_audio_us = us_button
        self.btn_audio_uk = uk_button

        # Текущие URL аудио [US, UK]
        self.current_audio_urls: List[Optional[str]] = [None, None]

    def process_phonetics(self, phonetics: List[Dict]) -> None:
        """
        Обрабатывает phonetics данные из словаря API.

        Извлекает:
        - Фонетическую транскрипцию (text)
        - US и UK аудио URL

        Обновляет:
        - lbl_phonetic с текстом транскрипции
        - Состояние кнопок US/UK (enabled если есть URL)

        Args:
            phonetics: Список phonetics объектов из API ответа
        """
        if not phonetics:
            self._clear_phonetics()
            return

        # Извлекаем текст фонетики (первый доступный)
        p_text = next((p["text"] for p in phonetics if p.get("text")), "")
        self.lbl_phonetic.config(text=p_text)

        # Извлекаем URL аудио с приоритетом US/UK
        us_url, uk_url = self._extract_audio_urls(phonetics)
        self.current_audio_urls = [us_url, uk_url]

        # Обновляем состояние кнопок (enabled/disabled визуально)
        self.btn_audio_us.config(
            fg=COLORS["text_main"] if us_url else COLORS["text_faint"]
        )
        self.btn_audio_uk.config(
            fg=COLORS["text_main"] if uk_url else COLORS["text_faint"]
        )

    def _clear_phonetics(self) -> None:
        """Очищает phonetics UI (нет данных)"""
        self.lbl_phonetic.config(text="")
        self.btn_audio_us.config(fg=COLORS["text_faint"])
        self.btn_audio_uk.config(fg=COLORS["text_faint"])
        self.current_audio_urls = [None, None]

    def _extract_audio_urls(self, phonetics: List[Dict]) -> Tuple[Optional[str], Optional[str]]:
        """
        Извлекает US и UK аудио URL из phonetics с приоритетом.

        Приоритет поиска:
        1. Точное совпадение: "-us.mp3" / "-uk.mp3" в URL
        2. Язык в URL: "en-US" / "en-GB"
        3. Fallback: первые два доступных URL

        Args:
            phonetics: Список phonetics объектов

        Returns:
            (us_url, uk_url) - может содержать None если не найдено
        """
        # Приоритетный поиск US
        us = next(
            (p["audio"] for p in phonetics
             if "-us.mp3" in p.get("audio", "").lower() or "en-US" in p.get("audio", "")),
            None
        )

        # Приоритетный поиск UK
        uk = next(
            (p["audio"] for p in phonetics
             if "-uk.mp3" in p.get("audio", "").lower() or "en-GB" in p.get("audio", "")),
            None
        )

        # Fallback: используем первые доступные URL если не нашли приоритетные
        if not us or not uk:
            available = [p["audio"] for p in phonetics if p.get("audio")]
            us = us or (available[0] if len(available) > 0 else None)
            uk = uk or (available[1] if len(available) > 1 else None)

        return us, uk

    def play_audio(self, index: int) -> None:
        """
        Воспроизводит аудио по индексу (0=US, 1=UK).

        Логика:
        - Проверяет наличие URL
        - Запускает воспроизведение в отдельном потоке
        - Graceful degradation если playsound не доступен

        Args:
            index: 0 для US, 1 для UK
        """
        if index >= len(self.current_audio_urls):
            return

        url = self.current_audio_urls[index]
        if not url:
            return

        # Воспроизведение в отдельном потоке (не блокирует UI)
        threading.Thread(
            target=self._play_audio_worker,
            args=(url,),
            daemon=True
        ).start()

    def _play_audio_worker(self, url: str) -> None:
        """
        Worker для загрузки и воспроизведения аудио.

        Обрабатывает два типа URL:
        1. Google TTS (translate.google.com) - парсит word из query params
        2. Dictionary API (dictionaryapi.dev) - использует filename из URL

        Кэширование:
        - Проверяет наличие в кэше перед загрузкой
        - Скачивает и кэширует если отсутствует
        - Воспроизводит из кэша

        Args:
            url: URL аудио файла
        """
        if not PLAYSOUND_AVAILABLE or playsound is None:
            return

        try:
            # Google TTS: парсим слово из URL для именования кэша
            if "translate.google.com" in url:
                parsed = urlparse(url)
                params = parse_qs(parsed.query)
                word = params.get('q', [''])[0]
                accent = "us" if "en-US" in url else "uk"
                cache_path = get_audio_cache_path(word, accent)
            else:
                # Dictionary API: используем filename из URL
                filename = url.split("/")[-1] or f"audio_{abs(hash(url))}.mp3"
                if not filename.endswith(".mp3"):
                    filename += ".mp3"
                cache_path = os.path.join(AUDIO_DIR, filename)

            # Скачиваем если нет в кэше
            if not os.path.exists(cache_path):
                download_and_cache_audio(url, cache_path)

            # Воспроизводим
            if os.path.exists(cache_path):
                playsound(cache_path)

        except Exception:
            # Graceful degradation: ошибки воспроизведения не ломают приложение
            pass

    def clear_audio_urls(self) -> None:
        """
        Очищает сохраненные аудио URL.

        Вызывается при reset_ui() для нового слова.
        """
        self.current_audio_urls = [None, None]
