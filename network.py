import os
import requests
import json
import urllib3
import threading
from config import cfg, IMG_DIR, DICT_DIR

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Глобальная сессия для переиспользования соединений (УСКОРЕНИЕ TCP/SSL)
SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
})


# --- PRIVATE HELPERS ---

def _get_cache_path(word):
    return os.path.join(DICT_DIR, f"{word}_full.json")


def _load_cache(word):
    path = _get_cache_path(word)
    if not os.path.exists(path): return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except:
        return {}


def _save_cache(word, data):
    path = _get_cache_path(word)
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[Cache] Error saving: {e}")


def _update_cache_key(word, key, value):
    data = _load_cache(word)
    data[key] = value
    _save_cache(word, data)


# --- PUBLIC API ---

def check_cache_only(word):
    """Быстрая проверка ТОЛЬКО кэша (без сети)."""
    cache = _load_cache(word)
    if cache.get('russian'):
        return {"rus": cache['russian'], "trans": cache.get('trans_simple', ''), "cached": True}
    return None


def fetch_word_translation(word):
    cached = check_cache_only(word)
    if cached: return cached

    key = cfg.get("API", "YandexKey")
    if not key: return {"trans": "", "rus": "No API Key", "cached": False}

    try:
        url = "https://dictionary.yandex.net/api/v1/dicservice.json/lookup"
        params = {"key": key, "lang": "en-ru", "text": word, "ui": "ru"}
        resp = SESSION.get(url, params=params, timeout=2).json()

        if resp.get('def'):
            art = resp['def'][0]
            rus_text = art['tr'][0].get('text', '') if art.get('tr') else ""
            trans_text = art.get('ts', '')

            if rus_text:
                data = _load_cache(word)
                data['russian'] = rus_text;
                data['trans_simple'] = trans_text
                _save_cache(word, data)
                return {"rus": rus_text, "trans": trans_text, "cached": False}
    except:
        pass
    return None


def fetch_full_dictionary_data(word):
    cache = _load_cache(word)
    if cache.get('details') and len(cache['details']) > 0: return

    variants = [word]
    if not word[0].isupper():
        variants.append(word.title())

    found = False

    for variant in variants:
        url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{variant}"
        try:
            response = SESSION.get(url, timeout=5)
            if response.status_code == 200:
                _update_cache_key(word, 'details', response.json())
                found = True
                break
        except:
            pass

    if not found:
        _update_cache_key(word, 'details', [])


def load_full_dictionary_data(word):
    cache = _load_cache(word)
    details = cache.get('details')

    if details is not None and len(details) == 0: return None
    if not details or not isinstance(details, list): return None

    try:
        combined_phonetics = []
        combined_meanings = []
        base_word = details[0].get('word', word)

        for entry in details:
            for p in entry.get('phonetics', []):
                combined_phonetics.append(
                    {'text': p.get('text', ''), 'audio': p.get('audio', ''), 'sourceUrl': p.get('sourceUrl', '')})
            for m in entry.get('meanings', []):
                part_of_speech = m.get('partOfSpeech', '')
                definitions = []
                for d in m.get('definitions', [])[:3]:
                    definitions.append({'definition': d.get('definition', ''), 'example': d.get('example', '')})
                synonyms = m.get('synonyms', [])[:5]
                combined_meanings.append(
                    {'partOfSpeech': part_of_speech, 'definitions': definitions, 'synonyms': synonyms})
        return {'word': base_word, 'phonetics': combined_phonetics, 'meanings': combined_meanings}
    except:
        return None


# --- SMART IMAGE LOGIC ---

def fetch_image(word):
    local_path = os.path.join(IMG_DIR, f"{word.lower()}.jpg")
    if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
        return local_path, "Cache"

    variants = [word, word.upper(), word.title()]
    variants = list(dict.fromkeys(variants))

    wiki_url = "https://en.wikipedia.org/w/api.php"

    for variant in variants:
        try:
            params = {
                "action": "query", "format": "json", "prop": "pageimages",
                "titles": variant, "pithumbsize": 600, "redirects": 1
            }
            resp = SESSION.get(wiki_url, params=params, timeout=2)
            if resp.status_code == 200:
                data = resp.json()
                pages = data.get("query", {}).get("pages", {})
                for page_id, page_data in pages.items():
                    if page_id != "-1" and "thumbnail" in page_data:
                        img_url = page_data["thumbnail"]["source"]
                        img_resp = SESSION.get(img_url, timeout=5)
                        if img_resp.status_code == 200:
                            with open(local_path, 'wb') as f:
                                f.write(img_resp.content)
                            return local_path, "Wiki"
        except:
            pass

    return fetch_image_from_pexels(word, local_path)


def fetch_image_from_pexels(word, local_path):
    key = cfg.get("API", "PexelsKey")
    if not key: return None, "No Key"

    try:
        headers = SESSION.headers.copy()
        headers["Authorization"] = key
        resp = SESSION.get(f"https://api.pexels.com/v1/search?query={word}&per_page=1", headers=headers,
                           timeout=4).json()
        if resp.get('photos'):
            img_url = resp['photos'][0]['src']['medium']
            img_resp = SESSION.get(img_url, headers=SESSION.headers, timeout=5)
            if img_resp.status_code == 200:
                with open(local_path, 'wb') as f:
                    f.write(img_resp.content)
                return local_path, "Pexels"
    except:
        pass
    return None, "None"


def fetch_sentence_translation(text):
    if not text or len(text.strip()) < 2: return "..."
    try:
        url = "https://translate.googleapis.com/translate_a/single"
        params = {"client": "gtx", "sl": "en", "tl": "ru", "dt": "t", "q": text}
        resp = SESSION.get(url, params=params, timeout=3)
        if resp.status_code == 200:
            data = resp.json()
            res = ""
            for part in data[0]:
                if part[0]: res += part[0]
            return res
    except:
        return "Error"
    return "..."


def warmup_connections():
    """Фоновый прогрев SSL-соединений при старте"""

    def _warmup():
        try:
            SESSION.head("https://dictionary.yandex.net", timeout=1)
            SESSION.head("https://api.dictionaryapi.dev", timeout=1)
            SESSION.head("https://api.pexels.com", timeout=1)
            SESSION.head("https://en.wikipedia.org", timeout=1)
        except:
            pass

    threading.Thread(target=_warmup, daemon=True).start()


# Запускаем прогрев при импорте модуля
warmup_connections()
