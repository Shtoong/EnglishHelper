import os
import requests
import json
import urllib3
from config import cfg, IMG_DIR, DICT_DIR

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def fetch_word_translation(word):
    """Получает перевод слова через Yandex API или из кэша"""
    key = cfg.get("API", "YandexKey")
    if not key: return {"trans": "", "rus": "No API Key", "cached": False}

    json_path = os.path.join(DICT_DIR, f"{word}.json")

    # Проверка кэша
    if os.path.exists(json_path):
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if data.get('rus'):
                    data['cached'] = True
                    return data
        except:
            pass

    # Запрос к API
    try:
        url = "https://dictionary.yandex.net/api/v1/dicservice.json/lookup"
        params = {"key": key, "lang": "en-ru", "text": word, "ui": "ru"}
        resp = requests.get(url, params=params, timeout=3).json()

        result = {}
        if resp.get('def'):
            art = resp['def'][0]
            result = {
                "trans": art.get('ts', ''),
                "rus": art['tr'][0].get('text', '') if art.get('tr') else ""
            }  # <--- ДОБАВЛЕНА ЗАКРЫВАЮЩАЯ СКОБКА

            # Сохранение в кэш
            if result['rus']:
                with open(json_path, 'w', encoding='utf-8') as f:
                    json.dump(result, f, ensure_ascii=False)

            result['cached'] = False
            return result
    except:
        pass
    return None

def fetch_examples(word):
    """Получает пример использования слова"""
    try:
        dapi = requests.get(f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}", timeout=3).json()
        if isinstance(dapi, list):
            for e in dapi:
                for m in e.get('meanings', []):
                    for d in m.get('definitions', []):
                        if 'example' in d: return {"ex_text": d['example']}
    except:
        pass
    return None


def fetch_image(word):
    """Скачивает картинку с Pexels или берет из кэша"""
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
    """Переводит предложение целиком через Google Translate"""
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


def fetch_full_dictionary_data(word):
    """
    Фоновый запрос к dictionaryapi.dev для получения полных данных о слове.
    Кэширует JSON в папку Dict с суффиксом _full.json.
    Не возвращает данные в UI - только сохраняет для будущего использования.

    Содержимое JSON включает:
    - phonetics: транскрипция и аудио URL
    - meanings: определения, синонимы, антонимы
    - примеры использования
    """
    file_path = os.path.join(DICT_DIR, f"{word}_full.json")

    # Если файл уже существует — не делаем повторный запрос
    if os.path.exists(file_path):
        return

    url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}"

    try:
        response = requests.get(url, timeout=5)

        if response.status_code == 200:
            data = response.json()
            # Сохраняем полный JSON ответ
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"[DictAPI] Cached full data for: {word}")

        elif response.status_code == 404:
            # Слово не найдено - создаем пустой маркер, чтобы не запрашивать повторно
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump({"error": "Word not found"}, f)

    except Exception as e:
        # Это фоновая задача, ошибки не критичны
        print(f"[DictAPI] Error fetching data for '{word}': {e}")
