"""
Модуль сетевых операций для EnglishHelper.

Обрабатывает:
- HTTP запросы к API (DictionaryAPI, Yandex, Google, Pexels, Wiki)
- Кэширование данных (переводы, meanings, аудио, изображения)
- Атомарная запись файлов с защитой от race conditions
- Graceful degradation при отсутствии зависимостей

КРИТИЧНО:
- Кэш переводов отделён от meanings (word-trans.json vs word-full.json)
- phonetics НЕ сохраняются в кэш (лишние данные)
- Все операции записи защищены _cache_write_lock
"""

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import os
import json
import threading
import tempfile
import shutil
import time
import datetime
from urllib.parse import quote
from functools import lru_cache
import hashlib
from typing import Optional, Dict, Tuple

from config import cfg, DICT_DIR, IMG_DIR, AUDIO_DIR, TEMP_AUDIO_DIR

# ===== НАСТРОЙКИ ОТЛАДКИ =====
#DEBUG_NETWORK = False  # <--- ВКЛЮЧИТЕ FALSE, ЧТОБЫ УБРАТЬ ЛОГИ В КОНСОЛИ
DEBUG_NETWORK = True  # <--- ВКЛЮЧИТЕ True, ЧТОБЫ ПОКАЗАТЬ ЛОГИ В КОНСОЛИ

# ===== КОНСТАНТЫ =====
MIN_VALID_AUDIO_SIZE = 1500  # bytes, ~0.1s of MP3 audio
MIN_IMAGE_DIMENSION = 100  # pixels, минимум для валидных изображений
IMAGE_THUMBNAIL_SIZE = 500  # Pexels/Wiki API параметр

# ===== ИМПОРТЫ С GRACEFUL DEGRADATION =====
try:
    from playsound import playsound
    PLAYSOUND_AVAILABLE = True
except ImportError:
    playsound = None
    PLAYSOUND_AVAILABLE = False

# ===== ОЧИСТКА СЛОВ =====
@lru_cache(maxsize=2048)
def get_safe_filename(word: str) -> str:
    """
    Преобразует слово в безопасное имя файла.
    Очищает слово: только английские буквы, lowercase, только alnum для файла.
    Кэшируется для избежания повторных вычислений.
    """
    cleaned = ''.join(c for c in word if c.isalpha() and ord(c) < 128)
    word_lower = cleaned.lower()
    return "".join(c for c in word_lower if c.isalnum())

# ===== УПРАВЛЕНИЕ СЕССИЯМИ =====
def _create_session(max_retries=2, backoff_factor=0.2):
    """Создает HTTP session с логгером и retry стратегией"""
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

    # ===== ЛОГИРОВАНИЕ ЗАПРОСОВ (HOOKS) =====
    if DEBUG_NETWORK:
        def log_request(response, *args, **kwargs):
            # Точное время получения ответа
            now = datetime.datetime.now()
            # Вычисляем время начала (приблизительно)
            start_time = now - response.elapsed

            # Форматирование метода и URL
            method = response.request.method
            url = response.url
            if len(url) > 250:
                url = url[:247] + "..."

            print(f"[{start_time.strftime('%H:%M:%S.%f')[:-3]}] 🌐 -> REQ: {method} {url}")
            print(f"[{now.strftime('%H:%M:%S.%f')[:-3]}] 📥 <- RES: {response.status_code} (took {response.elapsed.total_seconds():.3f}s)")

        # Подключаем хук ко всем ответам этой сессии
        session.hooks['response'] = [log_request]

    return session

# Глобальные сессии для переиспользования соединений
session_dict = _create_session()
session_google = _create_session()
session_pexels = _create_session()
session_wiki = _create_session()

# ===== THREAD SAFETY =====
_audio_play_lock = threading.Lock()
_cache_write_lock = threading.Lock()  # ✅ ДОБАВЛЕНО: Защита от race condition

# ===== КЭШИРОВАНИЕ GOOGLE TTS TOKEN =====
_google_tts_token_cache = {
    "token": None,
    "expiry": None
}

# ===== ХЕЛПЕРЫ КЭША =====
def get_cache_path(word: str) -> str:
    """Возвращает путь к файлу кэша meanings (dictionaryapi.dev)"""
    safe_word = get_safe_filename(word)
    return os.path.join(DICT_DIR, f"{safe_word}-full.json")

