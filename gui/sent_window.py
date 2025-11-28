import tkinter as tk
from config import cfg
from gui.styles import COLORS, FONTS

class SentenceWindow(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.overrideredirect(True)
        self.wm_attributes("-topmost", True)
        
        x = cfg.get("USER", "WindowSentX", "450")
        y = cfg.get("USER", "WindowSentY", "100")
        
        self.geometry(f"900x200+{x}+{y}")
        self.configure(bg=COLORS["bg"])
        
        self.frame = tk.Frame(self, bg=COLORS["bg"], highlightbackground=COLORS["text_faint"], highlightthickness=1)
        self.frame.pack(fill="both", expand=True)

        self.lbl_eng = tk.Label(self.frame, text="Start typing...", font=("Georgia", 14, "italic"), bg=COLORS["bg"], fg="#586E75", wraplength=880)
        self.lbl_eng.pack(pady=(15, 5))
        
        tk.Frame(self.frame, height=1, bg=COLORS["text_faint"], width=800).pack(pady=5)

        self.lbl_rus = tk.Label(self.frame, text="...", font=("Georgia", 24), bg=COLORS["bg"], fg=COLORS["text_accent"], wraplength=880)
        self.lbl_rus.pack(pady=(5, 15))

        self.dragging_allowed = False
        for w in [self.frame, self.lbl_eng, self.lbl_rus]:
            w.bind("<Button-1>", self.start_move)
            w.bind("<B1-Motion>", self.do_move)
            w.bind("<ButtonRelease-1>", self.stop_move)

        # При старте проверяем, нужно ли показывать окно
        if not cfg.get_bool("USER", "ShowSentenceWindow"):
            self.withdraw()

    def update_content(self, eng_text, rus_text):
        self.lbl_eng.config(text=eng_text)
        self.lbl_rus.config(text=rus_text)

    # НОВЫЕ МЕТОДЫ УПРАВЛЕНИЯ ВИДИМОСТЬЮ
    def show(self):
        self.deiconify()
        
    def hide(self):
        self.withdraw()

    def start_move(self, event):
        self.dragging_allowed = True; self.x = event.x; self.y = event.y
    def do_move(self, event):
        if not self.dragging_allowed: return
        x = self.winfo_x() + (event.x - self.x); y = self.winfo_y() + (event.y - self.y)
        self.geometry(f"+{x}+{y}")
    def stop_move(self, event):
        if self.dragging_allowed:
            cfg.set("USER", "WindowSentX", self.winfo_x())
            cfg.set("USER", "WindowSentY", self.winfo_y())
        self.dragging_allowed = False
