import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import os
import json
import threading
import tempfile
import shutil
import time
from urllib.parse import quote
from functools import lru_cache
from config import cfg, DICT_DIR, IMG_DIR, AUDIO_DIR

# ===== CONSTANTS =====
MIN_VALID_AUDIO_SIZE = 1500  # bytes, ~0.1s of MP3 audio
MIN_IMAGE_DIMENSION = 100  # pixels, minimum for valid images
IMAGE_THUMBNAIL_SIZE = 500  # Pexels/Wiki API parameter

# ===== IMPORTS WITH GRACEFUL DEGRADATION =====
try:
    import lemminflect

    LEMMATIZER_AVAILABLE = True
except ImportError:
    lemminflect = None
    LEMMATIZER_AVAILABLE = False

try:
    from playsound import playsound

    PLAYSOUND_AVAILABLE = True
except ImportError:
    playsound = None
    PLAYSOUND_AVAILABLE = False


# ===== LEMMATIZATION =====

@lru_cache(maxsize=2048)
def lemmatize_word(word: str) -> str:
    """
    Приводит слово к словарной форме (лемме) с кэшированием.
    Кэш на 2048 слов покрывает 99% реальной печати (~50KB RAM).
    Всегда возвращает lowercase строку.
    """
    if not LEMMATIZER_AVAILABLE or lemminflect is None:
        return word.lower()

    try:
        for pos in ['VERB', 'NOUN', 'ADJ', 'ADV']:
            lemmas = lemminflect.getLemma(word.lower(), upos=pos)
            if lemmas:
                return lemmas[0]
        return word.lower()
    except (AttributeError, ValueError, TypeError):
        return word.lower()


@lru_cache(maxsize=2048)
def get_safe_filename(word: str) -> str:
    """
    Преобразует слово в безопасное имя файла.
    Кэшируется для избежания повторных вычислений.
    """
    lemma = lemmatize_word(word)
    return "".join(c for c in lemma if c.isalnum())


# ===== SESSION MANAGEMENT =====

