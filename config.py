import configparser
import os

CONFIG_FILE = "settings.ini"
DATA_DIR = "Data"
IMG_DIR = os.path.join(DATA_DIR, "Images")
DICT_DIR = os.path.join(DATA_DIR, "Dicts")
AUDIO_DIR = os.path.join(DATA_DIR, "Audio")
VOCAB_FILE = os.path.join(DATA_DIR, "vocab_10k.txt")

# Создаем папки, если нет
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(IMG_DIR, exist_ok=True)
os.makedirs(DICT_DIR, exist_ok=True)
os.makedirs(AUDIO_DIR, exist_ok=True)

DEFAULT_CONFIG = {
    "API": {
        "YandexKey": "",
        "PexelsKey": ""
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


class ConfigManager:
    def __init__(self):
        self.config = configparser.ConfigParser()
        if not os.path.exists(CONFIG_FILE):
            self._create_default()
        else:
            self.config.read(CONFIG_FILE)
            self._validate()

    def _create_default(self):
        for section, options in DEFAULT_CONFIG.items():
            self.config[section] = options
        self._save()

    def _validate(self):
        """Проверяет, есть ли все ключи, и добавляет недостающие"""
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
        with open(CONFIG_FILE, 'w') as f:
            self.config.write(f)

    def get(self, section, key, fallback=None):
        return self.config.get(section, key, fallback=fallback)

    def get_bool(self, section, key, fallback=False):
        return self.config.getboolean(section, key, fallback=fallback)

    def set(self, section, key, value):
        if not self.config.has_section(section):
            self.config.add_section(section)
        self.config.set(section, key, str(value))
        self._save()


def get_cache_size_mb() -> float:
    """Возвращает размер папки Data в мегабайтах"""
    if not os.path.exists(DATA_DIR):
        return 0.0

    total_size = 0
    for dirpath, dirnames, filenames in os.walk(DATA_DIR):
        for filename in filenames:
            filepath = os.path.join(dirpath, filename)
            if os.path.exists(filepath):
                try:
                    total_size += os.path.getsize(filepath)
                except Exception:
                    pass  # Игнорируем файлы, к которым нет доступа

    return round(total_size / (1024 * 1024), 1)  # MB с точностью до 0.1


def clear_cache() -> int:
    """Удаляет все файлы из кэша, сохраняя структуру папок"""
    deleted_count = 0

    for subdir in [IMG_DIR, DICT_DIR, AUDIO_DIR]:
        if os.path.exists(subdir):
            for filename in os.listdir(subdir):
                filepath = os.path.join(subdir, filename)
                try:
                    if os.path.isfile(filepath):
                        os.unlink(filepath)
                        deleted_count += 1
                except Exception as e:
                    print(f"Error deleting {filepath}: {e}")

    return deleted_count


cfg = ConfigManager()
