"""
Модуль управления частотным словарем английского языка.

Загружает топ-20K слов по частотности из COCA корпуса и обеспечивает
фильтрацию "слишком простых" слов на основе пользовательского уровня.
"""

import os
import requests
from config import VOCAB_FILE

# ===== КОНСТАНТЫ =====
TOP_WORDS_NO_LEMMA = 1000  # Топ-N слов защищены от лемматизации (предотвращает "this" → "thi")
VOCAB_LIST_URL = "https://raw.githubusercontent.com/first20hours/google-10000-english/master/20k.txt"
FALLBACK_WORDS = "the\nof\nand\na\nto\nin"  # Минимальный словарь при отсутствии интернета

# ===== ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ =====
WORD_RANKS = {}  # {word: rank} для O(1) поиска
SORTED_WORDS = []  # Отсортированный список слов (используется в popup.py)
_initialized = False  # Защита от повторной инициализации


def init_vocab():
    """
    Инициализирует частотный словарь.

    Порядок действий:
    1. Проверяет кэш файла (vocab_20k.txt)
    2. Если нет или поврежден - загружает из интернета
    3. При отсутствии интернета - создает минимальный fallback
    4. Строит WORD_RANKS dict для быстрого поиска

    Потокобезопасность: Может быть вызвана многократно без побочных эффектов.
    """
    global WORD_RANKS, SORTED_WORDS, _initialized

    # Защита от повторной инициализации
    if _initialized and SORTED_WORDS:
        return

    # Проверка существующего файла на валидность
    if os.path.exists(VOCAB_FILE):
        try:
            file_size = os.path.getsize(VOCAB_FILE)
            if file_size < 100:  # Поврежденный файл
                os.remove(VOCAB_FILE)
        except (OSError, IOError):
            pass

    # Загрузка словаря
    if not os.path.exists(VOCAB_FILE):
        _download_vocab_list()

    # Парсинг файла
    try:
        with open(VOCAB_FILE, 'r', encoding='utf-8') as f:
            words = f.read().splitlines()
            SORTED_WORDS = [w.strip().lower() for w in words if w.strip()]
            WORD_RANKS = {word: rank for rank, word in enumerate(SORTED_WORDS)}
            _initialized = True
    except (OSError, IOError, UnicodeDecodeError):
        # Критическая ошибка - создаем минимальный словарь в памяти
        SORTED_WORDS = FALLBACK_WORDS.split('\n')
        WORD_RANKS = {word: rank for rank, word in enumerate(SORTED_WORDS)}
        _initialized = True


def _download_vocab_list():
    """
    Загружает частотный список из интернета.

    При успехе сохраняет в VOCAB_FILE.
    При ошибке создает минимальный fallback файл.
    """
    try:
        resp = requests.get(VOCAB_LIST_URL, timeout=15)

        if resp.status_code == 200 and len(resp.text) > 1000:
            with open(VOCAB_FILE, 'w', encoding='utf-8') as f:
                f.write(resp.text)
        else:
            _create_fallback_file()

    except (requests.RequestException, OSError, IOError):
        _create_fallback_file()


def _create_fallback_file():
    """Создает минимальный словарь при отсутствии интернета."""
    try:
        with open(VOCAB_FILE, 'w', encoding='utf-8') as f:
            f.write(FALLBACK_WORDS)
    except (OSError, IOError):
        pass  # Если даже fallback не записался - будет работать из памяти


def is_word_too_simple(word: str, current_level: int) -> tuple[bool, str]:
    """
    Определяет, является ли слово "слишком простым" для текущего уровня.

    Args:
        word: Исходное слово (может быть в любой форме)
        current_level: Уровень пользователя из слайдера (0-100)

    Returns:
        (is_too_simple, lemmatized_word):
            - is_too_simple: True если слово нужно скрыть
            - lemmatized_word: Лемматизированная форма слова

    Examples:
        >>> is_word_too_simple("working", 10)
        (False, "work")  # Ранг "work" > 1000 → показываем

        >>> is_word_too_simple("the", 10)
        (True, "the")  # Ранг "the" = 1 → прячем
    """
    from network import lemmatize_word_safe

    lemma = lemmatize_word_safe(word)
    rank = WORD_RANKS.get(lemma, 99999)
    cutoff = current_level * 100

    return rank < cutoff, lemma
