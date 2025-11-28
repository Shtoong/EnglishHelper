import tkinter as tk
from tkinter import messagebox
from PIL import Image, ImageTk
import keyboard
import sys
import os
import threading
import requests

from playsound import playsound

from config import cfg
from gui.styles import COLORS, FONTS
from gui.popup import VocabPopup
from gui.sent_window import SentenceWindow


class ResizeGrip(tk.Label):
    """Виджет-треугольник для изменения размера окна"""

    def __init__(self, parent, resize_callback, finish_callback, bg, fg):
        super().__init__(parent, text="◢", font=("Arial", 10), bg=bg, fg=fg, cursor="sizing")
        self.parent = parent
        self.resize_callback = resize_callback
        self.finish_callback = finish_callback
        self.bind("<Button-1>", self._start_resize)
        self.bind("<B1-Motion>", self._do_resize)
        self.bind("<ButtonRelease-1>", self._stop_resize)
        self._x = 0
        self._y = 0

    def _start_resize(self, event):
        self._x = event.x
        self._y = event.y

    def _do_resize(self, event):
        dx = event.x - self._x
        dy = event.y - self._y
        self.resize_callback(dx, dy)

    def _stop_resize(self, event):
        self.finish_callback()


class MainWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.COLORS = COLORS
        self.FONTS = FONTS

        self.overrideredirect(True)
        self.wm_attributes("-topmost", True)

        # Загрузка геометрии из конфига
        x = cfg.get("USER", "WindowX", "100")
        y = cfg.get("USER", "WindowY", "100")
        w = cfg.get("USER", "WindowWidth", "400")
        h = cfg.get("USER", "WindowHeight", "700")

        self.geometry(f"{w}x{h}+{x}+{y}")
        self.configure(bg=self.COLORS["bg"])

        self.sources = {"trans": "wait", "img": "wait"}
        self.dragging_allowed = False
        self.popup = None
        self.current_audio_urls = []
        self.current_image = None

        self.sent_window = SentenceWindow(self)

        self._init_ui()
        self._bind_events()

    # ---------------- UI ----------------

    def _init_ui(self):
        # Верхняя панель (кнопки)
        top_bar = tk.Frame(self, bg=self.COLORS["bg"], height=30)
        top_bar.pack(fill="x", pady=(5, 0))

        btn_close = tk.Label(
            top_bar, text="✕", font=("Arial", 12), bg=self.COLORS["bg"],
            fg=self.COLORS["close_btn"], cursor="hand2"
        )
        btn_close.pack(side="right", padx=10)
        btn_close.bind("<Button-1>", lambda e: self.close_app())

        btn_settings = tk.Label(
            top_bar, text="⚙", font=("Arial", 14), bg=self.COLORS["bg"],
            fg=self.COLORS["text_faint"], cursor="hand2"
        )
        btn_settings.pack(side="right", padx=5)
        btn_settings.bind("<Button-1>", lambda e: self.open_settings())

        # Заголовок - слово
        self.lbl_word = tk.Label(
            self, text="English Helper", font=self.FONTS["header"],
            bg=self.COLORS["bg"], fg=self.COLORS["text_header"]
        )
        self.lbl_word.pack(pady=(10, 5), anchor="center")

        # Транскрипция + аудио-кнопки
        phonetic_frame = tk.Frame(self, bg=self.COLORS["bg"])
        phonetic_frame.pack(anchor="center", pady=5)

        self.lbl_phonetic = tk.Label(
            phonetic_frame, text="", font=self.FONTS["phonetic"],
            bg=self.COLORS["bg"], fg=self.COLORS["text_phonetic"]
        )
        self.lbl_phonetic.pack(side="left", padx=5)

        self.btn_audio_us = tk.Label(
            phonetic_frame, text="🔊 US", font=("Segoe UI", 9),
            bg=self.COLORS["button_bg"], fg=self.COLORS["text_main"],
            cursor="hand2", padx=5, pady=2
        )
        self.btn_audio_us.pack(side="left", padx=2)
        self.btn_audio_us.bind("<Button-1>", lambda e: self.play_audio(0))

        self.btn_audio_uk = tk.Label(
            phonetic_frame, text="🔊 UK", font=("Segoe UI", 9),
            bg=self.COLORS["button_bg"], fg=self.COLORS["text_main"],
            cursor="hand2", padx=5, pady=2
        )
        self.btn_audio_uk.pack(side="left", padx=2)
        self.btn_audio_uk.bind("<Button-1>", lambda e: self.play_audio(1))

        # Русский перевод
        self.lbl_rus = tk.Label(
            self, text="Ready", font=self.FONTS["definition"],
            bg=self.COLORS["bg"], fg=self.COLORS["text_main"],
            wraplength=380, justify="center"
        )
        self.lbl_rus.pack(anchor="center", padx=10, pady=(5, 10))

        # Картинка
        self.img_container = tk.Label(self, bg=self.COLORS["bg"])
        self.img_container.pack(pady=5)

        tk.Frame(self, height=1, bg=self.COLORS["separator"], width=360).pack(pady=5)

        # --- Скроллируемая область ---
        scroll_container = tk.Frame(self, bg=self.COLORS["bg"])
        scroll_container.pack(fill="both", expand=True, padx=10, pady=5)

        self.canvas_scroll = tk.Canvas(
            scroll_container, bg=self.COLORS["bg"], highlightthickness=0
        )

        self.scrollbar = tk.Scrollbar(
            scroll_container, orient="vertical", command=self.canvas_scroll.yview
        )

        self.scrollable_frame = tk.Frame(self.canvas_scroll, bg=self.COLORS["bg"])

        self.scrollable_frame.bind("<Configure>", self._on_frame_configure)
        self.canvas_scroll.bind("<Configure>", self._on_canvas_configure)

        self.canvas_scroll.create_window(
            (0, 0), window=self.scrollable_frame, anchor="nw"
        )
        self.canvas_scroll.configure(yscrollcommand=self.scrollbar.set)

        self.canvas_scroll.pack(side="left", fill="both", expand=True)

        self.canvas_scroll.bind_all("<MouseWheel>", self._on_mousewheel)

        # Нижняя панель (Слайдер + Статус + Grip)
        self.bottom_frame = tk.Frame(self, bg=self.COLORS["bg"])
        self.bottom_frame.pack(side="bottom", fill="x", padx=0, pady=0)

        # Слайдер (в отдельном фрейме внутри bottom_frame)
        slider_area = tk.Frame(self.bottom_frame, bg=self.COLORS["bg"])
        slider_area.pack(side="top", fill="x", padx=10, pady=(5, 0))

        tk.Label(
            slider_area, text="Vocab:", font=self.FONTS["ui"],
            bg=self.COLORS["bg"], fg=self.COLORS["text_faint"]
        ).pack(side="left")

        self.vocab_var = tk.IntVar(value=int(cfg.get("USER", "VocabLevel")))

        btn_minus = tk.Label(
            slider_area, text="<", font=("Consolas", 12, "bold"),
            bg=self.COLORS["bg"], fg=self.COLORS["text_accent"], cursor="hand2"
        )
        btn_minus.pack(side="left", padx=2)
        btn_minus.bind("<Button-1>", lambda e: self.change_level(-1))

        self.scale = tk.Scale(
            slider_area, from_=0, to=100, orient="horizontal",
            variable=self.vocab_var, showvalue=0, bg=self.COLORS["bg"],
            troughcolor=self.COLORS["bg_secondary"],
            activebackground=self.COLORS["text_accent"],
            bd=0, highlightthickness=0, length=150
        )
        self.scale.pack(side="left", padx=2, fill="x", expand=True)

        btn_plus = tk.Label(
            slider_area, text=">", font=("Consolas", 12, "bold"),
            bg=self.COLORS["bg"], fg=self.COLORS["text_accent"], cursor="hand2"
        )
        btn_plus.pack(side="left", padx=2)
        btn_plus.bind("<Button-1>", lambda e: self.change_level(1))

        self.lbl_lvl_val = tk.Label(
            slider_area, text=str(self.vocab_var.get()),
            font=("Segoe UI", 9, "bold"), bg=self.COLORS["bg"],
            fg=self.COLORS["text_header"]
        )
        self.lbl_lvl_val.pack(side="left", padx=(5, 0))
        self.scale.config(command=lambda v: self.lbl_lvl_val.config(text=v))

        # Статус бар и Grip
        status_bar = tk.Frame(self.bottom_frame, bg=self.COLORS["bg"])
        status_bar.pack(side="bottom", fill="x", pady=2)

        self.grip = ResizeGrip(status_bar, self.resize_window, self.save_size,
                               self.COLORS["bg"], self.COLORS["resize_grip"])
        self.grip.pack(side="right", anchor="se")

        self.lbl_status = tk.Label(
            status_bar, text="Waiting...", font=("Segoe UI", 7),
            bg=self.COLORS["bg"], fg=self.COLORS["text_faint"]
        )
        self.lbl_status.pack(side="right", padx=5)

    def _bind_events(self):
        self.bind("<Button-1>", self.start_move)
        self.bind("<B1-Motion>", self.do_move)
        self.bind("<ButtonRelease-1>", self.stop_move)

        self.scale.bind("<ButtonPress-1>", self.show_popup)
        self.scale.bind("<B1-Motion>", self.move_popup)
        self.scale.bind("<ButtonRelease-1>", self.hide_popup_and_save)

    def _on_mousewheel(self, event):
        self.canvas_scroll.yview_scroll(int(-1 * (event.delta / 120)), "units")

    # ------------- AUTO SCROLLBAR LOGIC -------------
    def _on_frame_configure(self, event):
        """Вызывается когда меняется размер содержимого"""
        self.canvas_scroll.configure(scrollregion=self.canvas_scroll.bbox("all"))
        self._check_scroll_needed()

    def _on_canvas_configure(self, event):
        """Вызывается когда меняется размер самого окна (канваса)"""
        self._check_scroll_needed()

    def _check_scroll_needed(self):
        """Показывает скроллбар только если контент больше окна"""
        bbox = self.canvas_scroll.bbox("all")
        if not bbox: return

        content_height = bbox[3]
        canvas_height = self.canvas_scroll.winfo_height()

        if content_height > canvas_height:
            self.scrollbar.pack(side="right", fill="y")
        else:
            self.scrollbar.pack_forget()

    # ------------- RESIZE LOGIC -------------
    def resize_window(self, dx, dy):
        new_w = self.winfo_width() + dx
        new_h = self.winfo_height() + dy
        if new_w < 300: new_w = 300
        if new_h < 400: new_h = 400
        self.geometry(f"{new_w}x{new_h}")

        # Обновляем ширину текста
        self.lbl_rus.config(wraplength=new_w - 20)
        self.scrollable_frame.event_generate("<Configure>")

    def save_size(self):
        cfg.set("USER", "WindowWidth", self.winfo_width())
        cfg.set("USER", "WindowHeight", self.winfo_height())

    # ------------- АУДИО -------------
    def play_audio(self, index: int):
        if index < len(self.current_audio_urls):
            url = self.current_audio_urls[index]
            if not url: return
            threading.Thread(target=self._play_audio_worker, args=(url,), daemon=True).start()

    def _play_audio_worker(self, url: str):
        try:
            audio_dir = os.path.join("Data", "Audio")
            os.makedirs(audio_dir, exist_ok=True)
            filename = url.split("/")[-1] or f"audio_{abs(hash(url))}.mp3"
            if not filename.endswith(".mp3"): filename += ".mp3"
            file_path = os.path.join(audio_dir, filename)
            if not os.path.exists(file_path):
                resp = requests.get(url, timeout=10)
                if resp.status_code == 200:
                    with open(file_path, "wb") as f:
                        f.write(resp.content)
                else:
                    return
            playsound(file_path)
        except Exception as e:
            print(f"Audio Play Error: {e}")

    # ------------- ОБНОВЛЕНИЕ UI -------------
    def refresh_status(self):
        self.lbl_status.config(text=f"Tr: {self.sources['trans']} • Img: {self.sources['img']}")

    def update_trans_ui(self, data, source: str):
        if data:
            self.lbl_rus.config(text=data["rus"])
            self.sources["trans"] = source
        else:
            self.sources["trans"] = "-"
        self.refresh_status()

    def update_img_ui(self, path, source: str):
        if path:
            try:
                pil_img = Image.open(path)
                window_width = self.winfo_width()
                base_width = window_width - 40

                w_percent = base_width / float(pil_img.size[0])
                h_size = int(float(pil_img.size[1]) * float(w_percent))

                if h_size > 250:
                    h_size = 250
                    w_percent = h_size / float(pil_img.size[1])
                    base_width = int(float(pil_img.size[0]) * float(w_percent))

                try:
                    resample = Image.Resampling.LANCZOS
                except AttributeError:
                    resample = Image.ANTIALIAS

                pil_img = pil_img.resize((base_width, h_size), resample)
                tki = ImageTk.PhotoImage(pil_img)

                self.img_container.config(image=tki, width=base_width, height=h_size, bg=self.COLORS["bg"])
                self.img_container.image = tki
                self.sources["img"] = source
            except Exception as e:
                print(f"Img Error: {e}")
                self.img_container.config(image="")
                self.sources["img"] = "Err"
        else:
            self.img_container.config(image="")
            self.sources["img"] = "No"
        self.refresh_status()

    def update_full_data_ui(self, full_data):
        for widget in self.scrollable_frame.winfo_children(): widget.destroy()
        self.current_audio_urls = []

        if not full_data:
            tk.Label(
                self.scrollable_frame, text="No detailed data available",
                font=self.FONTS["definition"], bg=self.COLORS["bg"], fg=self.COLORS["text_faint"]
            ).pack(pady=10)
            self.lbl_phonetic.config(text="")
            return

        phonetics = full_data.get("phonetics", [])
        if phonetics:
            p_text = next((p["text"] for p in phonetics if p.get("text")), "")
            self.lbl_phonetic.config(text=p_text)
            for p in phonetics:
                if p.get("audio"): self.current_audio_urls.append(p["audio"])
        else:
            self.lbl_phonetic.config(text="")

        # БЛОК AUTO-PRONOUNCE УДАЛЕН ОТСЮДА (ПЕРЕНЕСЕН В MAIN.PYW)

        # --- ВЫВОД ЗНАЧЕНИЙ ---
        meanings = full_data.get("meanings", [])
        window_width = self.winfo_width() - 60

        for meaning in meanings:
            pos = meaning.get("partOfSpeech", "")
            definitions = meaning.get("definitions", [])
            synonyms = meaning.get("synonyms", [])

            pos_label = tk.Label(
                self.scrollable_frame, text=pos, font=self.FONTS["pos"],
                bg=self.COLORS["bg"], fg=self.COLORS["text_pos"], anchor="w"
            )
            pos_label.pack(fill="x", pady=(10, 5))

            for i, defn in enumerate(definitions, 1):
                def_text = f"{i}. {defn.get('definition', '')}"
                tk.Label(
                    self.scrollable_frame, text=def_text, font=self.FONTS["definition"],
                    bg=self.COLORS["bg"], fg=self.COLORS["text_main"],
                    wraplength=window_width, justify="left", anchor="w"
                ).pack(fill="x", padx=10, pady=2)

                if defn.get("example"):
                    tk.Label(
                        self.scrollable_frame, text=f'   "{defn["example"]}"',
                        font=self.FONTS["example"], bg=self.COLORS["bg"],
                        fg=self.COLORS["text_accent"], wraplength=window_width,
                        justify="left", anchor="w"
                    ).pack(fill="x", padx=10, pady=(0, 5))

            if synonyms:
                tk.Label(
                    self.scrollable_frame, text="Syn: " + ", ".join(synonyms),
                    font=self.FONTS["synonym"], bg=self.COLORS["bg"],
                    fg=self.COLORS["text_synonym"], wraplength=window_width,
                    justify="left", anchor="w"
                ).pack(fill="x", padx=10, pady=(5, 5))

            tk.Frame(self.scrollable_frame, height=1, bg=self.COLORS["separator"], width=360).pack(pady=5)

    def reset_ui(self, word: str):
        self.lbl_word.config(text=word)
        self.lbl_phonetic.config(text="")
        self.lbl_rus.config(text="Loading...")
        self.img_container.config(image="")
        self.current_audio_urls = []
        for widget in self.scrollable_frame.winfo_children(): widget.destroy()
        self.sources = {"trans": "...", "img": "..."}
        self.refresh_status()

    # ------------- Change Level / Popup -------------
    def change_level(self, delta: int):
        new_val = self.vocab_var.get() + delta
        if 0 <= new_val <= 100:
            self.vocab_var.set(new_val)
            self.lbl_lvl_val.config(text=str(new_val))
            self.save_level()

    def show_popup(self, event):
        self.dragging_allowed = False
        if not self.popup:
            self.popup = VocabPopup(self)
            x = self.winfo_x() + self.winfo_width() + 10
            y = self.winfo_y()
            self.popup.geometry(f"220x550+{x}+{y}")
        self.update_popup_content()

    def move_popup(self, event):
        self.lbl_lvl_val.config(text=str(self.vocab_var.get()))
        self.update_popup_content()

    def update_popup_content(self):
        if self.popup: self.popup.update_words(self.vocab_var.get())

    def hide_popup_and_save(self, event):
        if self.popup:
            self.popup.destroy();
            self.popup = None
        self.save_level()
        self.dragging_allowed = False

    def save_level(self, event=None):
        cfg.set("USER", "VocabLevel", self.vocab_var.get())

    # ------------- Settings -------------
    def open_settings(self):
        keyboard.unhook_all()
        top = tk.Toplevel(self)
        top.title("Settings");
        top.geometry("350x400")
        top.configure(bg=self.COLORS["bg"]);
        top.attributes("-topmost", True)

        tk.Label(top, text="Settings", font=("Segoe UI", 14, "bold"), bg=self.COLORS["bg"],
                 fg=self.COLORS["text_header"]).pack(pady=10)

        # Keys
        tk.Label(top, text="Yandex Dictionary Key:", bg=self.COLORS["bg"], fg=self.COLORS["text_main"]).pack(anchor="w",
                                                                                                             padx=20)
        entry_yandex = tk.Entry(top, width=45, bg=self.COLORS["bg_secondary"], fg=self.COLORS["text_main"], bd=0);
        entry_yandex.pack(padx=20, pady=5, ipady=3);
        entry_yandex.insert(0, cfg.get("API", "YandexKey"))

        tk.Label(top, text="Pexels API Key:", bg=self.COLORS["bg"], fg=self.COLORS["text_main"]).pack(anchor="w",
                                                                                                      padx=20)
        entry_pexels = tk.Entry(top, width=45, bg=self.COLORS["bg_secondary"], fg=self.COLORS["text_main"], bd=0);
        entry_pexels.pack(padx=20, pady=5, ipady=3);
        entry_pexels.insert(0, cfg.get("API", "PexelsKey"))

        # Checkboxes Frame
        chk_frame = tk.Frame(top, bg=self.COLORS["bg"])
        chk_frame.pack(anchor="w", padx=20, pady=15)

        # Show Sentence Window
        show_sent_var = tk.BooleanVar(value=cfg.get_bool("USER", "ShowSentenceWindow"))
        chk_sent = tk.Checkbutton(chk_frame, text="Show Sentence Window", variable=show_sent_var, onvalue=True,
                                  offvalue=False, bg=self.COLORS["bg"], fg=self.COLORS["text_main"],
                                  selectcolor=self.COLORS["bg_secondary"], activebackground=self.COLORS["bg"])
        chk_sent.pack(anchor="w", pady=2)

        # Auto Pronounce
        try:
            val_pronounce = cfg.get_bool("USER", "AutoPronounce")
        except:
            val_pronounce = False

        auto_pronounce_var = tk.BooleanVar(value=val_pronounce)
        chk_pronounce = tk.Checkbutton(chk_frame, text="Auto-pronounce (US)", variable=auto_pronounce_var, onvalue=True,
                                       offvalue=False, bg=self.COLORS["bg"], fg=self.COLORS["text_main"],
                                       selectcolor=self.COLORS["bg_secondary"], activebackground=self.COLORS["bg"])
        chk_pronounce.pack(anchor="w", pady=2)

        def save_and_close():
            cfg.set("API", "YandexKey", entry_yandex.get().strip())
            cfg.set("API", "PexelsKey", entry_pexels.get().strip())

            # Save Sent Window state
            new_sent_state = show_sent_var.get()
            cfg.set("USER", "ShowSentenceWindow", new_sent_state)
            if new_sent_state:
                self.sent_window.show()
            else:
                self.sent_window.hide()

            # Save Auto Pronounce state
            cfg.set("USER", "AutoPronounce", auto_pronounce_var.get())

            top.destroy()
            if hasattr(self, "hook_func"): keyboard.hook(self.hook_func)

        def on_close():
            top.destroy()
            if hasattr(self, "hook_func"): keyboard.hook(self.hook_func)

        tk.Button(top, text="Save", command=save_and_close, bg=self.COLORS["text_accent"], fg="white",
                  font=("Segoe UI", 10, "bold"), bd=0, padx=20, pady=5, cursor="hand2").pack(pady=10)
        top.protocol("WM_DELETE_WINDOW", on_close)

    # ------------- Window Move -------------
    def start_move(self, event):
        widget = event.widget
        if isinstance(widget, (tk.Button, tk.Scale, tk.Scrollbar, tk.Entry)):
            self.dragging_allowed = False;
            return
        if widget == self.grip:
            self.dragging_allowed = False;
            return
        try:
            if widget.cget("cursor") == "hand2":
                self.dragging_allowed = False;
                return
        except:
            pass
        self.dragging_allowed = True;
        self.x = event.x;
        self.y = event.y

    def do_move(self, event):
        if not self.dragging_allowed: return
        new_x = self.winfo_x() + (event.x - self.x);
        new_y = self.winfo_y() + (event.y - self.y)
        self.geometry(f"+{new_x}+{new_y}")

    def stop_move(self, event):
        if self.dragging_allowed:
            cfg.set("USER", "WindowX", self.winfo_x());
            cfg.set("USER", "WindowY", self.winfo_y())
        self.dragging_allowed = False

    def close_app(self):
        keyboard.unhook_all();
        self.destroy();
        sys.exit(0)