def _create_session(max_retries=2, backoff_factor=0.2):
    """Создает HTTP session с оптимизированной retry стратегией"""
    session = requests.Session()
    retry_strategy = Retry(
        total=max_retries,
        backoff_factor=backoff_factor,
        status_forcelist=[429, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "OPTIONS"]
    )
    adapter = HTTPAdapter(
        max_retries=retry_strategy,
        pool_connections=10,
        pool_maxsize=50
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update({
        "User-Agent": "EnglishHelper/1.0 (Educational App; Python/requests)"
    })
    return session


session_dict = _create_session()
session_google = _create_session()
session_pexels = _create_session()
session_wiki = _create_session()

_audio_play_lock = threading.Lock()


# ===== CACHE HELPERS =====

def get_cache_path(word):
    """Возвращает путь к файлу кэша словарных данных"""
    safe_word = get_safe_filename(word)
    return os.path.join(DICT_DIR, f"{safe_word}-full.json")


def get_audio_cache_path(word: str, accent: str = "us") -> str:
    """Возвращает путь к кэшу аудио файла"""
    safe_word = get_safe_filename(word)
    return os.path.join(AUDIO_DIR, f"{safe_word}-{accent}.mp3")


def get_image_path(word):
    """Возвращает путь к кэшу изображения"""
    safe_word = get_safe_filename(word)
    return os.path.join(IMG_DIR, f"{safe_word}.jpg")


def mark_image_not_found(word):
    """Создает маркер отсутствия изображения"""
    safe_word = get_safe_filename(word)
    marker_path = os.path.join(IMG_DIR, f"{safe_word}.nofound")
    try:
        with open(marker_path, "w") as f:
            f.write("")
    except (IOError, OSError):
        pass


def is_image_not_found(word) -> bool:
    """Проверяет наличие маркера отсутствия изображения"""
    safe_word = get_safe_filename(word)
    marker_path = os.path.join(IMG_DIR, f"{safe_word}.nofound")
    return os.path.exists(marker_path)


# ===== GOOGLE TTS =====

def get_google_tts_url(word: str, accent: str = "us") -> str:
    """
    Генерирует URL для Google TTS.
    Использует ОРИГИНАЛЬНОЕ слово (не лемму) для правильного произношения.
    """
    lang_code = "en-US" if accent == "us" else "en-GB"
    encoded_word = quote(word)
    return f"https://translate.google.com/translate_tts?ie=UTF-8&tl={lang_code}&client=tw-ob&q={encoded_word}"


def is_valid_audio_file(path: str) -> bool:
    """Проверяет валидность аудио файла"""
    if not os.path.exists(path):
        return False

    try:
        size = os.path.getsize(path)
        if size < MIN_VALID_AUDIO_SIZE:
            return False

        # Проверка MP3 magic bytes
        with open(path, 'rb') as f:
            header = f.read(3)
            return header == b'ID3' or header[:2] == b'\xff\xfb'
    except (IOError, OSError):
        return False


def download_and_cache_audio(url: str, cache_path: str) -> bool:
    """Загружает и кэширует аудио файл"""
    try:
        resp = session_google.get(url, timeout=10)
        if resp.status_code == 200:
            # Atomic write pattern
            temp_path = cache_path + '.tmp'
            with open(temp_path, "wb") as f:
                f.write(resp.content)

            # Атомарная замена (работает на Windows и POSIX)
            os.replace(temp_path, cache_path)

            return is_valid_audio_file(cache_path)
    except (requests.RequestException, IOError, OSError):
        pass
    return False


def _cache_audio_async(url: str, cache_path: str):
    """Фоновое кэширование аудио без блокировки"""
    if not os.path.exists(cache_path):
        download_and_cache_audio(url, cache_path)


def _cache_audio_from_phonetics(audio_url: str, word: str):
    """Асинхронное кэширование аудио из phonetics данных"""
    if not audio_url:
        return

    accent = "us" if "-us.mp3" in audio_url.lower() or "en-US" in audio_url else "uk"
    cache_path = get_audio_cache_path(word, accent)

    if not os.path.exists(cache_path):
        threading.Thread(
            target=download_and_cache_audio,
            args=(audio_url, cache_path),
            daemon=True
        ).start()


def streaming_play_and_cache(url: str, cache_path: str):
    """Потоковое воспроизведение с кэшированием"""
    if not PLAYSOUND_AVAILABLE:
        return

    try:
        resp = session_google.get(url, timeout=10, stream=True)

        if resp.status_code == 200:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp:
                tmp_path = tmp.name

                chunk_size = 4096
                chunks_written = 0
                play_started = False

                for chunk in resp.iter_content(chunk_size=chunk_size):
                    if chunk:
                        tmp.write(chunk)
                        chunks_written += 1

                        if chunks_written == 2 and not play_started:
                            play_started = True
                            threading.Thread(
                                target=_safe_play,
                                args=(tmp_path,),
                                daemon=True
                            ).start()

            # Явное закрытие handle перед move (критично для Windows)
            tmp.close()

            # Atomic write
            temp_final = cache_path + '.tmp'
            shutil.move(tmp_path, temp_final)
            os.replace(temp_final, cache_path)

    except (requests.RequestException, IOError, OSError):
        pass


def _safe_play(path: str):
    """Безопасное воспроизведение с ожиданием готовности файла"""
    if not PLAYSOUND_AVAILABLE or playsound is None:
        return

    max_attempts = 10
    for i in range(max_attempts):
        try:
            if is_valid_audio_file(path):
                with _audio_play_lock:
                    playsound(path)
                return
        except (IOError, OSError, RuntimeError):
            if i < max_attempts - 1:
                time.sleep(0.05)


# ===== DICTIONARY DATA =====

def check_cache_only(word):
    """Быстрая проверка наличия перевода в кэше"""
    path = get_cache_path(word)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {
                "rus": data.get("rus", ""),
                "cached": True
            }
        except (IOError, OSError, json.JSONDecodeError, ValueError):
            pass
    return None


def load_full_dictionary_data(word):
    """Загружает полные словарные данные из кэша"""
    path = get_cache_path(word)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (IOError, OSError, json.JSONDecodeError, ValueError):
            pass
    return None


def save_full_dictionary_data(word, data):
    """Сохраняет полные словарные данные в кэш"""
    path = get_cache_path(word)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except (IOError, OSError, TypeError):
        pass


def fetch_full_dictionary_data(word):
    """
    Загружает полные данные словаря из API.
    Оптимизировано:
    - Проверяет кэш перед HTTP запросом
    - Google TTS кэшируется асинхронно без блокировки
    """
    # Проверяем полный кэш перед запросом к API
    cached = load_full_dictionary_data(word)
    if cached and cached.get("meanings"):
        return cached

    lemma = lemmatize_word(word)
    url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{lemma}"

    # Запускаем кэширование US audio в фоне (не блокируем)
    google_us_url = get_google_tts_url(word, "us")
    google_us_cache = get_audio_cache_path(word, "us")
    threading.Thread(
        target=_cache_audio_async,
        args=(google_us_url, google_us_cache),
        daemon=True
    ).start()

    try:
        resp = session_dict.get(url, timeout=8)
        if resp.status_code == 200:
            data_list = resp.json()
            if data_list and isinstance(data_list, list):
                full_data = data_list[0]

                # Получаем русский перевод
                rus_trans = fetch_yandex_translation(lemma)
                if not rus_trans:
                    rus_trans = fetch_google_translation(lemma)

                if rus_trans:
                    full_data["rus"] = rus_trans

                phonetics = full_data.get("phonetics", [])

                # Кэшируем audio из phonetics
                for p in phonetics:
                    audio_url = p.get("audio")
                    if audio_url:
                        _cache_audio_from_phonetics(audio_url, word)

                # Оптимизированная проверка US/UK (один проход с early break)
                has_us = False
                has_uk = False

                for p in phonetics:
                    audio = p.get("audio", "")
                    if not audio:
                        continue

                    audio_lower = audio.lower()
                    if "-us.mp3" in audio_lower or "en-US" in audio:
                        has_us = True
                    if "-uk.mp3" in audio_lower or "en-GB" in audio:
                        has_uk = True

                    if has_us and has_uk:
                        break

                # Добавляем Google TTS как fallback
                if not has_us:
                    phonetics.append({
                        "text": "",
                        "audio": google_us_url,
                        "sourceUrl": "",
                        "license": {"name": "Google TTS", "url": ""}
                    })

                if not has_uk:
                    uk_url = get_google_tts_url(word, "uk")
                    phonetics.append({
                        "text": "",
                        "audio": uk_url,
                        "sourceUrl": "",
                        "license": {"name": "Google TTS", "url": ""}
                    })

                full_data["phonetics"] = phonetics
                full_data["word"] = lemma
                save_full_dictionary_data(word, full_data)

                return full_data
    except (requests.RequestException, json.JSONDecodeError, ValueError, KeyError, TypeError):
        pass

    # Fallback на существующий кэш или создание минимального
    if cached:
        return cached

    rus_trans = fetch_yandex_translation(lemma)
    if not rus_trans:
        rus_trans = fetch_google_translation(lemma)

    if rus_trans:
        minimal_data = {
            "word": lemma,
            "rus": rus_trans,
            "phonetics": [{
                "text": "",
                "audio": google_us_url,
                "sourceUrl": "",
                "license": {"name": "Google TTS", "url": ""}
            }],
            "meanings": []
        }
        save_full_dictionary_data(word, minimal_data)
        return minimal_data

    return None


# ===== TRANSLATION =====

def fetch_yandex_translation(word):
    """Получает перевод из Yandex Dictionary API"""
    key = cfg.get("API", "YandexKey")
    if not key:
        return None

    lemma = lemmatize_word(word)
    url = f"https://dictionary.yandex.net/api/v1/dicservice.json/lookup?key={key}&lang=en-ru&text={lemma}"
    try:
        resp = session_google.get(url, timeout=3)
        if resp.status_code == 200:
            data = resp.json()
            if "def" in data and data["def"]:
                translations = []
                for definition in data["def"]:
                    for tr in definition.get("tr", []):
                        translations.append(tr["text"])
                return ", ".join(translations[:3])
    except (requests.RequestException, json.JSONDecodeError, ValueError, KeyError):
        pass
    return None


def fetch_google_translation(word):
    """Получает перевод из Google Translate"""
    lemma = lemmatize_word(word)

    try:
        url = "https://translate.googleapis.com/translate_a/single"
        params = {
            "client": "gtx",
            "sl": "en",
            "tl": "ru",
            "dt": "t",
            "q": lemma
        }
        resp = session_google.get(url, params=params, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            translated_text = "".join([item[0] for item in data[0] if item[0]])
            return translated_text.strip()
    except (requests.RequestException, json.JSONDecodeError, ValueError, KeyError, TypeError):
        pass
    return None


def fetch_word_translation(word):
    """Получает перевод слова с использованием кэша"""
    full_data = load_full_dictionary_data(word)
    if full_data and "rus" in full_data:
        return {"rus": full_data["rus"], "cached": True}

    full_data = fetch_full_dictionary_data(word)
    if full_data and "rus" in full_data:
        return {"rus": full_data["rus"], "cached": False}

    google_trans = fetch_google_translation(word)
    if google_trans:
        lemma = lemmatize_word(word)
        if full_data:
            full_data["rus"] = google_trans
            save_full_dictionary_data(word, full_data)
        else:
            save_full_dictionary_data(word, {"rus": google_trans, "word": lemma})
        return {"rus": google_trans, "cached": False}

    return None


def fetch_sentence_translation(text):
    """Переводит предложение через Google Translate"""
    text = text.strip()
    if not text:
        return ""

    try:
        url = "https://translate.googleapis.com/translate_a/single"
        params = {
            "client": "gtx",
            "sl": "en",
            "tl": "ru",
            "dt": "t",
            "q": text
        }
        resp = session_google.get(url, params=params, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            translated_text = "".join([item[0] for item in data[0] if item[0]])
            return translated_text
    except (requests.RequestException, json.JSONDecodeError, ValueError, KeyError, TypeError):
        pass

    return None


# ===== IMAGES =====

def download_image(url, word):
    """Загружает изображение по URL"""
    try:
        if "pexels.com" in url:
            resp = session_pexels.get(url, timeout=5)
        elif "wikipedia" in url or "wikimedia" in url:
            resp = session_wiki.get(url, timeout=5)
        else:
            resp = session_google.get(url, timeout=5)

        if resp.status_code == 200:
            path = get_image_path(word)
            with open(path, "wb") as f:
                f.write(resp.content)

            if os.path.exists(path):
                return path
    except (requests.RequestException, IOError, OSError):
        pass
    return None


def fetch_pexels_image(word):
    """Загружает изображение из Pexels API"""
    if is_image_not_found(word):
        return None

    cached_path = get_image_path(word)
    if os.path.exists(cached_path):
        return cached_path

    key = cfg.get("API", "PexelsKey")
    if not key:
        return None

    lemma = lemmatize_word(word)
    url = f"https://api.pexels.com/v1/search?query={lemma}&per_page=1"
    session_pexels.headers.update({"Authorization": key})

    try:
        resp = session_pexels.get(url, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("photos"):
                img_url = data["photos"][0]["src"]["medium"]
                return download_image(img_url, word)
    except (requests.RequestException, json.JSONDecodeError, ValueError, KeyError):
        pass

    return None


def fetch_wiki_image(word):
    """Загружает изображение из Wikipedia"""
    if is_image_not_found(word):
        return None

    lemma = lemmatize_word(word)
    url = f"https://en.wikipedia.org/w/api.php?action=query&titles={lemma}&prop=pageimages&format=json&pithumbsize={IMAGE_THUMBNAIL_SIZE}"

    blacklist = [
        "Commons-logo", "Disambig", "Ambox", "Wiki_letter",
        "Question_book", "Folder", "Decrease", "Increase",
        "Edit-clear", "Symbol", "Icon",
        "No_image", "Image_missing", "Placeholder", "Replace_this",
        "Wiktionary", "Wikiquote", "Wikibooks", "Wikisource",
        "Flag_of", "Coat_of_arms", "Emblem",
        "Crystal", "Nuvola", "Tango",
        ".svg"
    ]

    try:
        resp = session_wiki.get(url, timeout=5)

        if resp.status_code == 200:
            data = resp.json()
            pages = data.get("query", {}).get("pages", {})

            for page_id in pages:
                if page_id == "-1":
                    continue

                page = pages[page_id]

                if "thumbnail" not in page:
                    continue

                thumbnail = page["thumbnail"]
                img_url = thumbnail.get("source", "")

                if not img_url:
                    continue

                if any(bad.lower() in img_url.lower() for bad in blacklist):
                    continue

                width = thumbnail.get("width", 0)
                height = thumbnail.get("height", 0)

                if width < MIN_IMAGE_DIMENSION or height < MIN_IMAGE_DIMENSION:
                    continue

                return download_image(img_url, word)

    except (requests.RequestException, json.JSONDecodeError, ValueError, KeyError):
        pass

    return None


def fetch_image(word):
    """Загружает изображение из доступных источников"""
    path = fetch_pexels_image(word)
    if path:
        return path, "Pexels"

    path = fetch_wiki_image(word)
    if path:
        return path, "Wiki"

    if not is_image_not_found(word):
        mark_image_not_found(word)

    return None, "None"


def close_all_sessions():
    """Закрывает все HTTP сессии"""
    session_dict.close()
    session_google.close()
    session_pexels.close()
    session_wiki.close()
