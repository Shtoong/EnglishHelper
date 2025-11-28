import tkinter as tk
from tkinter import messagebox
from PIL import Image, ImageTk
import keyboard
from config import cfg
from gui.styles import COLORS, FONTS
from gui.popup import VocabPopup
from gui.sent_window import SentenceWindow

class MainWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.COLORS = COLORS
        self.FONTS = FONTS
        
        self.overrideredirect(True)
        self.wm_attributes("-topmost", True)
        
        x = cfg.get("USER", "WindowX", "100")
        y = cfg.get("USER", "WindowY", "100")
        self.geometry(f"320x480+{x}+{y}")
        self.configure(bg=self.COLORS["bg"])
        
        self.sources = {"trans": "wait", "img": "wait"}
        self.dragging_allowed = False
        self.popup = None
        
        self.sent_window = SentenceWindow(self)
        
        self._init_ui()
        self._bind_events()

    def _init_ui(self):
        btn_close = tk.Label(self, text="✕", font=("Arial", 12), bg=self.COLORS["bg"], fg=self.COLORS["text_faint"], cursor="hand2")
        btn_close.place(x=295, y=5)
        btn_close.bind("<Button-1>", lambda e: self.close_app())
        
        btn_settings = tk.Label(self, text="⚙", font=("Arial", 14), bg=self.COLORS["bg"], fg=self.COLORS["text_faint"], cursor="hand2")
        btn_settings.place(x=265, y=3)
        btn_settings.bind("<Button-1>", lambda e: self.open_settings())

        self.lbl_word = tk.Label(self, text="English Helper", font=self.FONTS["header"], bg=self.COLORS["bg"], fg=self.COLORS["text_header"])
        self.lbl_word.pack(pady=(20, 0), anchor="center")
        
        self.lbl_trans = tk.Label(self, text="", font=self.FONTS["trans"], bg=self.COLORS["bg"], fg=self.COLORS["text_faint"])
        self.lbl_trans.pack(anchor="center")
        
        sep = tk.Frame(self, height=1, bg=self.COLORS["separator"], width=260); sep.pack(pady=12)
        
        self.lbl_rus = tk.Label(self, text="Ready", font=self.FONTS["main"], bg=self.COLORS["bg"], fg=self.COLORS["text_main"], wraplength=300, justify="center")
        self.lbl_rus.pack(anchor="center", padx=10)
        
        self.lbl_ex = tk.Label(self, text="", font=self.FONTS["example"], bg=self.COLORS["bg"], fg=self.COLORS["text_accent"], wraplength=280, justify="center")
        self.lbl_ex.pack(anchor="center", padx=20, pady=(5,0))
        
        self.canvas = tk.Label(self, bg=self.COLORS["bg"]); self.canvas.pack(pady=15, fill="both", expand=True)
        
        self.slider_frame = tk.Frame(self, bg=self.COLORS["bg"]); self.slider_frame.pack(side="bottom", fill="x", padx=10, pady=5)
        tk.Label(self.slider_frame, text="Vocab:", font=self.FONTS["ui"], bg=self.COLORS["bg"], fg=self.COLORS["text_faint"]).pack(side="left")
        
        self.vocab_var = tk.IntVar(value=int(cfg.get("USER", "VocabLevel")))
        
        btn_minus = tk.Label(self.slider_frame, text="<", font=("Consolas", 12, "bold"), bg=self.COLORS["bg"], fg=self.COLORS["text_accent"], cursor="hand2")
        btn_minus.pack(side="left", padx=2)
        btn_minus.bind("<Button-1>", lambda e: self.change_level(-1))
        
        self.scale = tk.Scale(self.slider_frame, from_=0, to=100, orient="horizontal", variable=self.vocab_var, showvalue=0, bg=self.COLORS["bg"], troughcolor="#EEE8D5", activebackground=self.COLORS["text_accent"], bd=0, highlightthickness=0, length=160)
        self.scale.pack(side="left", padx=2)
        
        btn_plus = tk.Label(self.slider_frame, text=">", font=("Consolas", 12, "bold"), bg=self.COLORS["bg"], fg=self.COLORS["text_accent"], cursor="hand2")
        btn_plus.pack(side="left", padx=2)
        btn_plus.bind("<Button-1>", lambda e: self.change_level(1))

        self.lbl_lvl_val = tk.Label(self.slider_frame, text=str(self.vocab_var.get()), font=("Segoe UI", 9, "bold"), bg=self.COLORS["bg"], fg=self.COLORS["text_header"])
        self.lbl_lvl_val.pack(side="left", padx=(5,0))
        
        self.scale.config(command=lambda v: self.lbl_lvl_val.config(text=v))
        
        self.lbl_status = tk.Label(self, text="Waiting...", font=("Segoe UI", 7), bg=self.COLORS["bg"], fg=self.COLORS["text_faint"])
        self.lbl_status.pack(side="bottom", anchor="e", padx=10)

    def _bind_events(self):
        self.bind("<Button-1>", self.start_move)
        self.bind("<B1-Motion>", self.do_move)
        self.bind("<ButtonRelease-1>", self.stop_move)
        
        self.scale.bind("<ButtonPress-1>", self.show_popup)
        self.scale.bind("<B1-Motion>", self.move_popup)
        self.scale.bind("<ButtonRelease-1>", self.hide_popup_and_save)
        
        for w in [self.lbl_word, self.lbl_trans, self.lbl_rus, self.lbl_ex, self.canvas, self.lbl_status, self.slider_frame]:
            w.bind("<Button-1>", self.start_move)
            w.bind("<B1-Motion>", self.do_move)
            w.bind("<ButtonRelease-1>", self.stop_move)

    def refresh_status(self):
        self.lbl_status.config(text=f"Tr: {self.sources['trans']} • Img: {self.sources['img']}")

    def update_trans_ui(self, data, source):
        if data:
            self.lbl_trans.config(text=f"[{data['trans']}]")
            self.lbl_rus.config(text=data['rus'])
            self.sources['trans'] = source
        else:
            self.sources['trans'] = "-"
        self.refresh_status()

    def update_ex_ui(self, data):
        if data: self.lbl_ex.config(text=data['ex_text'])

    def update_img_ui(self, path, source):
        if path:
            try:
                pil = Image.open(path); pil.thumbnail((280, 180))
                tki = ImageTk.PhotoImage(pil)
                self.canvas.config(image=tki); self.canvas.image = tki
                self.sources['img'] = source
            except: self.sources['img'] = "Err"
        else: self.sources['img'] = "-"
        self.refresh_status()

    def reset_ui(self, word):
        self.lbl_word.config(text=word)
        self.lbl_trans.config(text="")
        self.lbl_rus.config(text="Searching...")
        self.lbl_ex.config(text="")
        self.canvas.config(image="")
        self.sources = {"trans": "...", "img": "..."}
        self.refresh_status()

    def change_level(self, delta):
        new_val = self.vocab_var.get() + delta
        if 0 <= new_val <= 100:
            self.vocab_var.set(new_val)
            self.lbl_lvl_val.config(text=str(new_val))
            self.save_level()

    def show_popup(self, event):
        self.dragging_allowed = False
        if not self.popup:
            self.popup = VocabPopup(self)
            x = self.winfo_x() + 330; y = self.winfo_y() - 50
            self.popup.geometry(f"220x550+{x}+{y}")
        self.update_popup_content()
    
    def move_popup(self, event):
        self.lbl_lvl_val.config(text=str(self.vocab_var.get()))
        self.update_popup_content()

    def update_popup_content(self):
        if self.popup: self.popup.update_words(self.vocab_var.get())

    def hide_popup_and_save(self, event):
        if self.popup:
            self.popup.destroy(); self.popup = None
        self.save_level()
        self.dragging_allowed = False

    def save_level(self, event=None):
        cfg.set("USER", "VocabLevel", self.vocab_var.get())

    def open_settings(self):
        keyboard.unhook_all()
        top = tk.Toplevel(self); top.title("Settings"); top.geometry("350x350"); top.configure(bg=self.COLORS["bg"]); top.attributes("-topmost", True)
        
        tk.Label(top, text="Settings", font=("Georgia", 14, "bold"), bg=self.COLORS["bg"], fg=self.COLORS["text_header"]).pack(pady=10)
        
        # API Keys
        tk.Label(top, text="Yandex Dictionary Key:", bg=self.COLORS["bg"], fg=self.COLORS["text_main"]).pack(anchor="w", padx=20)
        entry_yandex = tk.Entry(top, width=45, bg="#EEE8D5", bd=0); entry_yandex.pack(padx=20, pady=5, ipady=3)
        entry_yandex.insert(0, cfg.get("API", "YandexKey"))
        
        tk.Label(top, text="Pexels API Key:", bg=self.COLORS["bg"], fg=self.COLORS["text_main"]).pack(anchor="w", padx=20)
        entry_pexels = tk.Entry(top, width=45, bg="#EEE8D5", bd=0); entry_pexels.pack(padx=20, pady=5, ipady=3)
        entry_pexels.insert(0, cfg.get("API", "PexelsKey"))
        
        # Sentence Window Checkbox
        show_sent_var = tk.BooleanVar(value=cfg.get_bool("USER", "ShowSentenceWindow"))
        
        # Стилизованный чекбокс
        chk_frame = tk.Frame(top, bg=self.COLORS["bg"])
        chk_frame.pack(anchor="w", padx=20, pady=15)
        chk = tk.Checkbutton(chk_frame, text="Show Sentence Window", variable=show_sent_var, 
                             onvalue=True, offvalue=False, 
                             bg=self.COLORS["bg"], fg=self.COLORS["text_main"], 
                             selectcolor="#EEE8D5", activebackground=self.COLORS["bg"])
        chk.pack(side="left")
        
        def save_and_close():
            cfg.set("API", "YandexKey", entry_yandex.get().strip())
            cfg.set("API", "PexelsKey", entry_pexels.get().strip())
            
            # Сохраняем состояние чекбокса
            new_state = show_sent_var.get()
            cfg.set("USER", "ShowSentenceWindow", new_state)
            
            # Применяем изменения сразу
            if new_state:
                self.sent_window.show()
            else:
                self.sent_window.hide()
                
            top.destroy()
            if hasattr(self, 'hook_func'): keyboard.hook(self.hook_func)
            messagebox.showinfo("Saved", "Settings saved!")
            
        def on_close():
            top.destroy()
            if hasattr(self, 'hook_func'): keyboard.hook(self.hook_func)

        tk.Button(top, text="Save", command=save_and_close, bg=self.COLORS["text_accent"], fg="white", font=("Segoe UI", 10, "bold"), bd=0, padx=20, pady=5, cursor="hand2").pack(pady=10)
        top.protocol("WM_DELETE_WINDOW", on_close)

    def start_move(self, event):
        if str(event.widget) == str(self.scale) or event.widget.master == self.slider_frame:
             if event.widget != self.slider_frame:
                 self.dragging_allowed = False
                 return
        self.dragging_allowed = True
        self.x = event.x; self.y = event.y

    def do_move(self, event):
        if not self.dragging_allowed: return
        x = self.winfo_x() + (event.x - self.x); y = self.winfo_y() + (event.y - self.y)
        self.geometry(f"+{x}+{y}")

    def stop_move(self, event):
        if self.dragging_allowed:
            cfg.set("USER", "WindowX", self.winfo_x())
            cfg.set("USER", "WindowY", self.winfo_y())
        self.dragging_allowed = False

    def close_app(self):
        keyboard.unhook_all()
        self.destroy()
        sys.exit(0)