def get_translation_cache_path(word: str) -> str:
    """
    Возвращает путь к файлу кэша переводов (Яндекс/Google).
    ✅ НОВАЯ ФУНКЦИЯ для разделения кэша!
    """
    safe_word = get_safe_filename(word)
    return os.path.join(DICT_DIR, f"{safe_word}-trans.json")

def get_audio_cache_path(word: str, accent: str = "us") -> str:
    """Возвращает путь к кэшу аудио файла"""
    safe_word = get_safe_filename(word)
    return os.path.join(AUDIO_DIR, f"{safe_word}-{accent}.mp3")

def get_temp_audio_path(text: str) -> str:
    """
    Возвращает путь к временному аудиофайлу на основе хэша текста.
    Используется для предложений/определений (use_cache=False).
    """
    text_hash = hashlib.md5(text.encode('utf-8')).hexdigest()[:16]
    return os.path.join(TEMP_AUDIO_DIR, f"{text_hash}.mp3")

def get_image_path(word: str) -> str:
    """Возвращает путь к кэшу изображения"""
    safe_word = get_safe_filename(word)
    return os.path.join(IMG_DIR, f"{safe_word}.jpg")

def mark_image_not_found(word: str):
    """Создает маркер отсутствия изображения"""
    safe_word = get_safe_filename(word)
    marker_path = os.path.join(IMG_DIR, f"{safe_word}.nofound")
    try:
        with open(marker_path, "w") as f:
            f.write("")
    except (IOError, OSError):
        pass

def is_image_not_found(word: str) -> bool:
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
    """Проверяет валидность аудио файла (УПРОЩЕННАЯ ВЕРСИЯ)"""
    if not os.path.exists(path):
        return False
    try:
        size = os.path.getsize(path)
        # Просто проверяем, что файл не пустой (больше 1Кб)
        return size > 1024
    except (IOError, OSError):
        return False

def download_and_cache_audio(url: str, cache_path: str) -> bool:
    """Загружает и кэширует аудио файл с атомарной записью"""
    try:
        resp = session_google.get(url, timeout=10)
        if resp.status_code == 200:
            # Атомарная запись через временный файл
            temp_path = cache_path + '.tmp'
            with open(temp_path, "wb") as f:
                f.write(resp.content)

            # Атомарная замена (работает на Windows и POSIX)
            os.replace(temp_path, cache_path)
            return is_valid_audio_file(cache_path)
    except (requests.RequestException, IOError, OSError):
        pass
    return False


def _is_single_word(text: str) -> bool:
    """
    Проверяет является ли текст одним словом (только английские буквы).

    Args:
        text: Текст для проверки

    Returns:
        True если текст содержит только английские буквы (одно слово),
        False если есть пробелы, знаки препинания или другие символы
    """
    # Убираем пробелы по краям
    cleaned = text.strip()

    # Проверяем что все символы - английские буквы
    return bool(cleaned) and all(c.isalpha() and ord(c) < 128 for c in cleaned)


