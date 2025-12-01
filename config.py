"""
Configuration management module for EnglishHelper.

Handles:
- Settings persistence (INI file)
- Directory structure initialization
- Cache size calculation and cleanup
- Singleton ConfigManager instance

Performance optimizations:
- os.scandir() for efficient directory traversal
- Lazy directory creation
- Minimal system calls
"""

import configparser
import os
from typing import Final

# ===== CONSTANTS =====
CONFIG_FILE: Final[str] = "settings.ini"
DATA_DIR: Final[str] = "Data"
IMG_DIR: Final[str] = os.path.join(DATA_DIR, "Images")
DICT_DIR: Final[str] = os.path.join(DATA_DIR, "Dicts")
AUDIO_DIR: Final[str] = os.path.join(DATA_DIR, "Audio")
VOCAB_FILE: Final[str] = os.path.join(DATA_DIR, "vocab_10k.txt")

_MB: Final[int] = 1048576  # Bytes in megabyte (1024 * 1024)

DEFAULT_CONFIG: Final[dict] = {
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


# ===== DIRECTORY INITIALIZATION =====
def _ensure_directories():
    """
    Lazy directory creation - called only when ConfigManager is instantiated.
    Uses exist_ok=True to avoid race conditions.
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(IMG_DIR, exist_ok=True)
    os.makedirs(DICT_DIR, exist_ok=True)
    os.makedirs(AUDIO_DIR, exist_ok=True)


# ===== CONFIG MANAGER =====
class ConfigManager:
    """
    Manages application configuration with automatic validation and persistence.

    Thread-safety: This class is NOT thread-safe. Use the singleton 'cfg' instance.
    """

    def __init__(self):
        _ensure_directories()  # Moved here from module level

        self.config = configparser.ConfigParser()
        if not os.path.exists(CONFIG_FILE):
            self._create_default()
        else:
            self.config.read(CONFIG_FILE, encoding='utf-8')
            self._validate()

    def _create_default(self):
        """Creates default configuration file"""
        for section, options in DEFAULT_CONFIG.items():
            self.config[section] = options
        self._save()

    def _validate(self):
        """
        Validates configuration integrity and adds missing keys.
        Critical for backward compatibility when adding new settings.
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
        """Persists configuration to disk"""
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            self.config.write(f)

    def get(self, section: str, key: str, fallback=None) -> str:
        """Retrieves configuration value as string"""
        return self.config.get(section, key, fallback=fallback)

    def get_bool(self, section: str, key: str, fallback=False) -> bool:
        """Retrieves configuration value as boolean"""
        return self.config.getboolean(section, key, fallback=fallback)

    def set(self, section: str, key: str, value) -> None:
        """
        Updates configuration value and saves to disk.

        Performance note: Every set() triggers file I/O. For batch updates,
        consider implementing set_batch() method.
        """
        if not self.config.has_section(section):
            self.config.add_section(section)
        self.config.set(section, key, str(value))
        self._save()


# ===== CACHE UTILITIES =====

def get_cache_size_mb() -> float:
    """
    Calculates total size of cache directory in megabytes.

    Optimizations:
    - Single os.walk() traversal
    - No redundant os.path.exists() checks (walk guarantees existence)
    - Graceful handling of inaccessible files

    Returns:
        Cache size in MB rounded to 1 decimal place
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
                    # File deleted/inaccessible during iteration - skip it
                    continue
    except OSError:
        # Root directory access error
        return 0.0

    return round(total_size / _MB, 1)


def clear_cache() -> int:
    """
    Deletes all cached files while preserving directory structure.

    Optimization: Uses os.scandir() instead of listdir() + isfile()
    - scandir() returns DirEntry objects with cached stat() results
    - Eliminates redundant system calls (2x performance improvement)

    Preserves:
    - vocab_10k.txt (in DATA_DIR root)
    - Directory structure

    Returns:
        Number of files successfully deleted
    """
    deleted_count = 0

    for subdir in (IMG_DIR, DICT_DIR, AUDIO_DIR):
        if not os.path.exists(subdir):
            continue

        try:
            # os.scandir() is 2-3x faster than os.listdir() + os.path.isfile()
            # because DirEntry caches stat() results
            with os.scandir(subdir) as entries:
                for entry in entries:
                    if entry.is_file():
                        try:
                            os.unlink(entry.path)
                            deleted_count += 1
                        except OSError:
                            # File locked/deleted by another process - skip
                            continue
        except OSError:
            # Directory access error - skip entire directory
            continue

    return deleted_count


# ===== SINGLETON INSTANCE =====
# CRITICAL: Import this singleton instead of creating new ConfigManager instances
# to avoid file I/O overhead and potential race conditions
cfg = ConfigManager()
