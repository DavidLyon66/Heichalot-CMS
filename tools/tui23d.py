"""
tui.py
======

Low-resolution terminal visual language for Heichalot tools.

This module gathers ordinary ASCII / Unicode characters and ANSI / VT100
control sequences in one readable place so a human or AI can quickly express
visual ideas in a terminal-like display.

The screen API at the bottom is backend-driven.  It defaults to an ANSI
terminal, but can be redirected to a browser/Three.js bridge without changing
application code.

Coordinate convention
---------------------
ANSI cursor positions are 1-based:

    row 1, column 1 == top-left cell

Newlines
--------
LF      "\\n"      Line Feed. Advance vertically one line. Do not assume it
                  also returns to column 1 in every terminal implementation.

CR      "\\r"      Carriage Return. Return to column 1 of the current line.

CRLF    "\\r\\n"   Carriage Return + Line Feed. Explicitly start at column 1
                  of the next line.

ANSI / VT100 basics
-------------------
ESC     0x1B       Escape character.
CSI     ESC + "["  Control Sequence Introducer.

Examples:

    ESC [ 2 J          erase entire display
    ESC [ H            cursor home
    ESC [ 10 ; 20 H    cursor to row 10, column 20
    ESC [ 31 m         red foreground
    ESC [ 0 m          reset attributes

Typical clear-and-home sequence:

    CLEAR_SCREEN + CURSOR_HOME
"""

# ---------------------------------------------------------------------------
# Control characters
# ---------------------------------------------------------------------------

NUL = "\x00"
BEL = "\x07"
BS = "\x08"
TAB = "\x09"
LF = "\x0a"          # \n  Line Feed
VT = "\x0b"
FF = "\x0c"
CR = "\x0d"          # \r  Carriage Return
ESC = "\x1b"
DEL = "\x7f"

NEWLINE = LF
CRLF = CR + LF

CSI = ESC + "["
OSC = ESC + "]"

# ---------------------------------------------------------------------------
# Cursor movement
# ---------------------------------------------------------------------------

CURSOR_HOME = CSI + "H"

CURSOR_UP = CSI + "A"
CURSOR_DOWN = CSI + "B"
CURSOR_FORWARD = CSI + "C"
CURSOR_BACK = CSI + "D"

SAVE_CURSOR = ESC + "7"
RESTORE_CURSOR = ESC + "8"


def cursor(row: int, column: int) -> str:
    """Move cursor to a 1-based row and column."""
    return f"{CSI}{int(row)};{int(column)}H"


def cursor_up(count: int = 1) -> str:
    return f"{CSI}{int(count)}A"


def cursor_down(count: int = 1) -> str:
    return f"{CSI}{int(count)}B"


def cursor_forward(count: int = 1) -> str:
    return f"{CSI}{int(count)}C"


def cursor_back(count: int = 1) -> str:
    return f"{CSI}{int(count)}D"


def cursor_column(column: int = 1) -> str:
    """Move cursor to an absolute 1-based column on the current row."""
    return f"{CSI}{int(column)}G"

# ---------------------------------------------------------------------------
# Erasing
# ---------------------------------------------------------------------------

ERASE_TO_END_OF_SCREEN = CSI + "0J"
ERASE_TO_START_OF_SCREEN = CSI + "1J"
CLEAR_SCREEN = CSI + "2J"

ERASE_TO_END_OF_LINE = CSI + "0K"
ERASE_TO_START_OF_LINE = CSI + "1K"
CLEAR_LINE = CSI + "2K"

CLEAR_AND_HOME = CLEAR_SCREEN + CURSOR_HOME

# ---------------------------------------------------------------------------
# Text attributes / SGR
# ---------------------------------------------------------------------------

RESET = CSI + "0m"

BOLD = CSI + "1m"
DIM = CSI + "2m"
ITALIC = CSI + "3m"
UNDERLINE = CSI + "4m"
BLINK = CSI + "5m"
REVERSE = CSI + "7m"
HIDDEN = CSI + "8m"
STRIKE = CSI + "9m"

BOLD_OFF = CSI + "22m"
ITALIC_OFF = CSI + "23m"
UNDERLINE_OFF = CSI + "24m"
BLINK_OFF = CSI + "25m"
REVERSE_OFF = CSI + "27m"

FG_DEFAULT = CSI + "39m"
BG_DEFAULT = CSI + "49m"

