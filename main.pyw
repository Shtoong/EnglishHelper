import threading
import keyboard
import re
import ctypes
import tkinter as tk
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
    download_and_cache_audio,
    streaming_play_and_cache,
    close_all_sessions
)
from editor import TextEditorSimulator
from gui.main_window import MainWindow

BUFFER = ""
SENTENCE_FINISHED = False
EDITOR = TextEditorSimulator()
RU_TO_EN = {
    ru: en
    for ru, en in zip(
        "йцукенгшщзхъфывапролджэячсмитьбю",
        "qwertyuiop[]asdfghjkl;'zxcvbnm,.",
    )
}

TRANSLATION_TIMER = None
CLIPBOARD_LAST_WORD = ""


def is_english_layout():
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        hwnd = user32.GetForegroundWindow()
        thread_id = user32.GetWindowThreadProcessId(hwnd, 0)
        layout_id = user32.GetKeyboardLayout(thread_id)
        return ((layout_id & 0xFFFF) & 0x3FF) == 0x09
    except:
        return True


# ===== WORKERS =====

def worker_trans(tgt, app):
    res = fetch_word_translation(tgt)
    app.after(
        0,
        lambda: app.update_trans_ui(
            res or {},
            "API" if res and not res.get("cached") else "—"
        ),
    )


def worker_img(tgt, app):
    path, src = fetch_image(tgt)
    app.after(0, lambda: app.update_img_ui(path, src))


def _instant_auto_pronounce(word, app):
    """
    ✅ ИСПРАВЛЕНО: ТОЛЬКО Google TTS US с активным ожиданием
    """
    try:
        from playsound import playsound

        # ✅ ТОЛЬКО US от Google (гарантированно кэшируется)
        cache_path = get_audio_cache_path(word, "us")

        # Ждём до 2 секунд готовности файла
        max_wait = 20  # 20 * 0.1s = 2 секунды
        for attempt in range(max_wait):
            if os.path.exists(cache_path) and os.path.getsize(cache_path) > 1000:
                try:
                    playsound(cache_path)
                    print(f"✅ Auto-played US: {word}")
                    return
                except Exception as e:
                    print(f"Play error: {e}")
                    break
            time.sleep(0.1)

        # Если файл так и не появился - streaming fallback
        url = get_google_tts_url(word, "us")
        streaming_play_and_cache(url, cache_path)

    except Exception as e:
        print(f"Auto-pronounce error: {e}")


def worker_full_data_display(tgt, app):
    """
    ✅ ИСПРАВЛЕНО: Автопроизношение работает даже без определений
    """
    # 1. Проверяем кэш
    full_data = load_full_dictionary_data(tgt)

    # 2. Если нет в кэше - загружаем СИНХРОННО (внутри кэшируется Google TTS US)
    if not full_data:
        full_data = fetch_full_dictionary_data(tgt)

    # 3. Обновляем UI
    app.after(0, lambda: app.update_full_data_ui(full_data))

    # 4. ✅ КРИТИЧНО: Автопроизношение ВСЕГДА (файл УЖЕ готов)
    if cfg.get_bool("USER", "AutoPronounce"):
        _instant_auto_pronounce(tgt, app)


def process_word_parallel(w, app):
    too_simple, tgt = is_word_too_simple(w, app.vocab_var.get())
    if too_simple:
        return

    app.after(0, lambda: app.reset_ui(tgt))

    cached_res = check_cache_only(tgt)
    if cached_res:
        app.update_trans_ui(cached_res, "Cache")
    else:
        threading.Thread(target=worker_trans, args=(tgt, app), daemon=True).start()

    threading.Thread(target=worker_img, args=(tgt, app), daemon=True).start()
    threading.Thread(target=worker_full_data_display, args=(tgt, app), daemon=True).start()


def handle_clipboard_word(app):
    global CLIPBOARD_LAST_WORD
    time.sleep(0.1)
    try:
        text = pyperclip.paste()
    except Exception:
        return

    if not text:
        return
    text = text.strip()

    if not (0 < len(text) <= 50):
        return
    if not re.match(r"^[a-zA-Z\-']+$", text):
        return

    lowered = text.lower()
    if lowered == CLIPBOARD_LAST_WORD:
        return

    CLIPBOARD_LAST_WORD = lowered
    threading.Thread(
        target=process_word_parallel, args=(text, app), daemon=True
    ).start()


def trigger_sentence_update(app, need_translate=False):
    global TRANSLATION_TIMER

    eng_display = EDITOR.get_text_with_cursor()
    app.after_idle(lambda: app.sent_window.lbl_eng.config(text=eng_display))

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
    global BUFFER, SENTENCE_FINISHED
    if e.event_type == "down":
        return
    if not is_english_layout():
        return

    if keyboard.is_pressed('ctrl') or keyboard.is_pressed('alt'):
        return

    key = e.name
    key_lower = key.lower()
    if key_lower in RU_TO_EN:
        key = RU_TO_EN[key_lower]

    update_needed = False
    need_translate = False

    if len(key) == 1:
        if (SENTENCE_FINISHED and key not in [" ", ".", "!", "?", ","]):
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
                threading.Thread(
                    target=process_word_parallel,
                    args=(BUFFER, APP),
                    daemon=True,
                ).start()
                BUFFER = ""
            if key in [".", "!", "?"]:
                SENTENCE_FINISHED = True

    elif key_lower == "space":
        EDITOR.insert(" ")
        update_needed = True
        need_translate = True
        if BUFFER:
            threading.Thread(
                target=process_word_parallel,
                args=(BUFFER, APP),
                daemon=True,
            ).start()
            BUFFER = ""

    elif key_lower == "enter":
        EDITOR.insert("\n")
        update_needed = True
        need_translate = True
        SENTENCE_FINISHED = True
        if BUFFER:
            threading.Thread(
                target=process_word_parallel,
                args=(BUFFER, APP),
                daemon=True,
            ).start()
            BUFFER = ""

    elif key_lower == "backspace":
        EDITOR.backspace()
        update_needed = True
        if BUFFER:
            BUFFER = BUFFER[:-1]
        SENTENCE_FINISHED = False

    elif key_lower == "delete":
        EDITOR.delete()
        update_needed = True
        SENTENCE_FINISHED = False

    elif key_lower == "left":
        EDITOR.move_left()
        update_needed = True

    elif key_lower == "right":
        EDITOR.move_right()
        update_needed = True

    if update_needed:
        trigger_sentence_update(APP, need_translate=need_translate)


if __name__ == "__main__":
    init_vocab()
    APP = MainWindow()

    APP.search_callback = lambda w: threading.Thread(
        target=process_word_parallel, args=(w, APP), daemon=True
    ).start()

    APP.clipboard_callback = lambda: handle_clipboard_word(APP)

    APP.hook_func = on_key_event
    keyboard.hook(on_key_event)
    keyboard.add_hotkey("ctrl+c", APP.clipboard_callback)

    try:
        APP.mainloop()
    finally:
        close_all_sessions()