def fetch_google_official_tts(text: str, use_cache: bool = True) -> Optional[str]:
    """
    Загружает аудио через официальный Google Cloud Text-to-Speech REST API.
    Использует Service Account credentials с кэшированием токена.

    УМНАЯ ЛОГИКА:
    1. Автоматически определяет: слово или предложение (по наличию не-букв)
    2. Слова → GoogleTTSVoiceWord + GoogleTTSSpeedWord, кэшируются в AUDIO_DIR
    3. Предложения → GoogleTTSVoiceSentence + GoogleTTSSpeedSentence, в TEMP_AUDIO_DIR
    4. Параметр use_cache сохранён для обратной совместимости (игнорируется)

    Args:
        text: Текст для озвучки
        use_cache: (игнорируется) Кэширование определяется автоматически

    Returns:
        Путь к аудиофайлу или None при ошибке
    """
    credentials_file = cfg.get("API", "GoogleTTSCredentials")
    if not credentials_file or not os.path.exists(credentials_file):
        return None

    # Умное определение: слово или предложение?
    is_word = _is_single_word(text)

    # Определяем путь, голос и скорость в зависимости от типа текста
    if is_word:
        # СЛОВО: кэшируем в AUDIO_DIR, используем голос и скорость для слов
        safe_word = get_safe_filename(text)
        cache_path = os.path.join(AUDIO_DIR, f"{safe_word}-us-official.mp3")
        voice_name = cfg.get("API", "GoogleTTSVoiceWord", fallback="en-US-Neural2-J")
        speed = float(cfg.get("API", "GoogleTTSSpeedWord", fallback="1.0"))
    else:
        # ПРЕДЛОЖЕНИЕ: временный файл в TEMP_AUDIO_DIR, используем голос и скорость для предложений
        cache_path = get_temp_audio_path(text)
        voice_name = cfg.get("API", "GoogleTTSVoiceSentence", fallback="en-US-Neural2-C")
        speed = float(cfg.get("API", "GoogleTTSSpeedSentence", fallback="0.9"))

    # Быстрая проверка кэша
    if os.path.exists(cache_path) and is_valid_audio_file(cache_path):
        return cache_path

    try:
        # Получаем или обновляем access token
        now = datetime.datetime.now()

        # Проверяем кэш токена
        if (_google_tts_token_cache["token"] is None or
                _google_tts_token_cache["expiry"] is None or
                now >= _google_tts_token_cache["expiry"]):
            # Загружаем credentials из JSON файла
            with open(credentials_file, 'r') as f:
                credentials_data = json.load(f)

            # Получаем новый access token
            from google.oauth2 import service_account
            from google.auth.transport.requests import Request

            credentials = service_account.Credentials.from_service_account_info(
                credentials_data,
                scopes=['https://www.googleapis.com/auth/cloud-platform']
            )

            credentials.refresh(Request())

            # Кэшируем токен (срок действия обычно 1 час)
            _google_tts_token_cache["token"] = credentials.token
            _google_tts_token_cache["expiry"] = now + datetime.timedelta(minutes=55)

        access_token = _google_tts_token_cache["token"]

        # REST API URL (без API key)
        url = "https://texttospeech.googleapis.com/v1/text:synthesize"

        # Формируем JSON тело запроса
        request_body = {
            "input": {"text": text},
            "voice": {
                "languageCode": "en-US",
                "name": voice_name  # Автоматически выбранный голос
            },
            "audioConfig": {
                "audioEncoding": "MP3",
                "speakingRate": speed  # Автоматически выбранная скорость
            }
        }

        # Отправляем POST запрос с Bearer token
        response = session_google.post(
            url,
            json=request_body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {access_token}"
            },
            timeout=10
        )

        if response.status_code == 200:
            result = response.json()

            # Аудио возвращается в base64
            import base64
            audio_content = base64.b64decode(result["audioContent"])

            # Атомарное сохранение
            temp_path = cache_path + '.tmp'
            with open(temp_path, "wb") as f:
                f.write(audio_content)

            os.replace(temp_path, cache_path)

            if is_valid_audio_file(cache_path):
                return cache_path
        else:
            if DEBUG_NETWORK:
                print(f"DEBUG: Google Official TTS HTTP {response.status_code}: {response.text}")

    except Exception as e:
        if DEBUG_NETWORK:
            print(f"DEBUG: Google Official TTS error: {e}")

    return None


def streaming_play_and_cache(url: str, cache_path: str):
    """Потоковое воспроизведение с одновременным кэшированием"""
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

                        # Начинаем воспроизведение после 2 чанков
                        if chunks_written == 2 and not play_started:
                            play_started = True
                            threading.Thread(
                                target=_safe_play,
                                args=(tmp_path,),
                                daemon=True
                            ).start()

                # Явное закрытие handle перед move (критично для Windows)
                tmp.close()

                # Атомарная запись
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

# ═══════════════════════════════════════════════════════════════════════════
# СЛОВАРНЫЕ ДАННЫЕ (MEANINGS)
# ═══════════════════════════════════════════════════════════════════════════

def load_full_dictionary_data(word: str) -> Optional[Dict]:
    """
    Загружает meanings из кэша.
    Returns:
        Словарные данные (БЕЗ перевода) или None
    """
    path = get_cache_path(word)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (IOError, OSError, json.JSONDecodeError, ValueError):
            pass
    return None

def save_full_dictionary_data(word: str, data: Dict):
    """
    Сохраняет meanings в кэш с атомарной записью.
    ✅ Защищено от race condition через _cache_write_lock
    """
    path = get_cache_path(word)
    with _cache_write_lock:
        try:
            temp_path = path + '.tmp'
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(temp_path, path)
        except (IOError, OSError):
            pass

def fetch_dictionary_meanings_only(word: str) -> Optional[Dict]:
    """
    Запрашивает данные у DictionaryAPI.
    Возвращает структуру с meanings/phonetics.
    Кэширует результат (даже пустой), чтобы не долбить API зря.
    """
    url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}"
    try:
        resp = session_dict.get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list) and len(data) > 0:
                result = data[0]
                result["word"] = word
                return result
            else:
                # API ответил 200 OK, но список пуст.
                # Возвращаем пустую структуру, которая будет закэширована.
                return {"word": word, "meanings": [], "phonetics": []}
        elif resp.status_code == 404:
            # Слова нет (404). Тоже кэшируем пустоту.
            return {"word": word, "meanings": [], "phonetics": []}
    except (requests.RequestException, ValueError):
        pass
    return None

