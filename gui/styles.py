"""
UI theme definitions for EnglishHelper.

Based on Monkeytype's Serika Dark color scheme.
All UI components should reference these constants instead of hardcoding values.

Color philosophy:
- High contrast for readability during typing practice
- Matte palette to reduce eye strain
- Consistent accent color (#E2B714) for focus elements

Font philosophy:
- Segoe UI for general text (native Windows rendering)
- Consolas for monospace elements (phonetics, console)
- Hierarchical sizing for visual importance
"""

from typing import Final

# ===== COLOR SCHEME =====
COLORS: Final[dict[str, str]] = {
    # === BACKGROUNDS ===
    "bg": "#323437",  # Main window background (soft dark gray)
    "bg_secondary": "#2C2E31",  # Buttons, sliders, input fields (darker gray)

    # === TEXT COLORS ===
    "text_main": "#D1D0C5",  # Primary text (light gray/beige)
    "text_header": "#E2B714",  # Main word display (Monkeytype signature yellow)
    "text_accent": "#E2B714",  # Examples, highlights, active elements
    "text_faint": "#646669",  # Secondary info, timestamps, disabled state
    "text_phonetic": "#646669",  # Phonetic transcription (subdued)
    "text_pos": "#E2B714",  # Part of speech tags (accent)

    # === UI ELEMENTS ===
    "close_btn": "#CA4754",  # Close button (soft red/error color)
    "separator": "#646669",  # Horizontal dividers
    "button_bg": "#2C2E31",  # Button backgrounds
    "resize_grip": "#646669",  # Window resize handle
}

# ===== FONT DEFINITIONS =====
FONTS: Final[dict[str, tuple]] = {
    # === HEADERS & TITLES ===
    "header": ("Segoe UI", 18, "bold"),  # Main word display
    "close_btn": ("Arial", 12),  # Close button (X)

    # === TRANSLATION DISPLAY ===
    "translation": ("Segoe UI", 33),  # Primary translation (large, prominent)

    # === DICTIONARY DATA ===
    "phonetic": ("Consolas", 11),  # Phonetic transcription (monospace)
    "pos": ("Segoe UI", 10, "italic"),  # Part of speech
    "definition": ("Segoe UI", 11),  # Word definitions
    "example": ("Segoe UI", 10, "italic"),  # Usage examples

    # === SYNONYMS ===
    "synonym": ("Segoe UI", 10),  # Synonym tags
    "synonym_label": ("Segoe UI", 9, "bold"),  # "Syn:" label

    # === UI CONTROLS ===
    "audio_btn": ("Segoe UI", 9),  # Audio playback buttons (US/UK)
    "tooltip": ("Segoe UI", 10),  # Hover translation tooltips
    "ui": ("Segoe UI", 9),  # General UI elements (labels, buttons)
    "console": ("Consolas", 8),  # Monospace text (popup word list)

    # === SENTENCE WINDOW ===
    "sentence_text": ("Segoe UI", 12),  # English sentence display
}
