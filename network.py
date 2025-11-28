import os
import requests
import json
import urllib3
from config import cfg, IMG_DIR, DICT_DIR

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# --- PRIVATE HELPERS ---

def _get_cache_path(word):
    return os.path.join(DICT_DIR, f"{word}_full.json")


def _load_cache(word):
    """Загружает JSON файл. Всегда возвращает dict."""
    path = _get_cache_path(word)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # Если файл пустой или битый - возвращаем пустой dict
            return data if isinstance(data, dict) else {}
    except:
        return {}


def _save_cache(word, data):
    """Сохраняет dict в JSON файл."""
    path = _get_cache_path(word)
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[Cache] Error saving: {e}")


def _update_cache_key(word, key, value):
    """Обновляет одно поле в JSON файле."""
    data = _load_cache(word)
    data[key] = value
    _save_cache(word, data)


# --- PUBLIC API ---

def fetch_word_translation(word):
    """
    Получает краткий перевод (Яндекс).
    Кэширует результат в поле 'russian' и 'trans_simple'.
    """
    cache = _load_cache(word)

    # 1. Есть в кэше?
    if cache.get('russian'):
        return {
            "rus": cache['russian'],
            "trans": cache.get('trans_simple', ''),
            "cached": True
        }

    # 2. Нет API ключа?
    key = cfg.get("API", "YandexKey")
    if not key:
        return {"trans": "", "rus": "No API Key", "cached": False}

    # 3. Запрос к API
    try:
        url = "https://dictionary.yandex.net/api/v1/dicservice.json/lookup"
        params = {"key": key, "lang": "en-ru", "text": word, "ui": "ru"}
        resp = requests.get(url, params=params, timeout=3).json()

        if resp.get('def'):
            art = resp['def'][0]
            rus_text = art['tr'][0].get('text', '') if art.get('tr') else ""
            trans_text = art.get('ts', '')

            if rus_text:
                # Сохраняем в общий кэш
                data = _load_cache(word)
                data['russian'] = rus_text
                data['trans_simple'] = trans_text
                _save_cache(word, data)

                return {"rus": rus_text, "trans": trans_text, "cached": False}
    except:
        pass

    return None


def fetch_full_dictionary_data(word):
    """
    Загружает полные данные (DictionaryAPI).
    Кэширует результат в поле 'details'.
    """
    cache = _load_cache(word)

    if cache.get('details'):
        return

    url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}"
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            # Сохраняем список деталей в поле details
            _update_cache_key(word, 'details', response.json())
            print(f"[DictAPI] Cached details for: {word}")
        elif response.status_code == 404:
            _update_cache_key(word, 'details', [])  # Пустой список = слово не найдено
    except Exception as e:
        print(f"[DictAPI] Error: {e}")


def load_full_dictionary_data(word):
    """
    Читает данные из поля 'details' для UI.
    """
    cache = _load_cache(word)
    details = cache.get('details')

    if not details or not isinstance(details, list) or len(details) == 0:
        return None

    try:
        combined_phonetics = []
        combined_meanings = []
        base_word = details[0].get('word', word)

        for entry in details:
            # Фонетика
            for p in entry.get('phonetics', []):
                combined_phonetics.append({
                    'text': p.get('text', ''),
                    'audio': p.get('audio', ''),
                    'sourceUrl': p.get('sourceUrl', '')
                })

            # Значения
            for m in entry.get('meanings', []):
                part_of_speech = m.get('partOfSpeech', '')
                definitions = []
                for d in m.get('definitions', [])[:3]:
                    definitions.append({
                        'definition': d.get('definition', ''),
                        'example': d.get('example', ''),
                    })
                synonyms = m.get('synonyms', [])[:5]

                combined_meanings.append({
                    'partOfSpeech': part_of_speech,
                    'definitions': definitions,
                    'synonyms': synonyms
                })

        return {
            'word': base_word,
            'phonetics': combined_phonetics,
            'meanings': combined_meanings
        }
    except:
        return None


def fetch_image(word):
    """Картинки храним отдельными файлами .jpg (так эффективнее для Tkinter)"""
    local_path = os.path.join(IMG_DIR, f"{word.lower()}.jpg")
    if os.path.exists(local_path): return local_path, "Cache"

    key = cfg.get("API", "PexelsKey")
    if not key: return None, "No Key"

    try:
        headers = {"Authorization": key}
        resp = requests.get(f"https://api.pexels.com/v1/search?query={word}&per_page=1", headers=headers,
                            timeout=5).json()
        if resp.get('photos'):
            with open(local_path, 'wb') as f:
                f.write(requests.get(resp['photos'][0]['src']['medium']).content)
            return local_path, "API"
    except:
        pass
    return None, "None"


def fetch_sentence_translation(text):
    """Google Translate (без кэша)"""
    if not text or len(text.strip()) < 2: return "..."
    try:
        url = "https://translate.googleapis.com/translate_a/single"
        params = {"client": "gtx", "sl": "en", "tl": "ru", "dt": "t", "q": text}
        resp = requests.get(url, params=params, timeout=4)
        if resp.status_code == 200:
            data = resp.json()
            res = ""
            for part in data[0]:
                if part[0]: res += part[0]
            return res
    except:
        return "Error"
    return "..."
