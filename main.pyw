import threading
import keyboard
import re
import ctypes
import time
import pyperclip
import os

from config import cfg
from vocab import init_vocab, is_word_too_simple
from network import (
    fetch_word_translation,
    fetch_image,
    fetch_sentence_translation,
    fetch_full_dictionary_data,
    load_full_dictionary_data,
    check_cache_only,
    get_google_tts_url,
    get_audio_cache_path,
    streaming_play_and_cache,
    close_all_sessions
)
from editor import TextEditorSimulator
from gui.main_window import MainWindow

# ===== GRACEFUL DEGRADATION =====
try:
    from playsound import playsound

    PLAYSOUND_AVAILABLE = True
except ImportError:
    playsound = None
    PLAYSOUND_AVAILABLE = False

# ===== GLOBAL STATE =====
BUFFER = ""
SENTENCE_FINISHED = False
EDITOR = TextEditorSimulator()

# ===== KEYBOARD LIBRARY BUG FIX =====
# КРИТИЧНО: НЕ УДАЛЯТЬ!
# Библиотека keyboard на Windows имеет баг: при английской раскладке
# e.name может возвращать РУССКИЕ символы (по физической позиции клавиши).
# Например: нажатие "h" → e.name = "р" (русская буква на той же клавише).
# Этот словарь преобразует русские символы обратно в английские.
# Без него во втором окне будет печататься кириллица вместо латиницы!
KEYBOARD_BUG_FIX = {
    ru: en
    for ru, en in zip(
        "йцукенгшщзхъфывапролджэячсмитьбю",
        "qwertyuiop[]asdfghjkl;'zxcvbnm,.",
    )
}

# ===== THREAD SAFETY =====
_translation_lock = threading.Lock()
TRANSLATION_TIMER = None

# ===== CLIPBOARD THROTTLING =====
CLIPBOARD_LAST_TIME = 0

# ===== LAYOUT CACHE =====
_layout_cache = {"is_english": True, "last_check": 0}


def is_english_layout():
    """
    Проверяет английскую раскладку с кэшированием (500ms TTL).
    Оптимизация: 100+ WinAPI вызовов/мин → 2 вызова/сек = 98% снижение.
    """
    current_time = time.time()
    if current_time - _layout_cache["last_check"] < 0.5:
        return _layout_cache["is_english"]

    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        hwnd = user32.GetForegroundWindow()
        thread_id = user32.GetWindowThreadProcessId(hwnd, 0)
        layout_id = user32.GetKeyboardLayout(thread_id)
        is_en = ((layout_id & 0xFFFF) & 0x3FF) == 0x09

        _layout_cache["is_english"] = is_en
        _layout_cache["last_check"] = current_time
        return is_en
    except Exception:
        return True


# ===== WORKERS =====

def worker_trans(tgt, app):
    """Загружает перевод слова"""
    res = fetch_word_translation(tgt)
    app.after(
        0,
        lambda: app.update_trans_ui(
            res or {},
            "API" if res and not res.get("cached") else "—"
        ),
    )


def worker_img(tgt, app):
    """Загружает изображение для слова"""
    path, src = fetch_image(tgt)
    app.after(0, lambda: app.update_img_ui(path, src))


def _instant_auto_pronounce(word, app):
    """
    Автоматическое произношение слова (только Google TTS US).
    Оптимизировано: активное ожидание файла до 2 секунд.
    """
    if not PLAYSOUND_AVAILABLE:
        return

    try:
        cache_path = get_audio_cache_path(word, "us")

        # Активное ожидание готовности файла (до 2 секунд)
        max_wait = 20  # 20 × 0.1s = 2 секунды
        for attempt in range(max_wait):
            if os.path.exists(cache_path) and os.path.getsize(cache_path) > 1000:
                try:
                    playsound(cache_path)
                    return
                except Exception:
                    break
            time.sleep(0.1)

        # Fallback: streaming воспроизведение
        url = get_google_tts_url(word, "us")
        streaming_play_and_cache(url, cache_path)

    except Exception:
        pass


def worker_full_data_display(tgt, app):
    """
    Загружает полные данные словаря и запускает автопроизношение.
    Оптимизировано: автопроизношение в отдельном потоке (не блокирует).
    """
    # Проверяем кэш
    full_data = load_full_dictionary_data(tgt)

    # Если нет в кэше - загружаем синхронно
    if not full_data:
        full_data = fetch_full_dictionary_data(tgt)

    # Обновляем UI
    app.after(0, lambda: app.update_full_data_ui(full_data))

    # Автопроизношение в отдельном потоке (не блокирует worker)
    if cfg.get_bool("USER", "AutoPronounce"):
        threading.Thread(
            target=_instant_auto_pronounce,
            args=(tgt, app),
            daemon=True
        ).start()


def process_word_async(word, app):
    """
    Асинхронно обрабатывает слово в отдельном потоке.
    Helper для избежания дублирования кода.
    """
    threading.Thread(
        target=process_word_parallel,
        args=(word, app),
        daemon=True
    ).start()


def process_word_parallel(w, app):
    """Параллельная обработка слова (перевод + изображение + словарь)"""
    too_simple, tgt = is_word_too_simple(w, int(app.vocab_var.get()))  # ← ИСПРАВЛЕНО
    if too_simple:
        return

    app.after(0, lambda: app.reset_ui(tgt))

    # Быстрая проверка кэша
    cached_res = check_cache_only(tgt)
    if cached_res:
        # Thread-safe: используем app.after() для UI обновлений
        app.after(0, lambda: app.update_trans_ui(cached_res, "Cache"))
    else:
        threading.Thread(target=worker_trans, args=(tgt, app), daemon=True).start()

    threading.Thread(target=worker_img, args=(tgt, app), daemon=True).start()
    threading.Thread(target=worker_full_data_display, args=(tgt, app), daemon=True).start()


