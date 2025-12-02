"""
Переиспользуемые кнопки для EnglishHelper.

Содержит:
- ToggleButton: Кнопка-переключатель с двумя состояниями (on/off)
- ActionButton: Кнопка для однократных действий
"""

import tkinter as tk
from typing import Callable
from config import cfg
from gui.styles import COLORS


class ToggleButton(tk.Label):
    """
    Кнопка-переключатель с автоматической синхронизацией состояния с config.

    Features:
    - Автоматическое чтение состояния из config при создании
    - Hover эффекты с сохранением состояния
    - Визуальная индикация on/off через цвета

    Цветовая схема:
    - Enabled: accent bg + dark fg (яркая кнопка)
    - Disabled: secondary bg + faint fg (приглушенная)
    - Hover: всегда accent bg + dark fg (независимо от состояния)
    """

    def __init__(self, parent: tk.Widget, text: str, config_key: str,
                 command: Callable, **kwargs):
        """
        Args:
            parent: Родительский виджет
            text: Текст кнопки
            config_key: Ключ в config.USER для хранения состояния (bool)
            command: Callback вызываемый при клике
            **kwargs: Дополнительные параметры для tk.Label
        """
        # Настройки по умолчанию
        defaults = {
            "font": ("Segoe UI", 8),
            "cursor": "hand2",
            "padx": 8,
            "pady": 3,
            "relief": "flat"
        }
        defaults.update(kwargs)

        super().__init__(parent, text=text, **defaults)

        self.config_key = config_key
        self.command = command

        # Привязка событий
        self.bind("<Button-1>", self._on_click)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)

        # Установка начального состояния из config
        self.sync_state()

    def _on_click(self, event):
        """Обработка клика с передачей в callback"""
        self.command(event)
        # После выполнения команды синхронизируем визуальное состояние
        self.sync_state()

    def _on_enter(self, event):
        """Hover эффект: всегда яркая кнопка"""
        self.config(bg=COLORS["text_accent"], fg=COLORS["bg"])

    def _on_leave(self, event):
        """Возврат к состоянию на основе config"""
        self.sync_state()

    def sync_state(self):
        """
        Синхронизирует визуальное состояние кнопки с значением в config.

        Вызывается:
        - При создании кнопки
        - После клика (для обновления визуального состояния)
        - При программном изменении config извне
        """
        is_enabled = cfg.get_bool("USER", self.config_key, True)
        self.config(
            bg=COLORS["text_accent"] if is_enabled else COLORS["bg_secondary"],
            fg=COLORS["bg"] if is_enabled else COLORS["text_faint"]
        )


class ActionButton(tk.Label):
    """
    Кнопка для однократных действий без сохранения состояния.

    Отличие от ToggleButton:
    - Нет привязки к config
    - Простые hover эффекты
    - Используется для команд: "Clear Cache", "Export", etc.
    """

    def __init__(self, parent: tk.Widget, text: str, command: Callable, **kwargs):
        """
        Args:
            parent: Родительский виджет
            text: Текст кнопки
            command: Callback вызываемый при клике
            **kwargs: Дополнительные параметры для tk.Label
        """
        # Настройки по умолчанию
        defaults = {
            "font": ("Segoe UI", 8),
            "bg": COLORS["bg_secondary"],
            "fg": COLORS["text_main"],
            "cursor": "hand2",
            "padx": 8,
            "pady": 3,
            "relief": "flat"
        }
        defaults.update(kwargs)

        super().__init__(parent, text=text, **defaults)

        self.command = command

        # Привязка событий
        self.bind("<Button-1>", self.command)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)

    def _on_enter(self, event):
        """Hover эффект: яркая кнопка"""
        self.config(bg=COLORS["text_accent"], fg=COLORS["bg"])

    def _on_leave(self, event):
        """Возврат к обычному состоянию"""
        self.config(bg=COLORS["bg_secondary"], fg=COLORS["text_main"])
