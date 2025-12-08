"""
Модуль управления конфигурацией для EnglishHelper.

Обрабатывает:
- Сохранение настроек (INI файл)
- Инициализацию структуры директорий
- Подсчет размера кэша и его очистку
- Singleton экземпляр ConfigManager

Оптимизации производительности:
- os.scandir() для эффективного обхода директорий
- Ленивое создание директорий
- Минимум системных вызовов
"""

import configparser
import os
from typing import Final

# ===== КОНСТАНТЫ =====
CONFIG_FILE: Final[str] = "settings.ini"
DATA_DIR: Final[str] = "Data"
IMG_DIR: Final[str] = os.path.join(DATA_DIR, "Images")
DICT_DIR: Final[str] = os.path.join(DATA_DIR, "Dicts")
AUDIO_DIR: Final[str] = os.path.join(DATA_DIR, "Audio")
TEMP_AUDIO_DIR: Final[str] = os.path.join(DATA_DIR, "TempAudio")
VOCAB_FILE: Final[str] = os.path.join(DATA_DIR, "vocab_20k.txt")
_MB: Final[int] = 1048576  # Байт в мегабайте (1024 * 1024)

DEFAULT_CONFIG: Final[dict] = {
    "API": {
        "YandexKey": "",
        "PexelsKey": "",
        "GoogleTTSCredentials": "google-tts-credentials.json",
        "GoogleTTSVoiceWord": "en-US-Neural2-J",           # Голос для слов
        "GoogleTTSVoiceSentence": "en-US-Neural2-C",      # Голос для предложений
        "GoogleTTSSpeedWord": "1.0",                       # Скорость для слов
        "GoogleTTSSpeedSentence": "0.9"                    # Скорость для предложений
    },
    "USER": {
        "VocabLevel": "10",
        "WindowX": "100",
        "WindowY": "100",
        "WindowWidth": "416",
        "WindowHeight": "953",
        "ShowSentenceWindow": "True",
        "SentWindowGeometry": "600x150+700+100",
        "AutoPronounce": "True"
    }
}


# ===== ИНИЦИАЛИЗАЦИЯ ДИРЕКТОРИЙ =====

def _ensure_directories():
    """
    Ленивое создание директорий - вызывается только при создании ConfigManager.
    Использует exist_ok=True для избежания race conditions.
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(IMG_DIR, exist_ok=True)
    os.makedirs(DICT_DIR, exist_ok=True)
    os.makedirs(AUDIO_DIR, exist_ok=True)
    os.makedirs(TEMP_AUDIO_DIR, exist_ok=True)


# ===== МЕНЕДЖЕР КОНФИГУРАЦИИ =====

class ConfigManager:
    """
    Управляет конфигурацией приложения с автоматической валидацией и сохранением.
    Потокобезопасность: Этот класс НЕ потокобезопасен. Используйте singleton 'cfg'.
    """

    def __init__(self):
        _ensure_directories()
        self.config = configparser.ConfigParser()

        if not os.path.exists(CONFIG_FILE):
            self._create_default()
        else:
            self.config.read(CONFIG_FILE, encoding='utf-8')
            self._validate()

    def _create_default(self):
        """Создает файл конфигурации по умолчанию"""
        for section, options in DEFAULT_CONFIG.items():
            self.config[section] = options
        self._save()

    def _validate(self):
        """
        Валидирует целостность конфигурации и добавляет недостающие ключи.
        Критично для обратной совместимости при добавлении новых настроек.
        """
        changed = False

        for section, options in DEFAULT_CONFIG.items():
            if not self.config.has_section(section):
                self.config.add_section(section)
                changed = True

            for key, val in options.items():
                if not self.config.has_option(section, key):
                    self.config.set(section, key, val)
                    changed = True

        if changed:
            self._save()

    def _save(self):
        """Сохраняет конфигурацию на диск"""
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            self.config.write(f)

    def get(self, section: str, key: str, fallback=None) -> str:
        """Получает значение конфигурации как строку"""
        return self.config.get(section, key, fallback=fallback)

    def get_bool(self, section: str, key: str, fallback=False) -> bool:
        """Получает значение конфигурации как boolean"""
        return self.config.getboolean(section, key, fallback=fallback)

    def set(self, section: str, key: str, value) -> None:
        """
        Обновляет значение конфигурации и сохраняет на диск.
        Примечание: Каждый set() вызывает файловый I/O. Для пакетных обновлений
        рассмотрите реализацию метода set_batch().
        """
        if not self.config.has_section(section):
            self.config.add_section(section)

        self.config.set(section, key, str(value))
        self._save()


# ===== УТИЛИТЫ КЭША =====

def get_cache_size_mb() -> float:
    """
    Вычисляет общий размер директории кэша в мегабайтах.

    Оптимизации:
    - Один проход os.walk()
    - Без избыточных os.path.exists() (walk гарантирует существование)
    - Graceful обработка недоступных файлов

    Returns:
        Размер кэша в MB с округлением до 1 знака
    """
    if not os.path.exists(DATA_DIR):
        return 0.0

    total_size = 0

    try:
        for dirpath, _, filenames in os.walk(DATA_DIR):
            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                try:
                    total_size += os.path.getsize(filepath)
                except OSError:
                    # Файл удален/недоступен во время итерации - пропускаем
                    continue
    except OSError:
        # Ошибка доступа к корневой директории
        return 0.0

    return round(total_size / _MB, 1)


def clear_cache() -> int:
    """
    Удаляет все закэшированные файлы с сохранением структуры директорий.

    Оптимизация: Использует os.scandir() вместо listdir() + isfile()
    - scandir() возвращает DirEntry объекты с кэшированными результатами stat()
    - Устраняет избыточные системные вызовы (2x улучшение производительности)

    Сохраняет:
    - vocab_20k.txt (в корне DATA_DIR)
    - Структуру директорий

    Returns:
        Количество успешно удаленных файлов
    """
    deleted_count = 0

    for subdir in (IMG_DIR, DICT_DIR, AUDIO_DIR, TEMP_AUDIO_DIR):
        if not os.path.exists(subdir):
            continue

        try:
            # os.scandir() в 2-3 раза быстрее чем os.listdir() + os.path.isfile()
            # потому что DirEntry кэширует результаты stat()
            with os.scandir(subdir) as entries:
                for entry in entries:
                    if entry.is_file():
                        try:
                            os.unlink(entry.path)
                            deleted_count += 1
                        except OSError:
                            # Файл заблокирован/удален другим процессом - пропускаем
                            continue
        except OSError:
            # Ошибка доступа к директории - пропускаем всю директорию
            continue

    return deleted_count


# ===== SINGLETON ЭКЗЕМПЛЯР =====

# КРИТИЧНО: Импортируйте этот singleton вместо создания новых экземпляров ConfigManager
# чтобы избежать избыточного файлового I/O и потенциальных race conditions
cfg = ConfigManager()