FG_BLACK = CSI + "30m"
FG_RED = CSI + "31m"
FG_GREEN = CSI + "32m"
FG_YELLOW = CSI + "33m"
FG_BLUE = CSI + "34m"
FG_MAGENTA = CSI + "35m"
FG_CYAN = CSI + "36m"
FG_WHITE = CSI + "37m"

FG_BRIGHT_BLACK = CSI + "90m"
FG_BRIGHT_RED = CSI + "91m"
FG_BRIGHT_GREEN = CSI + "92m"
FG_BRIGHT_YELLOW = CSI + "93m"
FG_BRIGHT_BLUE = CSI + "94m"
FG_BRIGHT_MAGENTA = CSI + "95m"
FG_BRIGHT_CYAN = CSI + "96m"
FG_BRIGHT_WHITE = CSI + "97m"

BG_BLACK = CSI + "40m"
BG_RED = CSI + "41m"
BG_GREEN = CSI + "42m"
BG_YELLOW = CSI + "43m"
BG_BLUE = CSI + "44m"
BG_MAGENTA = CSI + "45m"
BG_CYAN = CSI + "46m"
BG_WHITE = CSI + "47m"

BG_BRIGHT_BLACK = CSI + "100m"
BG_BRIGHT_RED = CSI + "101m"
BG_BRIGHT_GREEN = CSI + "102m"
BG_BRIGHT_YELLOW = CSI + "103m"
BG_BRIGHT_BLUE = CSI + "104m"
BG_BRIGHT_MAGENTA = CSI + "105m"
BG_BRIGHT_CYAN = CSI + "106m"
BG_BRIGHT_WHITE = CSI + "107m"


def fg256(index: int) -> str:
    """ANSI 256-colour foreground, index 0..255."""
    return f"{CSI}38;5;{int(index)}m"


def bg256(index: int) -> str:
    """ANSI 256-colour background, index 0..255."""
    return f"{CSI}48;5;{int(index)}m"


def fg_rgb(r: int, g: int, b: int) -> str:
    """24-bit foreground colour."""
    return f"{CSI}38;2;{int(r)};{int(g)};{int(b)}m"


def bg_rgb(r: int, g: int, b: int) -> str:
    """24-bit background colour."""
    return f"{CSI}48;2;{int(r)};{int(g)};{int(b)}m"

# ---------------------------------------------------------------------------
# Box drawing: Unicode U+2500..U+257F
# ---------------------------------------------------------------------------

BOX = {
    "h": "─", "v": "│",
    "tl": "┌", "tr": "┐", "bl": "└", "br": "┘",
    "tee_left": "├", "tee_right": "┤", "tee_down": "┬", "tee_up": "┴", "cross": "┼",
    "round_tl": "╭", "round_tr": "╮", "round_bl": "╰", "round_br": "╯",
    "heavy_h": "━", "heavy_v": "┃",
    "heavy_tl": "┏", "heavy_tr": "┓", "heavy_bl": "┗", "heavy_br": "┛",
    "heavy_tee_left": "┣", "heavy_tee_right": "┫", "heavy_tee_down": "┳", "heavy_tee_up": "┻", "heavy_cross": "╋",
    "double_h": "═", "double_v": "║",
    "double_tl": "╔", "double_tr": "╗", "double_bl": "╚", "double_br": "╝", "double_cross": "╬",
}

# ---------------------------------------------------------------------------
# Block elements: Unicode U+2580..U+259F
# ---------------------------------------------------------------------------

BLOCK = {
    "full": "█",
    "upper_half": "▀",
    "lower_half": "▄",
    "left_half": "▌",
    "right_half": "▐",
    "shade_light": "░",
    "shade_medium": "▒",
    "shade_dark": "▓",
}

SPARKLINE = "▁▂▃▄▅▆▇█"
HORIZONTAL_FILL = "▏▎▍▌▋▊▉█"

# ---------------------------------------------------------------------------
# Geometric symbols and arrows
# ---------------------------------------------------------------------------

SYMBOL = {
    "square": "■", "square_open": "□", "small_square": "▪", "small_square_open": "▫",
    "circle": "●", "circle_open": "○", "bullseye": "◉",
    "diamond": "◆", "diamond_open": "◇",
    "triangle_up": "▲", "triangle_up_open": "△",
    "triangle_down": "▼", "triangle_down_open": "▽",
}

ARROW = {
    "left": "←", "up": "↑", "right": "→", "down": "↓",
    "left_right": "↔", "up_down": "↕",
    "up_left": "↖", "up_right": "↗", "down_right": "↘", "down_left": "↙",
}

