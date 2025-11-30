import requests
import os
import json
from urllib.parse import quote
from config import cfg, DICT_DIR, IMG_DIR, AUDIO_DIR


def get_cache_path(word):
    """Возвращает путь к кэшированному файлу данных слова"""
    safe_word = "".join(c for c in word if c.isalnum()).lower()
    return os.path.join(DICT_DIR, f"{safe_word}-full.json")


def get_google_tts_url(word: str, accent: str = "us") -> str:
    """
    Генерирует URL для Google TTS API
    accent: 'us' или 'uk'
    """
    lang_code = "en-US" if accent == "us" else "en-GB"
    encoded_word = quote(word)
    return f"https://translate.google.com/translate_tts?ie=UTF-8&tl={lang_code}&client=tw-ob&q={encoded_word}"


def get_audio_cache_path(word: str, accent: str = "us") -> str:
    """
    Возвращает путь для кэширования аудио
    Формат: {word}-{accent}.mp3
    """
    safe_word = "".join(c for c in word if c.isalnum()).lower()
    return os.path.join(AUDIO_DIR, f"{safe_word}-{accent}.mp3")


def download_and_cache_audio(url: str, cache_path: str):
    """
    Скачивает аудио и сохраняет по указанному пути
    """
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            with open(cache_path, "wb") as f:
                f.write(resp.content)
            return True
    except Exception as e:
        print(f"Audio download error: {e}")
    return False


def check_cache_only(word):
    """Проверяет наличие перевода только в кэше"""
    path = get_cache_path(word)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Возвращаем структуру, совместимую с UI
            return {
                "rus": data.get("rus", ""),
                "cached": True
            }
        except:
            pass
    return None


def load_full_dictionary_data(word):
    """Загружает полные данные словаря из кэша, если есть"""
    path = get_cache_path(word)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return None


def save_full_dictionary_data(word, data):
    """Сохраняет полные данные словаря в кэш"""
    path = get_cache_path(word)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Cache Save Error: {e}")


def fetch_full_dictionary_data(word):
    """
    Получает полные данные о слове (определения, фонетика)
    из Free Dictionary API + добавляет Google TTS fallback.
    """
    url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}"
    try:
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            data_list = resp.json()
            if data_list and isinstance(data_list, list):
                # Берем первый результат
                full_data = data_list[0]

                # Пытаемся найти русский перевод через Yandex
                rus_trans = fetch_yandex_translation(word)
                if rus_trans:
                    full_data["rus"] = rus_trans

                # Обогащаем phonetics Google TTS
                phonetics = full_data.get("phonetics", [])

                # Проверяем наличие US и UK аудио от dictionaryapi.dev
                has_us = any("-us.mp3" in p.get("audio", "").lower() for p in phonetics if p.get("audio"))
                has_uk = any("-uk.mp3" in p.get("audio", "").lower() for p in phonetics if p.get("audio"))

                # Добавляем Google TTS как fallback
                if not has_us:
                    phonetics.append({
                        "text": "",
                        "audio": get_google_tts_url(word, "us"),
                        "sourceUrl": "",
                        "license": {"name": "Google TTS", "url": ""}
                    })

                if not has_uk:
                    phonetics.append({
                        "text": "",
                        "audio": get_google_tts_url(word, "uk"),
                        "sourceUrl": "",
                        "license": {"name": "Google TTS", "url": ""}
                    })

                full_data["phonetics"] = phonetics

                save_full_dictionary_data(word, full_data)
                return full_data
    except Exception as e:
        print(f"Dict API Error: {e}")

    # Если API не сработало, проверяем, есть ли уже кэш
    return load_full_dictionary_data(word)


def fetch_yandex_translation(word):
    """Запрос перевода слова через Yandex Dictionary API"""
    key = cfg.get("API", "YandexKey")
    if not key: return None

    url = f"https://dictionary.yandex.net/api/v1/dicservice.json/lookup?key={key}&lang=en-ru&text={word}"
    try:
        resp = requests.get(url, timeout=3)
        if resp.status_code == 200:
            data = resp.json()
            if "def" in data and data["def"]:
                translations = []
                for definition in data["def"]:
                    for tr in definition.get("tr", []):
                        translations.append(tr["text"])
                return ", ".join(translations[:3])
    except Exception as e:
        print(f"Yandex API Error: {e}")
    return None


