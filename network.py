import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import os
import json
import threading
import time
import tempfile
import shutil
from urllib.parse import quote, urlparse, parse_qs
from config import cfg, DICT_DIR, IMG_DIR, AUDIO_DIR

# ===== LEMMATIZATION =====
try:
    import lemminflect

    LEMMATIZER_AVAILABLE = True
except ImportError:
    LEMMATIZER_AVAILABLE = False
    print("⚠️ lemminflect not available")


def lemmatize_word(word: str) -> str:
    """
    ✅ ВОССТАНОВЛЕНО: Приведение к словарной форме
    """
    if not LEMMATIZER_AVAILABLE:
        return word.lower()

    try:
        import lemminflect
        # Пробуем разные части речи
        for pos in ['VERB', 'NOUN', 'ADJ', 'ADV']:
            lemmas = lemminflect.getLemma(word.lower(), upos=pos)
            if lemmas:
                return lemmas[0]
        return word.lower()
    except:
        return word.lower()


# ===== SESSION MANAGEMENT =====

def _create_session(max_retries=3, backoff_factor=0.3):
    session = requests.Session()
    retry_strategy = Retry(
        total=max_retries,
        backoff_factor=backoff_factor,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "OPTIONS"]
    )
    adapter = HTTPAdapter(
        max_retries=retry_strategy,
        pool_connections=10,
        pool_maxsize=20
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
    """✅ ВОССТАНОВЛЕНО: Лемматизация для имени файла"""
    lemma = lemmatize_word(word)
    safe_word = "".join(c for c in lemma if c.isalnum()).lower()
    return os.path.join(DICT_DIR, f"{safe_word}-full.json")


def get_audio_cache_path(word: str, accent: str = "us") -> str:
    """✅ ВОССТАНОВЛЕНО: Лемматизация для имени файла"""
    lemma = lemmatize_word(word)
    safe_word = "".join(c for c in lemma if c.isalnum()).lower()
    return os.path.join(AUDIO_DIR, f"{safe_word}-{accent}.mp3")


def get_image_path(word):
    """✅ ВОССТАНОВЛЕНО: Лемматизация для имени файла"""
    lemma = lemmatize_word(word)
    safe_word = "".join(c for c in lemma if c.isalnum()).lower()
    return os.path.join(IMG_DIR, f"{safe_word}.jpg")


def mark_image_not_found(word):
    lemma = lemmatize_word(word)
    safe_word = "".join(c for c in lemma if c.isalnum()).lower()
    marker_path = os.path.join(IMG_DIR, f"{safe_word}.nofound")
    try:
        os.makedirs(IMG_DIR, exist_ok=True)
        with open(marker_path, "w") as f:
            f.write(str(int(time.time())))
        print(f"✅ Marked as 'no image': {lemma}")
    except Exception as e:
        print(f"Marker error: {e}")


def is_image_not_found(word) -> bool:
    lemma = lemmatize_word(word)
    safe_word = "".join(c for c in lemma if c.isalnum()).lower()
    marker_path = os.path.join(IMG_DIR, f"{safe_word}.nofound")
    return os.path.exists(marker_path)


# ===== GOOGLE TTS =====

def get_google_tts_url(word: str, accent: str = "us") -> str:
    """✅ ВАЖНО: TTS использует ОРИГИНАЛЬНОЕ слово (не лемму) для правильного произношения"""
    lang_code = "en-US" if accent == "us" else "en-GB"
    encoded_word = quote(word)
    return f"https://translate.google.com/translate_tts?ie=UTF-8&tl={lang_code}&client=tw-ob&q={encoded_word}"


def download_and_cache_audio(url: str, cache_path: str) -> bool:
    try:
        resp = session_google.get(url, timeout=10)
        if resp.status_code == 200:
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            with open(cache_path, "wb") as f:
                f.write(resp.content)

            if os.path.exists(cache_path) and os.path.getsize(cache_path) > 1000:
                print(f"✅ Cached audio: {cache_path}")
                return True
    except Exception as e:
        print(f"Audio download error: {e}")
    return False


def _cache_audio_sync(url: str, cache_path: str) -> bool:
    if os.path.exists(cache_path):
        return True
    return download_and_cache_audio(url, cache_path)


def _cache_audio_from_phonetics(audio_url: str, word: str):
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
    try:
        from playsound import playsound

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

            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            shutil.move(tmp_path, cache_path)

    except Exception as e:
        print(f"Streaming Play Error: {e}")


def _safe_play(path: str):
    max_attempts = 10
    for i in range(max_attempts):
        try:
            if os.path.exists(path) and os.path.getsize(path) > 1000:
                from playsound import playsound
                with _audio_play_lock:
                    playsound(path)
                return
        except Exception as e:
            if i < max_attempts - 1:
                time.sleep(0.05)
            else:
                print(f"Play failed: {e}")


# ===== DICTIONARY DATA =====

def check_cache_only(word):
    path = get_cache_path(word)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {
                "rus": data.get("rus", ""),
                "cached": True
            }
        except:
            pass
    return None


def load_full_dictionary_data(word):
    path = get_cache_path(word)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return None


def save_full_dictionary_data(word, data):
    path = get_cache_path(word)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        lemma = lemmatize_word(word)
        print(f"✅ Saved cache for: {word} -> {lemma}")
    except Exception as e:
        print(f"Cache Save Error: {e}")


def fetch_full_dictionary_data(word):
    """
    ✅ ВОССТАНОВЛЕНО:
    1. API запрашивается с ЛЕММОЙ
    2. Google TTS URL создаётся с ОРИГИНАЛЬНЫМ словом
    3. Кэш сохраняется по имени ЛЕММЫ
    """
    lemma = lemmatize_word(word)
    url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{lemma}"

    # ✅ КРИТИЧНО: Google TTS с ОРИГИНАЛЬНЫМ словом для правильного произношения
    google_us_url = get_google_tts_url(word, "us")
    google_us_cache = get_audio_cache_path(word, "us")
    _cache_audio_sync(google_us_url, google_us_cache)
    print(f"✅ Google US audio cached: {word} (lemma: {lemma})")

    try:
        resp = session_dict.get(url, timeout=8)
        if resp.status_code == 200:
            data_list = resp.json()
            if data_list and isinstance(data_list, list):
                full_data = data_list[0]

                rus_trans = fetch_yandex_translation(lemma)
                if not rus_trans:
                    rus_trans = fetch_google_translation(lemma)

                if rus_trans:
                    full_data["rus"] = rus_trans

                phonetics = full_data.get("phonetics", [])

                for p in phonetics:
                    audio_url = p.get("audio")
                    if audio_url:
                        _cache_audio_from_phonetics(audio_url, word)

                has_us = any(
                    "-us.mp3" in p.get("audio", "").lower() or "en-US" in p.get("audio", "")
                    for p in phonetics if p.get("audio")
                )
                has_uk = any(
                    "-uk.mp3" in p.get("audio", "").lower() or "en-GB" in p.get("audio", "")
                    for p in phonetics if p.get("audio")
                )

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
                    threading.Thread(
                        target=_cache_audio_sync,
                        args=(uk_url, get_audio_cache_path(word, "uk")),
                        daemon=True
                    ).start()

                full_data["phonetics"] = phonetics
                full_data["word"] = lemma
                save_full_dictionary_data(word, full_data)

                return full_data
    except Exception as e:
        print(f"Dict API Error: {e}")

    cached = load_full_dictionary_data(word)
    if not cached:
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

    return cached


# ===== TRANSLATION =====

def fetch_yandex_translation(word):
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
    except Exception as e:
        print(f"Yandex API Error: {e}")
    return None


def fetch_google_translation(word):
    try:
        lemma = lemmatize_word(word)
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
    except Exception as e:
        print(f"Google Translation Error: {e}")
    return None


def fetch_word_translation(word):
    full_data = load_full_dictionary_data(word)
    if full_data and "rus" in full_data:
        return {"rus": full_data["rus"], "cached": True}

    full_data = fetch_full_dictionary_data(word)
    if full_data and "rus" in full_data:
        return {"rus": full_data["rus"], "cached": False}

    google_trans = fetch_google_translation(word)
    if google_trans:
        if full_data:
            full_data["rus"] = google_trans
            save_full_dictionary_data(word, full_data)
        else:
            lemma = lemmatize_word(word)
            save_full_dictionary_data(word, {"rus": google_trans, "word": lemma})
        return {"rus": google_trans, "cached": False}

    return None


def fetch_sentence_translation(text):
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
    except Exception as e:
        print(f"Translation Error: {e}")

    return None


# ===== IMAGES =====

def download_image(url, word):
    os.makedirs(IMG_DIR, exist_ok=True)

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
    except Exception as e:
        print(f"Download Error: {e}")
    return None


def fetch_pexels_image(word):
    if is_image_not_found(word):
        print(f"⏭️ Skipping Pexels (marked): {word}")
        return None

    cached_path = get_image_path(word)
    if os.path.exists(cached_path):
        print(f"✅ Image from cache: {word}")
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
    except Exception as e:
        print(f"Pexels Error: {e}")

    return None


def fetch_wiki_image(word):
    if is_image_not_found(word):
        print(f"⏭️ Skipping Wiki (marked): {word}")
        return None

    lemma = lemmatize_word(word)
    url = f"https://en.wikipedia.org/w/api.php?action=query&titles={lemma}&prop=pageimages&format=json&pithumbsize=500"

    BLACKLIST = [
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

                if any(bad.lower() in img_url.lower() for bad in BLACKLIST):
                    continue

                width = thumbnail.get("width", 0)
                height = thumbnail.get("height", 0)

                if width < 100 or height < 100:
                    continue

                return download_image(img_url, word)

    except Exception as e:
        print(f"Wiki Error: {e}")

    return None


def fetch_image(word):
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
    session_dict.close()
    session_google.close()
    session_pexels.close()
    session_wiki.close()