# ---------------------------------------------------------------------------
# Braille graphics: Unicode U+2800..U+28FF
#
# One Braille cell is a 2 x 4 dot matrix:
#
#     1 4
#     2 5
#     3 6
#     7 8
#
# That gives eight low-resolution graphic pixels per text cell.
# ---------------------------------------------------------------------------

BRAILLE_BLANK = "\u2800"
BRAILLE_FULL = "\u28ff"

_BRAILLE_BITS = {
    (0, 0): 0, (0, 1): 1, (0, 2): 2,
    (1, 0): 3, (1, 1): 4, (1, 2): 5,
    (0, 3): 6, (1, 3): 7,
}


def braille(points) -> str:
    """Return one Braille character from an iterable of (x, y) points."""
    bits = 0
    for x, y in points:
        bits |= 1 << _BRAILLE_BITS[(int(x), int(y))]
    return chr(0x2800 + bits)

# ---------------------------------------------------------------------------
# Small helpers for AI / application output
# ---------------------------------------------------------------------------


def styled(text: str, *codes: str) -> str:
    """Wrap text in ANSI codes and reset attributes afterwards."""
    return "".join(codes) + str(text) + RESET


def box(width: int, height: int, rounded: bool = False) -> str:
    """Return a simple empty Unicode box as plain text."""
    width = max(2, int(width))
    height = max(2, int(height))

    if rounded:
        tl, tr, bl, br = "╭", "╮", "╰", "╯"
    else:
        tl, tr, bl, br = "┌", "┐", "└", "┘"

    top = tl + ("─" * (width - 2)) + tr
    middle = "│" + (" " * (width - 2)) + "│"
    bottom = bl + ("─" * (width - 2)) + br
    return LF.join([top] + [middle] * (height - 2) + [bottom])


def sparkline(values) -> str:
    """Convert numeric values into an eight-level Unicode sparkline."""
    values = list(values)
    if not values:
        return ""

    lo = min(values)
    hi = max(values)
    if hi == lo:
        return SPARKLINE[0] * len(values)

    chars = []
    for value in values:
        level = round((float(value) - lo) / (hi - lo) * 7)
        chars.append(SPARKLINE[max(0, min(7, level))])
    return "".join(chars)

# ---------------------------------------------------------------------------
# Screen / input-output interface
#
# Coordinates and mouse positions are CHARACTER CELLS, not pixels.
# Public coordinates are zero-based.  The terminal backend converts them to
# ANSI's one-based row/column coordinates at its boundary.
# ---------------------------------------------------------------------------

from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass
import os
import re
import select
import sys
from typing import Callable, Optional


@dataclass(frozen=True)
class MouseEvent:
    """A mouse event in character cells rather than pixels."""

    x: int
    y: int
    button: int = 0
    pressed: bool = True
    kind: str = "button"       # button, move, wheel
    wheel: int = 0              # -1 down, +1 up
    modifiers: tuple = ()       # shift, alt, ctrl


class ScreenBackend(ABC):
    """Boundary implemented by a terminal, Three.js bridge, or test double."""

    @abstractmethod
    def open(self, width: int, height: int, depth: int = 1): pass

    @abstractmethod
    def close(self): pass

    @abstractmethod
    def write(self, text: str): pass

    @abstractmethod
    def writeln(self, text: str = "", z: Optional[int] = None): pass

    @abstractmethod
    def position(self, x: int, y: int, z: int = 0): pass

    @abstractmethod
    def set_z(self, z: int): pass

    @abstractmethod
    def read_key(self): pass

    @abstractmethod
    def key_pressed(self) -> bool: pass

    @abstractmethod
    def read_mouse(self) -> MouseEvent: pass

    @abstractmethod
    def mouse_position(self): pass

    @abstractmethod
    def mouse_pressed(self) -> bool: pass

    def set_palette(self, colours):
        pass

    def colour(self, index: int):
        pass

    def background_colour(self, index: int):
        pass


