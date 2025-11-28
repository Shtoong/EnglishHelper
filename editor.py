class TextEditorSimulator:
    def __init__(self):
        self.chars = []
        self.cursor = 0

    def insert(self, text):
        for char in text:
            self.chars.insert(self.cursor, char)
            self.cursor += 1

    def backspace(self):
        if self.cursor > 0:
            self.chars.pop(self.cursor - 1)
            self.cursor -= 1

    def delete(self):
        if self.cursor < len(self.chars):
            self.chars.pop(self.cursor)

    def move_left(self):
        if self.cursor > 0: self.cursor -= 1

    def move_right(self):
        if self.cursor < len(self.chars): self.cursor += 1
        
    def clear(self):
        self.chars = []
        self.cursor = 0

    def get_text(self):
        return "".join(self.chars)
    
    def get_text_with_cursor(self):
        temp = self.chars.copy()
        temp.insert(self.cursor, "|")
        return "".join(temp)
