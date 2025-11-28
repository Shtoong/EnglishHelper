import os
import sys
import configparser

if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DATA_DIR = os.path.join(BASE_DIR, "Data")
IMG_DIR = os.path.join(DATA_DIR, "Images")
DICT_DIR = os.path.join(DATA_DIR, "Dict")
VOCAB_FILE = os.path.join(DATA_DIR, "vocab_10k.txt")
SETTINGS_FILE = os.path.join(BASE_DIR, "settings.ini")

for d in [DATA_DIR, IMG_DIR, DICT_DIR]:
    os.makedirs(d, exist_ok=True)

DEFAULT_CONFIG = {
    "API": {"PexelsKey": "", "YandexKey": ""},
    "USER": {
        "VocabLevel": "10", 
        "WindowX": "100", "WindowY": "100",
        "WindowSentX": "450", "WindowSentY": "100",
        "ShowSentenceWindow": "True"  # <--- НОВАЯ НАСТРОЙКА
    }
}

class ConfigManager:
    def __init__(self):
        self.config = configparser.ConfigParser()
        self._load()

    def _load(self):
        if not os.path.exists(SETTINGS_FILE):
            self.config.read_dict(DEFAULT_CONFIG)
            self.save()
        else:
            self.config.read(SETTINGS_FILE)
            changed = False
            for section in DEFAULT_CONFIG:
                if section not in self.config:
                    self.config[section] = DEFAULT_CONFIG[section]
                    changed = True
                for key in DEFAULT_CONFIG[section]:
                    if key not in self.config[section]:
                        self.config[section][key] = DEFAULT_CONFIG[section][key]
                        changed = True
            if changed:
                self.save()

    def get(self, section, key, fallback=None):
        return self.config.get(section, key, fallback=fallback)
    
    def get_bool(self, section, key, fallback=True):
        val = self.config.get(section, key, fallback=str(fallback))
        return val.lower() == 'true'

    def set(self, section, key, value):
        if section not in self.config:
            self.config[section] = {}
        self.config[section][str(key)] = str(value)
        self.save()

    def save(self):
        with open(SETTINGS_FILE, 'w') as f:
            self.config.write(f)

cfg = ConfigManager()