class TerminalBackend(ScreenBackend):
    """ANSI/VT terminal backend for Linux, macOS, and other POSIX terminals.

    A terminal has no real z axis.  ``z`` is retained as state so the same
    program can later use a 3D backend, but all layers are drawn on the one
    visible terminal plane.
    """

    _MOUSE_RE = re.compile(rb"^\x1b\[<(\d+);(\d+);(\d+)([Mm])")
    _KEYS = {
        b"\x1b[A": "UP", b"\x1b[B": "DOWN", b"\x1b[C": "RIGHT",
        b"\x1b[D": "LEFT", b"\x1b[H": "HOME", b"\x1b[F": "END",
        b"\x1b[2~": "INSERT", b"\x1b[3~": "DELETE",
        b"\x1b[5~": "PAGE_UP", b"\x1b[6~": "PAGE_DOWN",
        b"\r": "ENTER", b"\n": "ENTER", b"\t": "TAB",
        b"\x7f": "BACKSPACE", b"\x1b": "ESCAPE",
    }

    def __init__(self, input_stream=None, output_stream=None,
                 alternate_screen: bool = True, enable_mouse: bool = True):
        self.input = input_stream or sys.stdin
        self.output = output_stream or sys.stdout
        self.alternate_screen = alternate_screen
        self.enable_mouse = enable_mouse
        self.width = self.height = self.depth = 0
        self.x = self.y = self.z = 0
        self._old_termios = None
        self._buffer = bytearray()
        self._keys = deque()
        self._mouse = deque()
        self._mouse_position = (0, 0)
        self._button_down = False

    def _emit(self, value):
        self.output.write(value)
        self.output.flush()

    def open(self, width: int, height: int, depth: int = 1):
        self.width, self.height, self.depth = _dimensions(width, height, depth)
        if getattr(self.input, "isatty", lambda: False)():
            import termios
            import tty
            fd = self.input.fileno()
            self._old_termios = termios.tcgetattr(fd)
            tty.setraw(fd)
        sequence = ""
        if self.alternate_screen:
            sequence += CSI + "?1049h"
        sequence += CSI + "?25l" + CLEAR_AND_HOME
        if self.enable_mouse:
            sequence += CSI + "?1000h" + CSI + "?1003h" + CSI + "?1006h"
        self._emit(sequence)
        return self

    def close(self):
        sequence = RESET
        if self.enable_mouse:
            sequence += CSI + "?1006l" + CSI + "?1003l" + CSI + "?1000l"
        sequence += CSI + "?25h"
        if self.alternate_screen:
            sequence += CSI + "?1049l"
        self._emit(sequence)
        if self._old_termios is not None:
            import termios
            termios.tcsetattr(self.input.fileno(), termios.TCSADRAIN,
                              self._old_termios)
            self._old_termios = None

    def write(self, text: str):
        value = str(text)
        self._emit(value)
        self.x += len(_strip_ansi(value))

    def writeln(self, text: str = "", z: Optional[int] = None):
        if z is not None:
            self.set_z(z)
        self.write(text)
        self._emit(CRLF)
        self.x, self.y = 0, self.y + 1

    def position(self, x: int, y: int, z: int = 0):
        self.x, self.y, self.z = _coordinates(x, y, z)
        self._emit(cursor(self.y + 1, self.x + 1))

    def set_z(self, z: int):
        self.z = _non_negative("z", z)

    def _read_available(self, block: bool):
        if not getattr(self.input, "isatty", lambda: False)():
            return False
        ready, _, _ = select.select([self.input], [], [], None if block else 0)
        if not ready:
            return False
        self._buffer.extend(os.read(self.input.fileno(), 64))
        self._parse_buffer()
        return True

    def _parse_buffer(self):
        while self._buffer:
            match = self._MOUSE_RE.match(self._buffer)
            if match:
                code, x, y, final = match.groups()
                del self._buffer[:match.end()]
                self._queue_mouse(int(code), int(x) - 1, int(y) - 1,
                                  final == b"M")
                continue
            matched = next(((raw, name) for raw, name in self._KEYS.items()
                            if self._buffer.startswith(raw) and
                            (raw != b"\x1b" or len(self._buffer) == 1)), None)
            if matched:
                raw, name = matched
                del self._buffer[:len(raw)]
                self._keys.append(name)
                continue
            if self._buffer[0] == 0x1b and len(self._buffer) < 3:
                break
            size = _utf8_size(self._buffer[0])
            if len(self._buffer) < size:
                break
            raw = bytes(self._buffer[:size])
            del self._buffer[:size]
            self._keys.append(raw.decode("utf-8", errors="replace"))

    def _queue_mouse(self, code, x, y, pressed):
        modifiers = tuple(name for bit, name in
                          ((4, "shift"), (8, "alt"), (16, "ctrl")) if code & bit)
        if code & 64:
            event = MouseEvent(x, y, kind="wheel", wheel=1 if not code & 1 else -1,
                               modifiers=modifiers)
        else:
            event = MouseEvent(x, y, button=(code & 3) + 1,
                               pressed=pressed, kind="move" if code & 32 else "button",
                               modifiers=modifiers)
        self._mouse_position = (x, y)
        self._button_down = event.pressed and event.kind == "button"
        self._mouse.append(event)

    def read_key(self):
        while not self._keys:
            self._read_available(True)
        return self._keys.popleft()

    def key_pressed(self) -> bool:
        self._read_available(False)
        return bool(self._keys)

    def read_mouse(self) -> MouseEvent:
        while not self._mouse:
            self._read_available(True)
        return self._mouse.popleft()

    def mouse_position(self):
        self._read_available(False)
        return self._mouse_position

    def mouse_pressed(self) -> bool:
        self._read_available(False)
        return self._button_down or bool(self._mouse)

    def set_palette(self, colours):
        self.palette = list(colours)

    def colour(self, index: int):
        self._emit(_palette_ansi(self.palette, index, False))

    def background_colour(self, index: int):
        self._emit(_palette_ansi(self.palette, index, True))


