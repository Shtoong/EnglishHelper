"""
EnglishHelper - Главный модуль запуска.

Интегрирует:
- InputManager: обработка клавиатуры и clipboard
- SentenceManager: управление предложениями и переводом
- WordProcessor: обработка слов и загрузка данных
- GUI компоненты: MainWindow, SentenceWindow

Architecture:
- Модульная структура с чёткими границами ответственности
- Callback-based интеграция между компонентами
- Централизованная инициализация и cleanup
"""

from vocab import init_vocab
from network import close_all_sessions
from editor import TextEditorSimulator
from gui.main_window import MainWindow

# Импорт новых менеджеров
from input_manager import InputManager
from sentence_manager import SentenceManager
from word_processor import WordProcessor


def main():
    """
    Главная точка входа приложения.

    Последовательность инициализации:
    1. Загрузка частотного словаря
    2. Создание GUI компонентов
    3. Инициализация менеджеров
    4. Регистрация callbacks
    5. Запуск event loop
    6. Cleanup при завершении
    """
    # ===== ИНИЦИАЛИЗАЦИЯ ДАННЫХ =====
    init_vocab()

    # ===== СОЗДАНИЕ GUI =====
    app = MainWindow()

    # ===== СОЗДАНИЕ МЕНЕДЖЕРОВ =====
    # TextEditorSimulator для второго окна
    editor = TextEditorSimulator()

    # Менеджер обработки слов
    word_processor = WordProcessor(app)

    # Менеджер предложений
    sentence_manager = SentenceManager(app.sent_window, editor)

    # Менеджер ввода (keyboard + clipboard)
    input_manager = InputManager(
        on_word_complete=word_processor.process_word,
        on_sentence_update=sentence_manager.update_display
    )

    # ===== РЕГИСТРАЦИЯ CALLBACKS =====
    # Callback для клика по синониму в главном окне
    app.search_callback = word_processor.process_word

    # ===== ЗАПУСК =====
    input_manager.start_listening()

    try:
        # Главный event loop
        app.mainloop()
    finally:
        # ===== CLEANUP =====
        input_manager.stop_listening()
        sentence_manager.cancel_pending_translation()
        close_all_sessions()


if __name__ == "__main__":
    main()