def handle_clipboard_word(app):
    """
    Обрабатывает слово из буфера обмена (Ctrl+C).
    Оптимизировано: throttling вместо проверки последнего слова.
    """
    global CLIPBOARD_LAST_TIME

    # Throttling: минимум 500ms между обработками
    current_time = time.time()
    if current_time - CLIPBOARD_LAST_TIME < 0.5:
        return

    CLIPBOARD_LAST_TIME = current_time

    # Минимальная задержка для гарантии записи в буфер
    time.sleep(0.02)

    try:
        text = pyperclip.paste()
    except Exception:
        return

    if not text:
        return
    text = text.strip()

    # Валидация: только слова длиной 1-50 символов
    if not (0 < len(text) <= 50):
        return
    if not re.match(r"^[a-zA-Z\-']+$", text):
        return

    process_word_async(text, app)


def trigger_sentence_update(app, need_translate=False):
    """
    Обновляет отображение предложения с отложенным переводом.
    Оптимизировано: Lock для предотвращения race condition.
    """
    global TRANSLATION_TIMER

    # Обновляем английский текст с курсором
    eng_display = EDITOR.get_text_with_cursor()
    app.after_idle(lambda: app.sent_window.lbl_eng.config(text=eng_display))

    # Thread-safe управление таймером перевода
    with _translation_lock:
        if TRANSLATION_TIMER is not None:
            TRANSLATION_TIMER.cancel()

        if need_translate:
            def delayed_translation_task():
                clean_text = EDITOR.get_text().strip()
                if clean_text:
                    tr_text = fetch_sentence_translation(clean_text)
                    app.after(
                        0,
                        lambda: app.sent_window.lbl_rus.config(text=tr_text),
                    )
                else:
                    app.after(
                        0,
                        lambda: app.sent_window.lbl_rus.config(text="..."),
                    )

            TRANSLATION_TIMER = threading.Timer(0.1, delayed_translation_task)
            TRANSLATION_TIMER.start()


def on_key_event(e):
    """
    Глобальный обработчик клавиатурных событий.
    Оптимизировано: кэшированная проверка раскладки + фикс бага keyboard.
    """
    global BUFFER, SENTENCE_FINISHED

    if e.event_type == "down":
        return

    # Оптимизированная проверка раскладки (кэш 500ms)
    if not is_english_layout():
        return

    # Игнорируем комбинации с модификаторами
    if keyboard.is_pressed('ctrl') or keyboard.is_pressed('alt'):
        return

    key = e.name
    key_lower = key.lower()

    # КРИТИЧНО: НЕ УДАЛЯТЬ!
    # Исправляем баг библиотеки keyboard: она возвращает русские символы
    # даже при английской раскладке (по физической позиции клавиши).
    # Без этого фикса во втором окне будет кириллица вместо латиницы.
    if key_lower in KEYBOARD_BUG_FIX:
        key = KEYBOARD_BUG_FIX[key_lower]

    update_needed = False
    need_translate = False

    # Обработка обычных символов
    if len(key) == 1:
        if SENTENCE_FINISHED and key not in [" ", ".", "!", "?", ","]:
            EDITOR.clear()
            SENTENCE_FINISHED = False
            update_needed = True

        EDITOR.insert(key)
        update_needed = True

        if re.match(r"^[a-zA-Z]$", key):
            BUFFER += key
        elif key in [" ", ".", ",", "!", "?"]:
            need_translate = True
            if BUFFER:
                process_word_async(BUFFER, APP)
                BUFFER = ""
            if key in [".", "!", "?"]:
                SENTENCE_FINISHED = True

    # Обработка пробела
    elif key_lower == "space":
        EDITOR.insert(" ")
        update_needed = True
        need_translate = True
        if BUFFER:
            process_word_async(BUFFER, APP)
            BUFFER = ""

    # Обработка Enter
    elif key_lower == "enter":
        EDITOR.insert("\n")
        update_needed = True
        need_translate = True
        SENTENCE_FINISHED = True
        if BUFFER:
            process_word_async(BUFFER, APP)
            BUFFER = ""

    # Обработка Backspace
    elif key_lower == "backspace":
        EDITOR.backspace()
        update_needed = True
        if BUFFER:
            BUFFER = BUFFER[:-1]
        SENTENCE_FINISHED = False

    # Обработка Delete
    elif key_lower == "delete":
        EDITOR.delete()
        update_needed = True
        SENTENCE_FINISHED = False

    # Навигация: Left
    elif key_lower == "left":
        EDITOR.move_left()
        update_needed = True

    # Навигация: Right
    elif key_lower == "right":
        EDITOR.move_right()
        update_needed = True

    if update_needed:
        trigger_sentence_update(APP, need_translate=need_translate)


if __name__ == "__main__":
    init_vocab()
    APP = MainWindow()

    # Регистрация callbacks
    APP.search_callback = lambda w: process_word_async(w, APP)
    APP.clipboard_callback = lambda: handle_clipboard_word(APP)

    # Установка глобальных хуков
    APP.hook_func = on_key_event
    keyboard.hook(on_key_event)
    keyboard.add_hotkey("ctrl+c", APP.clipboard_callback)

    try:
        APP.mainloop()
    finally:
        close_all_sessions()