def fetch_google_translation(word):
    """
    НОВОЕ: Fallback-перевод через Google Translate для редких слов
    """
    try:
        url = "https://translate.googleapis.com/translate_a/single"
        params = {
            "client": "gtx",
            "sl": "en",
            "tl": "ru",
            "dt": "t",
            "q": word
        }
        resp = requests.get(url, params=params, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            # Собираем перевод из частей
            translated_text = "".join([item[0] for item in data[0] if item[0]])
            return translated_text.strip()
    except Exception as e:
        print(f"Google Translation Error: {e}")
    return None


def fetch_word_translation(word):
    """
    Получает перевод слова с многоуровневым fallback.
    1. Кэш полных данных (Yandex)
    2. API Yandex через fetch_full_dictionary_data
    3. НОВОЕ: Google Translate как последний fallback
    """
    # 1. Пробуем загрузить из кэша полных данных
    full_data = load_full_dictionary_data(word)
    if full_data and "rus" in full_data:
        return {"rus": full_data["rus"], "cached": True}

    # 2. Если нет, запрашиваем полные данные (они внутри запросят Яндекс)
    full_data = fetch_full_dictionary_data(word)
    if full_data and "rus" in full_data:
        return {"rus": full_data["rus"], "cached": False}

    # 3. НОВОЕ: Fallback на Google Translate
    google_trans = fetch_google_translation(word)
    if google_trans:
        # Сохраняем в кэш для будущего использования
        if full_data:
            full_data["rus"] = google_trans
            save_full_dictionary_data(word, full_data)
        return {"rus": google_trans, "cached": False}

    # 4. Если совсем ничего нет
    return None


def get_image_path(word):
    """Возвращает путь для сохранения изображения слова"""
    safe_word = "".join(c for c in word if c.isalnum()).lower()
    return os.path.join(IMG_DIR, f"{safe_word}.jpg")


def download_image(url, word):
    """Скачивает и сохраняет изображение с понятным именем"""
    # Убеждаемся что папка существует
    os.makedirs(IMG_DIR, exist_ok=True)

    # User-Agent обязателен для Wikimedia и многих других серверов
    headers = {
        "User-Agent": "EnglishHelper/1.0 (Educational App; Python/requests)"
    }

    try:
        resp = requests.get(url, headers=headers, timeout=5)
        if resp.status_code == 200:
            path = get_image_path(word)
            with open(path, "wb") as f:
                f.write(resp.content)

            if os.path.exists(path):
                return path
    except Exception as e:
        print(f"Download Error: {e}")
    return None


def fetch_pexels_image(word):
    """Поиск изображения в Pexels"""
    key = cfg.get("API", "PexelsKey")
    if not key:
        # Проверяем, есть ли уже сохраненное изображение (если ключа нет)
        cached_path = get_image_path(word)
        if os.path.exists(cached_path):
            return cached_path
        return None

    # Сначала проверяем кэш
    cached_path = get_image_path(word)
    if os.path.exists(cached_path):
        return cached_path

    url = f"https://api.pexels.com/v1/search?query={word}&per_page=1"
    headers = {"Authorization": key}
    try:
        resp = requests.get(url, headers=headers, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("photos"):
                img_url = data["photos"][0]["src"]["medium"]
                return download_image(img_url, word)
    except Exception as e:
        print(f"Pexels Error: {e}")
    return None


def fetch_wiki_image(word):
    """Поиск изображения в Wikipedia с фильтрацией логотипов"""

    url = f"https://en.wikipedia.org/w/api.php?action=query&titles={word}&prop=pageimages&format=json&pithumbsize=500"

    # User-Agent обязателен для Wikipedia API
    headers = {
        "User-Agent": "EnglishHelper/1.0 (Educational App; Python/requests)"
    }

    # Расширенный список нежелательных паттернов
    BLACKLIST = [
        # Служебные иконки Wikipedia
        "Commons-logo", "Disambig", "Ambox", "Wiki_letter",
        "Question_book", "Folder", "Decrease", "Increase",
        "Edit-clear", "Symbol", "Icon",

        # Placeholder и отсутствующие изображения
        "No_image", "Image_missing", "Placeholder", "Replace_this",

        # Другие Wiki-проекты
        "Wiktionary", "Wikiquote", "Wikibooks", "Wikisource",

        # Геральдика (часто нерелевантна для обучения языку)
        "Flag_of", "Coat_of_arms", "Emblem",

        # Стандартные иконки KDE/GNOME
        "Crystal", "Nuvola", "Tango",

        # SVG логотипы
        ".svg"
    ]

    try:
        resp = requests.get(url, headers=headers, timeout=5)

        if resp.status_code == 200:
            data = resp.json()
            pages = data.get("query", {}).get("pages", {})

            for page_id in pages:
                # Пропускаем disambiguation pages (ID = -1)
                if page_id == "-1":
                    continue

                page = pages[page_id]

                # Проверяем наличие thumbnail
                if "thumbnail" not in page:
                    continue

                thumbnail = page["thumbnail"]
                img_url = thumbnail.get("source", "")

                if not img_url:
                    continue

                # Проверяем URL на наличие нежелательных паттернов
                if any(bad.lower() in img_url.lower() for bad in BLACKLIST):
                    continue

                # Проверяем минимальный размер (избегаем маленькие иконки)
                width = thumbnail.get("width", 0)
                height = thumbnail.get("height", 0)

                if width < 100 or height < 100:
                    continue

                return download_image(img_url, word)

    except Exception as e:
        print(f"Wiki Error: {e}")

    return None


def fetch_image(word):
    """
    Главная функция поиска изображения.
    Приоритет: Pexels -> Wikipedia
    """
    # 1. Сначала Pexels (лучшее качество для людей/природы)
    path = fetch_pexels_image(word)
    if path: return path, "Pexels"

    # 2. Затем Википедия (для терминов, знаменитостей)
    path = fetch_wiki_image(word)
    if path: return path, "Wiki"

    return None, "None"


def fetch_sentence_translation(text):
    """
    Перевод текста (для предложений и тултипов).
    БЕЗ кэша - всегда делает запрос к API.
    """
    text = text.strip()
    if not text: return ""

    try:
        # Используем публичный API Google Translate
        url = "https://translate.googleapis.com/translate_a/single"
        params = {
            "client": "gtx",
            "sl": "en",
            "tl": "ru",
            "dt": "t",
            "q": text
        }
        resp = requests.get(url, params=params, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            # Собираем перевод из частей
            translated_text = "".join([item[0] for item in data[0] if item[0]])
            return translated_text
    except Exception as e:
        print(f"Translation Error: {e}")

    return None