class WorldBackend(ScreenBackend):
    """JSON-friendly adapter for a Three.js/browser transport.

    ``send`` receives one dictionary per output command.  A WebSocket adapter
    can simply use ``lambda command: socket.send(json.dumps(command))``.
    Browser events are returned through :meth:`feed_key` and
    :meth:`feed_mouse`.
    """

    def __init__(self, send: Callable[[dict], None]):
        self.send = send
        self._keys, self._mouse = deque(), deque()
        self._mouse_position = (0, 0)
        self._button_down = False
        self.x = self.y = self.z = 0

    def _send(self, command, **values):
        self.send({"command": command, **values})

    def open(self, width, height, depth=1):
        self.width, self.height, self.depth = _dimensions(width, height, depth)
        self._send("open", width=self.width, height=self.height, depth=self.depth)
        return self

    def close(self): self._send("close")
    def write(self, text):
        text = str(text)
        self._send("write", text=text, x=self.x, y=self.y, z=self.z)
        self.x += len(_strip_ansi(text))
    def writeln(self, text="", z=None):
        if z is not None: self.set_z(z)
        self._send("writeln", text=str(text), x=self.x, y=self.y, z=self.z)
        self.x, self.y = 0, self.y + 1
    def position(self, x, y, z=0):
        self.x, self.y, self.z = _coordinates(x, y, z)
        self._send("position", x=self.x, y=self.y, z=self.z)
    def set_z(self, z):
        self.z = _non_negative("z", z)
        self._send("set_z", z=self.z)
    def set_palette(self, colours): self._send("palette", colours=list(colours))
    def colour(self, index): self._send("colour", index=int(index))
    def background_colour(self, index): self._send("background_colour", index=int(index))
    def feed_key(self, key): self._keys.append(key)
    def feed_mouse(self, event):
        if isinstance(event, dict): event = MouseEvent(**event)
        self._mouse_position = (event.x, event.y)
        self._button_down = event.pressed and event.kind == "button"
        self._mouse.append(event)
    def read_key(self):
        if not self._keys: raise BlockingIOError("no browser key event is waiting")
        return self._keys.popleft()
    def key_pressed(self): return bool(self._keys)
    def read_mouse(self):
        if not self._mouse: raise BlockingIOError("no browser mouse event is waiting")
        return self._mouse.popleft()
    def mouse_position(self): return self._mouse_position
    def mouse_pressed(self): return self._button_down or bool(self._mouse)


_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _strip_ansi(value):
    return _ANSI_RE.sub("", value)


def _utf8_size(first_byte):
    if first_byte < 0x80: return 1
    if first_byte < 0xE0: return 2
    if first_byte < 0xF0: return 3
    return 4


def _non_negative(name, value):
    value = int(value)
    if value < 0: raise ValueError(f"{name} must be zero or greater")
    return value


def _coordinates(x, y, z):
    return (_non_negative("x", x), _non_negative("y", y),
            _non_negative("z", z))


def _dimensions(width, height, depth):
    values = int(width), int(height), int(depth)
    if any(value < 1 for value in values):
        raise ValueError("screen dimensions must be at least 1")
    return values


def _palette_ansi(palette, index, background):
    value = palette[int(index)].lstrip("#")
    if len(value) != 6: raise ValueError("palette colours must be #RRGGBB")
    r, g, b = (int(value[i:i + 2], 16) for i in (0, 2, 4))
    return bg_rgb(r, g, b) if background else fg_rgb(r, g, b)


_backend: ScreenBackend = TerminalBackend()


def use_backend(backend: ScreenBackend):
    """Install a backend and return it (handy for setup expressions)."""
    global _backend
    _backend = backend
    return backend

