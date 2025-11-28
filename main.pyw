import threading
import keyboard
import re
import ctypes
import tkinter as tk

from vocab import init_vocab, is_word_too_simple
from network import fetch_word_translation, fetch_examples, fetch_image, fetch_sentence_translation, \
    fetch_full_dictionary_data
from editor import TextEditorSimulator
from gui.main_window import MainWindow

# Глобальное состояние
BUFFER = ""
SENTENCE_FINISHED = False
EDITOR = TextEditorSimulator()
RU_TO_EN = {ru: en for ru, en in zip("йцукенгшщзхъфывапролджэячсмитьбю", "qwertyuiop[]asdfghjkl;'zxcvbnm,.")}

# Таймер для отложенного перевода
TRANSLATION_TIMER = None


def is_english_layout():
    try:
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        hwnd = user32.GetForegroundWindow()
        thread_id = user32.GetWindowThreadProcessId(hwnd, 0)
        layout_id = user32.GetKeyboardLayout(thread_id)
        return ((layout_id & 0xFFFF) & 0x3FF) == 0x09
    except:
        return True


# --- WORKERS (СЛОВА) ---
def worker_trans(tgt, app):
    res = fetch_word_translation(tgt)
    app.after(0, lambda: app.update_trans_ui(res, "API" if res and not res.get('cached') else "Cache"))


def worker_ex(tgt, app):
    res = fetch_examples(tgt)
    app.after(0, lambda: app.update_ex_ui(res))


def worker_img(tgt, app):
    path, src = fetch_image(tgt)
    app.after(0, lambda: app.update_img_ui(path, src))


def worker_full_data(tgt):
    """Фоновое кэширование полных данных - без обновления UI"""
    fetch_full_dictionary_data(tgt)


# --- ЛОГИКА СЛОВАРЯ (ОДИНОЧНЫЕ СЛОВА) ---
def process_word_parallel(w, app):
    too_simple, tgt = is_word_too_simple(w, app.vocab_var.get())
    if too_simple: return

    app.after(0, lambda: app.reset_ui(tgt))

    # Запускаем основные потоки для UI
    threading.Thread(target=worker_trans, args=(tgt, app), daemon=True).start()
    threading.Thread(target=worker_ex, args=(tgt, app), daemon=True).start()
    threading.Thread(target=worker_img, args=(tgt, app), daemon=True).start()

    # НОВЫЙ ПОТОК: Фоновое кэширование полных данных из dictionaryapi.dev
    threading.Thread(target=worker_full_data, args=(tgt,), daemon=True).start()


# --- ГЛАВНАЯ ФУНКЦИЯ ОБНОВЛЕНИЯ UI (FIXED) ---
def trigger_sentence_update(app):
    global TRANSLATION_TIMER

    # 1. Мгновенно обновляем английский текст (визуализация набора)
    # Используем get_text_with_cursor для отображения палочки |
    eng_display = EDITOR.get_text_with_cursor()

    # Обновляем метку через after_idle (безопасно и быстро)
    app.after_idle(lambda: app.sent_window.lbl_eng.config(text=eng_display))

    # 2. Логика "Debounce" (Отложенный перевод)
    # Если предыдущий таймер еще не сработал (мы быстро печатаем) - отменяем его
    if TRANSLATION_TIMER is not None:
        TRANSLATION_TIMER.cancel()

    # Эта функция запустится только через 0.6 секунды тишины
    def delayed_translation_task():
        clean_text = EDITOR.get_text().strip()
        if clean_text:
            # Делаем запрос к Google (это может занять время)
            tr_text = fetch_sentence_translation(clean_text)
            # Обновляем UI русского текста
            app.after(0, lambda: app.sent_window.lbl_rus.config(text=tr_text))
        else:
            app.after(0, lambda: app.sent_window.lbl_rus.config(text="..."))

    # Заводим новый таймер на 0.6 сек
    TRANSLATION_TIMER = threading.Timer(0.6, delayed_translation_task)
    TRANSLATION_TIMER.start()


# --- KEYBOARD HOOK ---
def on_key_event(e):
    global BUFFER, SENTENCE_FINISHED
    if e.event_type == 'down': return

    if not is_english_layout(): return

    key = e.name
    key_lower = key.lower()
    if key_lower in RU_TO_EN: key = RU_TO_EN[key_lower]

    update_needed = False

    # 1. СИМВОЛЫ
    if len(key) == 1:
        # Если начали писать после точки - сброс
        if SENTENCE_FINISHED and key not in [' ', '.', '!', '?', ',']:
            EDITOR.clear()
            SENTENCE_FINISHED = False
            update_needed = True

        EDITOR.insert(key)
        update_needed = True

        # Логика сбора отдельного слова для словаря
        if re.match(r'^[a-zA-Z]$', key):
            BUFFER += key
        elif key in [' ', '.', ',', '!', '?']:
            if BUFFER:
                threading.Thread(target=process_word_parallel, args=(BUFFER, APP), daemon=True).start()
                BUFFER = ""
            if key in ['.', '!', '?']:
                SENTENCE_FINISHED = True

    # 2. ПРОБЕЛ
    elif key_lower == 'space':
        EDITOR.insert(" ")
        update_needed = True
        if BUFFER:
            threading.Thread(target=process_word_parallel, args=(BUFFER, APP), daemon=True).start()
            BUFFER = ""

    # 3. УДАЛЕНИЕ
    elif key_lower == 'backspace':
        EDITOR.backspace()
        update_needed = True
        if BUFFER: BUFFER = BUFFER[:-1]
        SENTENCE_FINISHED = False

    elif key_lower == 'delete':
        EDITOR.delete()
        update_needed = True
        SENTENCE_FINISHED = False

    # 4. НАВИГАЦИЯ
    elif key_lower == 'left':
        EDITOR.move_left()
        update_needed = True

    elif key_lower == 'right':
        EDITOR.move_right()
        update_needed = True

    # Запускаем обновление, если текст изменился
    if update_needed:
        trigger_sentence_update(APP)


if __name__ == "__main__":
    init_vocab()
    APP = MainWindow()
    APP.hook_func = on_key_event  # Для возврата хука после настроек
    keyboard.hook(on_key_event)
    APP.mainloop()