# ═══════════════════════════════════════════════════════════════════════════
# ПЕРЕВОД (TRANSLATION)
# ═══════════════════════════════════════════════════════════════════════════

def load_translation_cache(word: str) -> Optional[str]:
    """Загружает перевод из ОТДЕЛЬНОГО кэша"""
    path = get_translation_cache_path(word)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("trans")
        except (IOError, OSError, json.JSONDecodeError):
            pass
    return None

def save_translation_cache(word: str, translation: str):
    """Сохраняет перевод в ОТДЕЛЬНЫЙ кэш"""
    path = get_translation_cache_path(word)
    with _cache_write_lock:
        try:
            temp_path = path + '.tmp'
            data = {"trans": translation}
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(temp_path, path)
        except (IOError, OSError):
            pass

def fetch_yandex_translation(text: str) -> Optional[str]:
    """
    Перевод слова через Yandex Dictionary API с умным сбором значений.
    Алгоритм:
    1. Берем по 1 переводу из каждой части речи (def).
    2. Если набралось < 3 слов, добираем из первой части речи.
    3. Объединяем через запятую (макс 3 слова).
    """
    key = cfg.get("API", "YandexKey")
    if not key:
        return None

    url = "https://dictionary.yandex.net/api/v1/dicservice.json/lookup"
    params = {
        "key": key,
        "lang": "en-ru",
        "text": text,
        "ui": "ru"
    }

    try:
        resp = session_dict.get(url, params=params, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            definitions = data.get("def", [])
            if not definitions:
                return None

            collected_words = []

            # 1. Берем по одному переводу из каждой части речи
            for pos_block in definitions:
                if "tr" in pos_block and len(pos_block["tr"]) > 0:
                    word = pos_block["tr"][0]["text"]
                    if word not in collected_words:
                        collected_words.append(word)

            # 2. Если набрали меньше 3 слов, добираем из первой части речи (если она есть)
            if len(collected_words) < 3 and len(definitions) > 0:
                first_pos_translations = definitions[0].get("tr", [])
                # Начинаем со 2-го перевода (индекс 1), т.к. первый мы уже взяли выше
                for tr in first_pos_translations[1:]:
                    if len(collected_words) >= 3:
                        break
                    word = tr["text"]
                    if word not in collected_words:
                        collected_words.append(word)

            # 3. Формируем строку
            if collected_words:
                return ", ".join(collected_words[:3])
    except (requests.RequestException, KeyError, IndexError, ValueError):
        pass
    return None

def fetch_google_translation(text: str) -> Optional[str]:
    """Перевод через Google (fallback)"""
    url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=ru&dt=t&q={quote(text)}"
    try:
        resp = session_google.get(url, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            if data and len(data) > 0 and len(data[0]) > 0:
                return "".join([x[0] for x in data[0] if x[0]])
    except (requests.RequestException, IndexError, ValueError):
        pass
    return None

def fetch_sentence_translation(text: str) -> Optional[str]:
    """
    Перевод предложений (сначала Яндекс, потом Google).
    Не кэшируется (или кэшируется в памяти UI).
    """
    #res = fetch_yandex_translation(text)
    #if res:
    #    return res
    return fetch_google_translation(text)

# ═══════════════════════════════════════════════════════════════════════════
# ИЗОБРАЖЕНИЯ (IMAGES)
# ═══════════════════════════════════════════════════════════════════════════

def fetch_pexels_image(word: str) -> Optional[str]:
    """Загружает изображение из Pexels API"""
    if is_image_not_found(word):
        return None

    cached_path = get_image_path(word)
    if os.path.exists(cached_path):
        return cached_path

    key = cfg.get("API", "PexelsKey")
    if not key:
        return None

    cleaned_word = ''.join(c for c in word if c.isalpha() and ord(c) < 128).lower()
    url = f"https://api.pexels.com/v1/search?query={cleaned_word}&per_page=1"
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

def fetch_wiki_image(word: str) -> Optional[str]:
    """Загружает изображение из Wikipedia"""
    if is_image_not_found(word):
        return None

    cleaned_word = ''.join(c for c in word if c.isalpha() and ord(c) < 128).lower()
    url = f"https://en.wikipedia.org/w/api.php?action=query&titles={cleaned_word}&prop=pageimages&format=json&pithumbsize={IMAGE_THUMBNAIL_SIZE}"

    # Черный список для фильтрации служебных изображений
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

                # Фильтрация служебных изображений
                if any(bad.lower() in img_url.lower() for bad in blacklist):
                    continue

                # Проверка минимального разрешения
                width = thumbnail.get("width", 0)
                height = thumbnail.get("height", 0)
                if width < MIN_IMAGE_DIMENSION or height < MIN_IMAGE_DIMENSION:
                    continue

                return download_image(img_url, word)
    except (requests.RequestException, json.JSONDecodeError, ValueError, KeyError):
        pass
    return None

def download_image(url: str, word: str) -> Optional[str]:
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

def fetch_image(word: str) -> Tuple[Optional[str], str]:
    """
    Загружает изображение из доступных источников.
    Returns:
        (path, source_name): Путь к изображению и название источника
        или (None, "None") если не найдено
    """
    path = fetch_pexels_image(word)
    if path:
        return path, "Pexels"

    path = fetch_wiki_image(word)
    if path:
        return path, "Wiki"

    # Помечаем как не найденное только если оба источника не дали результат
    if not is_image_not_found(word):
        mark_image_not_found(word)

    return None, "None"

# ═══════════════════════════════════════════════════════════════════════════
# CLEANUP
# ═══════════════════════════════════════════════════════════════════════════

def close_all_sessions():
    """Закрывает все HTTP сессии при завершении приложения"""
    session_dict.close()
    session_google.close()
    session_pexels.close()
    session_wiki.close()

def clear_temp_audio() -> int:
    """
    Очищает временные аудиофайлы (вызывается при закрытии приложения).

    Returns:
        Количество удаленных файлов
    """
    if not os.path.exists(TEMP_AUDIO_DIR):
        return 0

    deleted_count = 0
    try:
        with os.scandir(TEMP_AUDIO_DIR) as entries:
            for entry in entries:
                if entry.is_file():
                    try:
                        os.unlink(entry.path)
                        deleted_count += 1
                    except OSError:
                        continue
    except OSError:
        pass

    return deleted_count

# ═══════════════════════════════════════════════════════════════════════════
# AUDIO HIGH-LEVEL API
# ═══════════════════════════════════════════════════════════════════════════

def ensure_audio_ready(word: str, use_cache: bool = True) -> Optional[str]:
    """
    Гарантирует наличие аудиофайла (с поддержкой официального Google TTS).

    Логика:
    1. Проверяет кэш (если use_cache=True).
    2. Пробует официальный Google Cloud TTS API.
    3. Fallback на неофициальный Google TTS.

    Args:
        word: Слово или текст для озвучки
        use_cache: Если True - сохранять в постоянный кэш (для вызова озвучки слов), иначе во временный

    Returns:
        Путь к файлу (.mp3) или None, если не удалось получить.
    """
    # 1. Пробуем официальный Google TTS API
    official_path = fetch_google_official_tts(word, use_cache=use_cache)
    if official_path:
        return official_path

    # 2. Fallback на неофициальный Google TTS (только для слов с кэшем)
    if use_cache:
        cache_path = get_audio_cache_path(word, "us")
        temp_path = cache_path + '.tmp'

        # Быстрая проверка кэша
        if os.path.exists(cache_path) and is_valid_audio_file(cache_path):
            return cache_path

        # Ожидание чужой загрузки
        if os.path.exists(temp_path):
            for _ in range(20):  # ждем до 2 сек
                if os.path.exists(cache_path) and is_valid_audio_file(cache_path):
                    return cache_path
                time.sleep(0.1)

        # Скачивание
        url = get_google_tts_url(word, "us")
        if download_and_cache_audio(url, cache_path):
            return cache_path

        # Fallback на стриминг
        streaming_play_and_cache(url, cache_path)

        # Финальная проверка
        if os.path.exists(cache_path) and is_valid_audio_file(cache_path):
            return cache_path

    return None

def play_audio_safe(path: str):
    """
    Безопасное воспроизведение аудиофайла.
    Не блокирует поток надолго (зависит от playsound) и глотает ошибки.
    """
    if not PLAYSOUND_AVAILABLE or playsound is None:
        return

    try:
        # with _audio_play_lock:  # Блокировка отключена для скорости
        playsound(path)
    except Exception as e:
        print(f"DEBUG: Audio playback error: {e}")