def open_screen(width: int, height: int, depth: int = 1):
    """Open a character-cell volume: open_screen(x, y, z)."""
    return _backend.open(width, height, depth)

def write(text):
    """Write at the current cursor position without a newline."""
    return _backend.write(text)

def writeln(text="", z=None):
    """Write at the current or selected z layer, then advance to the next line."""
    return _backend.writeln(text, z)

def set_z(z: int):
    """Select the current z layer/depth for subsequent output."""
    return _backend.set_z(z)


def position(x: int, y: int, z: int = 0):
    """Set the output position in character/voxel coordinates."""
    return _backend.position(x, y, z)


def close_screen():
    """Close the current character screen."""
    return _backend.close()

def read_key():
    """Read one keyboard event/key from the active screen."""
    return _backend.read_key()

def key_pressed():
    """Return whether a keyboard event is waiting, without blocking."""
    return _backend.key_pressed()

def read_mouse():
    """Read one mouse event in character-cell coordinates."""
    return _backend.read_mouse()

def mouse_position():
    """Return mouse position as character-cell coordinates (x, y)."""
    return _backend.mouse_position()

def mouse_pressed():
    """Return whether a mouse button event is waiting/active."""
    return _backend.mouse_pressed()

# ---------------------------------------------------------------------------
# Minimal vocabulary for a simple renderer / AI prompt
# ---------------------------------------------------------------------------

MINIMUM_ANSI = {
    "escape": ESC,
    "csi": CSI,
    "newline": LF,
    "carriage_return": CR,
    "next_line_explicit": CRLF,
    "home": CURSOR_HOME,
    "clear_screen": CLEAR_SCREEN,
    "clear_and_home": CLEAR_AND_HOME,
    "erase_line": CLEAR_LINE,
    "erase_to_end_of_line": ERASE_TO_END_OF_LINE,
    "reset": RESET,
    "bold": BOLD,
    "dim": DIM,
    "reverse": REVERSE,
}

MINIMUM_GRAPHICS = {
    "box": "─│┌┐└┘├┤┬┴┼╭╮╰╯",
    "blocks": "▁▂▃▄▅▆▇█▏▎▍▌▋▊▉░▒▓",
    "symbols": "●○■□▲△▼▽◆◇",
    "arrows": "←↑→↓↔↕↖↗↘↙",
}

# ---------------------------------------------------------------------------
# Indexed colour palette -- PLACEHOLDER ONLY
#
# A palette is an ordered collection of colours, such as a Lospec palette.
# Once loaded, drawing operations refer to colours ONLY by palette index.
#
# Example:
#
#     set_palette([
#         "#1a1c2c",   # 0
#         "#5d275d",   # 1
#         "#b13e53",   # 2
#         "#ef7d57",   # 3
#     ])
#
#     colour(2)
#
# No palette loading/rendering backend is implemented here.
# ---------------------------------------------------------------------------

PALETTE = []


def set_palette(colours):
    """Set the indexed colour palette."""
    global PALETTE
    PALETTE = list(colours)
    return _backend.set_palette(PALETTE)


def colour(index: int):
    """Select a colour by its index in the current palette."""
    return _backend.colour(index)


def background_colour(index: int):
    """Select a background colour by palette index."""
    return _backend.background_colour(index)


# ---------------------------------------------------------------------------
# Animation -- PLACEHOLDER
#
# Animation will eventually describe movement/change using keyframes.
# It does not define timing, interpolation, playback or rendering yet.
# ---------------------------------------------------------------------------

def animate(*keyframes):
    """
    Define an animation as a sequence of keyframes.

    Future conceptual use:

        animate(
            (0,  position_a),
            (10, position_b),
            (20, position_c),
        )

    Exact keyframe representation is deliberately undefined for now.
    """
    raise NotImplementedError("animation is not implemented yet")
if __name__ == "__main__":
    print("tui.py character / ANSI reference")
    print()
    print("Box drawing :", MINIMUM_GRAPHICS["box"])
    print("Blocks      :", MINIMUM_GRAPHICS["blocks"])
    print("Symbols     :", MINIMUM_GRAPHICS["symbols"])
    print("Arrows      :", MINIMUM_GRAPHICS["arrows"])
    print("Sparkline   :", sparkline([1, 2, 4, 7, 5, 9, 3, 2]))
    print("Braille     :", BRAILLE_BLANK, BRAILLE_FULL, braille([(0, 0), (1, 1), (0, 3)]))
