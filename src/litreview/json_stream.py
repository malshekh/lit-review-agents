"""Bounded-buffer JSON loading with standard-library scalar semantics.

Containers are assembled iteratively. Only the current scalar and a small input
buffer are decoded as text; no whole-document read/join is necessary. The result
still occupies its natural Python object memory, and one large scalar can require
a correspondingly large buffer.
"""
import json
import re


class _Reader:
    def __init__(self, stream, chunk_size):
        if chunk_size < 1:
            raise ValueError('chunk_size must be positive')
        self.stream, self.chunk_size = stream, chunk_size
        self.buffer, self.pos, self.eof = '', 0, False
        self.decoder = json.JSONDecoder()

    def fill(self):
        self.buffer = self.buffer[self.pos:]
        self.pos = 0
        text = self.stream.read(self.chunk_size)
        if not text:
            self.eof = True
        self.buffer += text

    def error(self, message):
        raise json.JSONDecodeError(message, self.buffer, self.pos)

    def token(self):
        while True:
            while self.pos < len(self.buffer) and self.buffer[self.pos] in ' \t\r\n':
                self.pos += 1
            if self.pos < len(self.buffer):
                break
            if self.eof:
                return 'EOF', None
            self.fill()
        char = self.buffer[self.pos]
        if char in '{}[]:,':
            self.pos += 1
            return char, None
        if char == '"':
            while True:
                try:
                    value, end = self.decoder.raw_decode(self.buffer, self.pos)
                except json.JSONDecodeError as exc:
                    incomplete = (exc.msg.startswith('Unterminated string')
                                  or (exc.msg.startswith('Invalid \\uXXXX escape')
                                      and len(self.buffer) - exc.pos <= 5))
                    if self.eof or not incomplete:
                        raise
                    self.fill()
                    continue
                self.pos = end
                return 'STRING', value
        # Wait for a delimiter or EOF: raw_decode alone would accept the prefix
        # 1 of a number split across chunks as 1 / 23, or 1 / e-9.
        while True:
            match = re.search(r'[ \t\r\n,\]}]', self.buffer[self.pos:])
            if match is not None or self.eof:
                end = self.pos + match.start() if match else len(self.buffer)
                text = self.buffer[self.pos:end]
                value, consumed = self.decoder.raw_decode(text)
                if consumed != len(text):
                    self.error('Invalid JSON scalar')
                self.pos = end
                return 'VALUE', value
            self.fill()


def load(stream, *, chunk_size=65536):
    """Load one JSON document without retaining its complete serialized text.

    String escapes, arbitrary-size integers, floats, NaN/Infinity and duplicate
    object-key behavior use json.JSONDecoder, matching existing artifact values.
    Syntax failures remain JSONDecodeError; no resource exception is suppressed.
    """
    reader = _Reader(stream, chunk_size)
    stack = []
    missing = object()
    result = missing

    def accept(kind, value):
        nonlocal result
        if kind == '{':
            value = {}
        elif kind == '[':
            value = []
        elif kind not in ('STRING', 'VALUE'):
            reader.error('Expecting value')
        if not stack:
            result = value
        else:
            frame = stack[-1]
            if frame[0] == '{':
                frame[1][frame[3]] = value
            else:
                frame[1].append(value)
            frame[2] = 'comma'
        if kind in ('{', '['):
            stack.append([kind, value, 'first', None])

    while result is missing or stack:
        kind, value = reader.token()
        if not stack:
            accept(kind, value)
            continue
        frame = stack[-1]
        container, _, state, _ = frame
        close = '}' if container == '{' else ']'
        if state == 'comma':
            if kind == close:
                stack.pop()
            elif kind == ',':
                frame[2] = 'required'
            else:
                reader.error('Expecting comma or closing delimiter')
        elif state == 'colon':
            if kind != ':':
                reader.error('Expecting colon')
            frame[2] = 'value'
        elif container == '{' and state in ('first', 'required'):
            if kind == '}' and state == 'first':
                stack.pop()
            elif kind == 'STRING':
                frame[3], frame[2] = value, 'colon'
            else:
                reader.error('Expecting property name enclosed in double quotes')
        elif container == '[' and kind == ']' and state == 'first':
            stack.pop()
        else:
            accept(kind, value)
    if reader.token()[0] != 'EOF':
        reader.error('Extra data')
    return result
