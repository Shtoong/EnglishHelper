"""
Модуль управления частотным словарем английского языка.

Загружает топ-20K слов по частотности из COCA корпуса и обеспечивает
фильтрацию "слишком простых" слов на основе пользовательского уровня.
"""

import os
import requests
from config import VOCAB_FILE

# ===== КОНСТАНТЫ =====
VOCAB_SIZE = 20000  # Размер загружаемого словаря (топ-N слов)
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
        (False, "work")  # Ранг "work" > 2000 → показываем

        >>> is_word_too_simple("the", 10)
        (True, "the")  # Ранг "the" = 1 → прячем

    Расчёт границы:
        При уровне 0:   cutoff = 0     → показываем все слова
        При уровне 10:  cutoff = 2000  → игнорируем топ-2000
        При уровне 50:  cutoff = 10000 → игнорируем топ-10K
        При уровне 100: cutoff = 20000 → игнорируем весь словарь
    """
    from network import lemmatize_word_safe

    lemma = lemmatize_word_safe(word)
    rank = WORD_RANKS.get(lemma, 99999)

    # Динамический расчёт границы на основе размера словаря
    # VOCAB_SIZE = 20000, поэтому level=100 даёт cutoff=20000
    cutoff = int(current_level * VOCAB_SIZE / 100)

    return rank < cutoff, lemma


def get_word_range(cutoff: int, before: int = 500, after: int = 500) -> tuple[list[tuple[str, int]], list[tuple[str, int]]]:
    """
    Возвращает слова до и после cutoff с их рангами.

    Args:
        cutoff: Граница между ignored и active словами (rank)
        before: Количество слов ДО cutoff (ignored)
        after: Количество слов ПОСЛЕ cutoff (active)

    Returns:
        (ignored_words, active_words)
        где каждый элемент это tuple (word, rank)

    Examples:
        cutoff=0:     ignored=[], active=[(word, 0), ..., (word, 499)]
        cutoff=500:   ignored=[(word, 0), ..., (word, 499)],
                      active=[(word, 500), ..., (word, 999)]
        cutoff=10000: ignored=[(word, 9500), ..., (word, 9999)],
                      active=[(word, 10000), ..., (word, 10499)]
        cutoff=20000: ignored=[(word, 19500), ..., (word, 19999)],
                      active=[]

    КРИТИЧНО: Обрабатывает edge cases когда cutoff у границ словаря.
    """
    total = len(SORTED_WORDS)

    # Вычисляем диапазоны индексов
    ignored_start = max(0, cutoff - before)
    ignored_end = min(cutoff, total)

    active_start = cutoff
    active_end = min(cutoff + after, total)

    # Извлекаем слова с рангами
    ignored = [(SORTED_WORDS[i], i) for i in range(ignored_start, ignored_end)]
    active = [(SORTED_WORDS[i], i) for i in range(active_start, active_end)]

    return ignored, active
