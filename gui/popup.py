import tkinter as tk
from gui.styles import COLORS, FONTS
import vocab  # <--- ИЗМЕНЕНИЕ 1: Импортируем весь модуль

class VocabPopup(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.overrideredirect(True)
        self.wm_attributes("-topmost", True)
        self.wm_attributes("-alpha", 0.95)
        self.configure(bg=COLORS["bg"])
        
        frame = tk.Frame(self, bg=COLORS["bg"], highlightbackground=COLORS["close_btn"], highlightthickness=2)
        frame.pack(fill="both", expand=True)
        
        tk.Label(frame, text="Ignored (Known Words):", font=("Segoe UI", 9, "bold"), bg=COLORS["bg"], fg=COLORS["close_btn"]).pack(pady=(5,2))
        
        self.text_box = tk.Text(frame, width=35, height=32, font=FONTS["console"], bg=COLORS["bg"], bd=0, fg="#586E75")
        self.text_box.pack(padx=10, pady=5)
        self.text_box.config(state="disabled")

    def update_words(self, level):
        cutoff_rank = level * 100
        if cutoff_rank == 0:
            content = "None (Show All)"
        else:
            start = max(0, cutoff_rank - 30)
            end = cutoff_rank
            
            # <--- ИЗМЕНЕНИЕ 2: Обращаемся через vocab.SORTED_WORDS
            # Теперь мы всегда видим актуальный список
            words_slice = vocab.SORTED_WORDS[start:end]
            
            ranks_slice = range(start + 1, end + 1)
            
            zipped = list(zip(ranks_slice, words_slice))
            zipped = zipped[::-1]
            
            lines = [f"{r}. {w}" for r, w in zipped]
            content = "\n".join(lines)

        self.text_box.config(state="normal")
        self.text_box.delete("1.0", "end")
        self.text_box.insert("1.0", content)
        self.text_box.config(state="disabled")
