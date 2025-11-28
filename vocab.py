import os
import requests
from config import VOCAB_FILE
from lemminflect import getLemma

WORD_RANKS = {}
SORTED_WORDS = []

def init_vocab():
    global WORD_RANKS, SORTED_WORDS
    url = "https://raw.githubusercontent.com/first20hours/google-10000-english/master/google-10000-english.txt"
    
    if os.path.exists(VOCAB_FILE):
        if os.path.getsize(VOCAB_FILE) < 100:
            try: os.remove(VOCAB_FILE)
            except: pass

    if not os.path.exists(VOCAB_FILE):
        try:
            resp = requests.get(url, timeout=15, verify=False)
            if resp.status_code == 200:
                with open(VOCAB_FILE, 'w', encoding='utf-8') as f: f.write(resp.text)
            else:
                with open(VOCAB_FILE, 'w') as f: f.write("the\nof\nand")
        except:
            if not os.path.exists(VOCAB_FILE):
                with open(VOCAB_FILE, 'w') as f: f.write("the\nof\nand")

    try:
        with open(VOCAB_FILE, 'r', encoding='utf-8') as f:
            words = f.read().splitlines()
            SORTED_WORDS = [w.strip().lower() for w in words]
            WORD_RANKS = {w: i for i, w in enumerate(SORTED_WORDS)}
    except: pass

def get_lemma_safe(word):
    word_lower = word.lower()

    # --- ИСПРАВЛЕНИЕ ---
    # Если слово очень популярное (входит в топ-1000), мы его НЕ трогаем.
    # Это предотвращает превращение "this" -> "thi", "bus" -> "bu" и т.д.
    if word_lower in WORD_RANKS and WORD_RANKS[word_lower] < 1000:
        return word_lower
    # -------------------

    try:
        if len(word) < 2: return word
        
        # Сначала пробуем найти глагол (works -> work)
        lemma_verb = getLemma(word, upos='VERB')
        if lemma_verb and lemma_verb[0] != word: return lemma_verb[0]
        
        # Потом существительное (cats -> cat)
        lemma_noun = getLemma(word, upos='NOUN')
        return lemma_noun[0] if lemma_noun else word
    except: return word

def is_word_too_simple(word, current_level):
    """Возвращает (True/False, Lemma) в зависимости от сложности"""
    lem = get_lemma_safe(word).lower()
    rank = WORD_RANKS.get(lem, 99999)
    cut_off = current_level * 100
    return rank < cut_off, lem
