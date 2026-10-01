"""Visual helpers for EqUpdater.

The UI deliberately keeps the update/business logic in :mod:`equpdater.app`.
This module only owns presentation primitives that Tk does not provide well:
font-family switching, cover-cropped background artwork, and subtle gradient
buttons.
"""

from __future__ import annotations

import os
import queue
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass

from . import branding

try:
    from PIL import Image, ImageEnhance, ImageFont, ImageTk
except Exception:  # pragma: no cover - source can still start without Pillow
    Image = ImageEnhance = ImageFont = ImageTk = None


FRIZ_FAMILIES = (
    "Friz Quadrata",
    "FrizQuadrata",
    "Friz Quadrata TT",
    "Friz Quadrata Std",
)
ARIAL_FAMILIES = (
    "Arial",
    "Arial MT",
    "ArialMT",
)
OPEN_DYSLEXIC_FAMILIES = (
    "OpenDyslexic",
    "OpenDyslexic3",
    "Open Dyslexic",
)
FALLBACK_FAMILY = "Georgia"
MONO_FAMILIES = {"consolas", "courier", "courier new", "monospace"}

FONT_CHOICES = {
    "friz": FRIZ_FAMILIES,
    "arial": ARIAL_FAMILIES,
    "opendyslexic": OPEN_DYSLEXIC_FAMILIES,
}

# OpenDyslexic has a much larger visual/em box than Friz at the same Tk point
# size. Keeping it at 1:1 makes fixed-height rows and the Settings panel spill
# beyond the authored 1000x700 layout. This multiplier keeps roughly the same
# occupied footprint while retaining the typeface's letterforms.
FONT_SIZE_SCALE = {
    "friz": 1.00,
    "arial": 1.00,
    # OpenDyslexic runs visually larger than Friz at the same point size, but
    # 0.82 was too aggressive and made normal 9/10 pt labels hard to read.
    # 0.92 keeps the fixed-height rows inside the 1000x700 layout without
    # shrinking body copy into tiny text.
    "opendyslexic": 0.92,
}

_FONT_DIR_NAMES = ("fonts",)
_REGISTERED_PRIVATE_FONTS = set()


def _first_installed(root: tk.Misc, candidates: tuple[str, ...]) -> str | None:
    try:
        installed = {name.casefold(): name for name in tkfont.families(root)}
    except tk.TclError:
        return None
    for candidate in candidates:
        if candidate.casefold() in installed:
            return installed[candidate.casefold()]
    return None


def _bundled_font_paths() -> list[str]:
    paths = []
    bases = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        bases.append(meipass)
    bases.append(branding.app_dir())
    # The fonts ship in the app's own fonts folder. Files dropped into
    # %LOCALAPPDATA%\EqUpdater\fonts are registered too, on next launch.
    bases.append(branding.app_data_dir())
    seen = set()
    for base in bases:
        for folder in _FONT_DIR_NAMES:
            font_dir = os.path.join(base, folder)
            if not os.path.isdir(font_dir):
                continue
            for name in sorted(os.listdir(font_dir)):
                if not name.lower().endswith((".ttf", ".otf")):
                    continue
                path = os.path.normpath(os.path.join(font_dir, name))
                if path not in seen:
                    seen.add(path)
                    paths.append(path)
    return paths


def _font_file_for(choice: str) -> str | None:
    """The regular-weight file of a font choice: shipped with EqUpdater, or
    Windows' own Arial."""
    if choice == "arial":
        path = os.path.join(os.environ.get("WINDIR", r"C:\Windows"),
                            "Fonts", "arial.ttf")
        return path if os.path.isfile(path) else None
    prefix = {"friz": "frizquadrata", "opendyslexic": "opendyslexic"}.get(choice)
    if not prefix:
        return None
    matches = [p for p in _bundled_font_paths()
               if os.path.basename(p).lower().startswith(prefix)]
    regular = [p for p in matches if "regular" in os.path.basename(p).lower()]
    return (regular or matches or [None])[0]


def _register_private_fonts() -> None:
    """Register bundled font files for the current process on Windows.

    Tk can only select a family name that the OS knows about.  Shipping the
    font files beside the app is therefore not enough on Windows unless they
    are registered with GDI first.  ``FR_PRIVATE`` keeps the registration
    process-local rather than installing anything system-wide.
    """
    if os.name != "nt":
        return
    try:
        import ctypes
        from ctypes import wintypes
        gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        add_font = gdi32.AddFontResourceExW
        add_font.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.LPVOID]
        add_font.restype = wintypes.INT
        FR_PRIVATE = 0x10
        for path in _bundled_font_paths():
            norm = os.path.normpath(path)
            if norm in _REGISTERED_PRIVATE_FONTS or not os.path.isfile(norm):
                continue
            added = add_font(norm, FR_PRIVATE, None)
            if added:
                _REGISTERED_PRIVATE_FONTS.add(norm)
        # **No WM_FONTCHANGE broadcast.** Private fonts are invisible to
        # other programs, so there is nothing to tell them -- and
        # SendMessage(HWND_BROADCAST) waits for *every* top-level window on
        # the desktop to answer. One that is not pumping messages (a game
        # mid-load, or an earlier EqUpdater stuck here) blocked this call
        # forever, before EqUpdater's window existed: a process in Task
        # Manager with nothing on screen.
    except Exception:
        pass


class FontManager:
    """Resolve the EqUpdater font family in one place.

    Arial is the default face; the user can switch to Friz Quadrata or
    OpenDyslexic live from Settings.  When bundled font files are present they
    are registered privately for this process on Windows so the choices work
    even without a system-wide install.
    """

    def __init__(self, root: tk.Misc, choice: str = "arial"):
        _register_private_fonts()
        self.root = root
        self.friz = _first_installed(root, FRIZ_FAMILIES)
        self.arial = _first_installed(root, ARIAL_FAMILIES)
        self.open_dyslexic = _first_installed(root, OPEN_DYSLEXIC_FAMILIES)
        self.fallback = _first_installed(root, (FALLBACK_FAMILY, "Times New Roman", "TkDefaultFont")) or FALLBACK_FAMILY
        self.choice = "arial"
        self.set_choice(choice)

    @property
    def family(self) -> str:
        families = FONT_CHOICES.get(self.choice, ARIAL_FAMILIES)
        return families[0]

    @property
    def active_family(self) -> str:
        if self.choice == "arial":
            return self.arial or self.fallback
        if self.choice == "opendyslexic":
            return self.open_dyslexic or self.fallback
        return self.friz or self.fallback

    def _choice_for_family(self, family: str) -> str | None:
        key = (family or "").casefold()
        candidates = {
            "friz": self.friz,
            "arial": self.arial,
            "opendyslexic": self.open_dyslexic,
        }
        for choice, installed in candidates.items():
            if installed and installed.casefold() == key:
                return choice
        for choice, names in FONT_CHOICES.items():
            if any(name.casefold() == key for name in names):
                return choice
        return None

    def preview_font(self, choice: str, size: int) -> tuple:
        """The font that shows what ``choice`` looks like -- its own family at
        its own scale -- whatever is selected now. A face that is not
        installed previews in the fallback."""
        family = {"friz": self.friz, "arial": self.arial,
                  "opendyslexic": self.open_dyslexic}.get(choice)
        return (family or self.fallback, self._scaled_size(size, choice))

    def ink_metrics(self, choice: str, size: int) -> tuple[int, int, int]:
        """(line ascent, capital height, descender), in pixels, of
        ``preview_font(choice, size)``.

        Tk only knows a font's line box. OpenDyslexic's is far taller than
        its letters, which sit low in it, so anything centred on the box sits
        visibly above the text. The letters' own height comes from the font
        file; without the file (or Pillow) it is estimated."""
        font = tkfont.Font(root=self.root, font=self.preview_font(choice, size))
        ascent = int(font.metrics("ascent"))
        cap, desc = round(ascent * 0.72), int(font.metrics("descent"))
        path = _font_file_for(choice)
        if path and ImageFont is not None:
            try:
                px = round(float(self.root.winfo_fpixels("1i"))
                           * abs(int(font.actual("size"))) / 72)
                face = ImageFont.truetype(path, px)
                cap = -face.getbbox("H", anchor="ls")[1]
                desc = face.getbbox("gjpqy", anchor="ls")[3]
            except Exception:
                pass
        return ascent, int(cap), int(desc)

    def _scaled_size(self, logical_size: int | float, choice: str | None = None) -> int:
        selected = choice or self.choice
        scale = FONT_SIZE_SCALE.get(selected, 1.0)
        # Never collapse small labels to unreadable sizes.
        return max(7, int(round(float(logical_size) * scale)))

    @property
    def dyslexic_available(self) -> bool:
        return self.open_dyslexic is not None

    @property
    def friz_available(self) -> bool:
        return self.friz is not None

    @property
    def arial_available(self) -> bool:
        return self.arial is not None

    def set_choice(self, choice: str) -> None:
        choice = (choice or "friz").strip().lower()
        if choice not in FONT_CHOICES:
            choice = "friz"
        self.choice = choice

    def spec(self, size: int, *, bold: bool = False, italic: bool = False,
             underline: bool = False) -> tuple:
        styles = []
        if bold:
            styles.append("bold")
        if italic:
            styles.append("italic")
        if underline:
            styles.append("underline")
        return (self.active_family, self._scaled_size(size), *styles)

    def apply_tree(self, widget: tk.Misc) -> None:
        """Swap user-facing widget fonts while preserving size/style.

        Existing EqUpdater UI code predates the font manager and still contains
        a number of explicit Segoe UI tuples.  Walking the tree lets the
        font selector apply immediately without rebuilding application state.
        Fixed-width technical text stays fixed-width.
        """
        try:
            # A widget that shows a particular face on purpose (the font
            # list in Settings) keeps it whatever is selected.
            if getattr(widget, "keeps_own_font", False):
                raise ValueError("fixed font")
            if "font" in widget.keys():
                current = widget.cget("font")
                f = tkfont.Font(root=self.root, font=current)
                family = str(f.actual("family"))
                fam_key = family.casefold()
                if fam_key not in MONO_FAMILIES and "symbol" not in fam_key:
                    size = int(f.actual("size"))
                    weight = str(f.actual("weight"))
                    slant = str(f.actual("slant"))
                    underline = bool(int(f.actual("underline")))
                    current_choice = self._choice_for_family(family)
                    current_scale = FONT_SIZE_SCALE.get(current_choice or "friz", 1.0)
                    logical_size = size / current_scale if current_scale else size
                    target_size = self._scaled_size(logical_size)
                    widget.configure(font=(
                        self.active_family, target_size,
                        *(["bold"] if weight == "bold" else []),
                        *(["italic"] if slant == "italic" else []),
                        *(["underline"] if underline else []),
                    ))
        except (tk.TclError, ValueError, TypeError):
            pass
        for child in widget.winfo_children():
            self.apply_tree(child)


def cover_background(path: str, width: int, height: int, *, darken: float = 0.92):
    """Return a Pillow image cover-cropped to ``width`` × ``height``."""
    if Image is None or not path or not os.path.exists(path):
        return None
    with Image.open(path) as src:
        src = src.convert("RGB")
        scale = max(width / src.width, height / src.height)
        size = (max(1, round(src.width * scale)), max(1, round(src.height * scale)))
        img = src.resize(size, Image.Resampling.LANCZOS)
        left = max(0, (img.width - width) // 2)
        top = max(0, (img.height - height) // 2)
        img = img.crop((left, top, left + width, top + height))
        if darken != 1.0 and ImageEnhance is not None:
            img = ImageEnhance.Brightness(img).enhance(darken)
        return img.copy()


def photo_image(image, master=None):
    if ImageTk is None or image is None:
        return None
    return ImageTk.PhotoImage(image, master=master)


def style_title_bar(window, *, caption: str | None = None,
                    text: str | None = None, dark: bool = True) -> bool:
    """Colour the native Windows title bar through DWM. Returns whether
    Windows accepted anything; a no-op off Windows.

    What Windows allows depends on the version, and each request simply
    fails on a version that does not know it:

    - Windows 10 1809+ and 11: the dark title bar (``dark``).
    - Windows 11: an exact ``caption`` and ``text`` colour, over the dark one.

    The bar stays the real one, so snapping, the system menu and the taskbar
    all behave as normal -- which a hand-drawn title bar in Tk would not.

    Call it while the window is still withdrawn: Windows 10 paints only part
    of the bar dark when dark mode is switched on after it is showing."""
    if os.name != "nt":
        return False
    try:
        import ctypes
        from ctypes import wintypes
        window.update_idletasks()
        user32 = ctypes.windll.user32
        hwnd = user32.GetParent(window.winfo_id()) or window.winfo_id()
        dwm = ctypes.windll.dwmapi

        def attr(key: int, value: int) -> bool:
            v = ctypes.c_int(value)
            return dwm.DwmSetWindowAttribute(
                wintypes.HWND(hwnd), key, ctypes.byref(v), ctypes.sizeof(v)) == 0

        def colorref(colour: str) -> int:
            r, g, b = (int(colour[i:i + 2], 16) for i in (1, 3, 5))
            return r | (g << 8) | (b << 16)

        accepted = False
        if dark:
            # 20 = DWMWA_USE_IMMERSIVE_DARK_MODE; 19 on builds before 18985.
            accepted = attr(20, 1) or attr(19, 1)
        if caption:
            accepted = attr(35, colorref(caption)) or accepted   # CAPTION_COLOR
        if text:
            attr(36, colorref(text))                               # TEXT_COLOR
        return accepted
    except Exception:
        return False


def edge_fade_layers(width: int, height: int, color: str, *,
                     top: tuple = (0, 0.0), bottom: tuple = (0, 0.0)) -> list:
    """Soft dark gradients for the top and bottom of the background.

    ``top`` and ``bottom`` are (height in px, strength 0..1 at the window
    edge). The strength eases in (smoothstep), so there is no line where a
    fade begins. Returns layers for ``apply_edge_fades``: (solid strip, alpha
    mask, y). Built once; applying them is one masked paste per edge."""
    if Image is None:
        return []
    layers = []
    for (size, strength), at_top in ((top, True), (bottom, False)):
        size = max(0, min(int(size), height))
        if not size or strength <= 0:
            continue
        values = []
        for i in range(size):
            t = (size - i) / size if at_top else (i + 1) / size   # 1 at the edge
            values.append(int(round(255 * strength * t * t * (3 - 2 * t))))
        column = Image.new("L", (1, size))
        column.putdata(values)
        mask = column.resize((width, size), Image.Resampling.NEAREST)
        strip = Image.new("RGB", (width, size), color)
        layers.append((strip, mask, 0 if at_top else height - size))
    return layers


def apply_edge_fades(img, layers):
    """Darken ``img`` in place with ``edge_fade_layers`` output; returns it."""
    for strip, mask, y in layers or ():
        img.paste(strip, (0, y), mask)
    return img


class BackdropCanvas(tk.Canvas):
    """A Canvas used as a panel that shows the window background behind its
    children -- see-through gaps between opaque Tk frames.

    It displays the *same* PhotoImage as the main background, offset by its
    own position, so every animation frame pasted there appears here too,
    aligned to the pixel, at no extra cost.

    tkinter aliases ``Canvas.tkraise``/``lift`` to ``tag_raise`` (raising
    canvas *items*); a stacked panel needs the widget raised, so those are
    restored to the window versions."""

    def __init__(self, parent, **kw):
        kw.setdefault("highlightthickness", 0)
        kw.setdefault("bd", 0)
        super().__init__(parent, **kw)
        self._backdrop = self.create_image(0, 0, anchor="nw")
        self.bind("<Configure>", self._align, add="+")

    def tkraise(self, aboveThis=None):
        tk.Misc.tkraise(self, aboveThis)

    lift = tkraise

    def set_image(self, photo) -> None:
        self.itemconfigure(self._backdrop, image=photo or "")
        self._align()

    def _align(self, _event=None) -> None:
        self.coords(self._backdrop, -self.winfo_x(), -self.winfo_y())
        self.tag_lower(self._backdrop)


class _FrameProducer:
    """The worker half of AnimatedBackground: decodes, crops, scales and
    darkens frames a few ahead into a queue, on its own thread.

    **It holds no Tk object** -- a path, sizes, the fade layers (Pillow
    images), a queue and a stop flag, nothing else. That is the point of the
    split. A thread keeps its target alive until it has finished running, so
    whatever the target references is released *on the worker thread* when
    it exits. When the worker's target was a method of the Tk-facing object,
    that object -- and through it the Tk window -- could be freed there, and
    Tcl aborts the whole process when an interpreter is deleted off the
    thread that created it ("Tcl_AsyncDelete: async handler deleted by the
    wrong thread"). With nothing Tk-owned reachable from here, the worker's
    exit can only ever free Pillow images and Python values."""

    def __init__(self, path: str, width: int, height: int, darken: float,
                 fades, frames_ahead: int):
        self.path, self.width, self.height = path, width, height
        self.darken, self.fades = darken, list(fades or [])
        self.queue: queue.Queue = queue.Queue(maxsize=frames_ahead)
        self.stop_event = threading.Event()
        self.error: str | None = None
        self.thread = threading.Thread(target=self.run, daemon=True,
                                       name="bg-animation")

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        """Ask the worker to finish. Safe from any thread, safe twice."""
        self.stop_event.set()
        try:                          # unblock a worker waiting on put()
            while True:
                self.queue.get_nowait()
        except queue.Empty:
            pass

    def join(self, timeout: float) -> bool:
        """Wait up to ``timeout`` seconds; True once the worker is gone."""
        if self.thread.is_alive() and self.thread is not threading.current_thread():
            self.thread.join(timeout)
        return not self.thread.is_alive()

    def _frame_box(self, w: int, h: int):
        """The part of a w×h frame that covers the window (centre crop)."""
        scale = max(self.width / w, self.height / h)
        cw, ch = self.width / scale, self.height / scale
        left, top = (w - cw) / 2, (h - ch) / 2
        return (left, top, left + cw, top + ch)

    def run(self) -> None:
        try:
            with Image.open(self.path) as gif:
                frames = getattr(gif, "n_frames", 1)
                if frames < 2:
                    raise ValueError("not an animation (1 frame)")
                box = self._frame_box(*gif.size)
                lut = [min(255, int(v * self.darken)) for v in range(256)] * 3
                while not self.stop_event.is_set():
                    for index in range(frames):
                        if self.stop_event.is_set():
                            return
                        gif.seek(index)
                        duration = max(20, int(gif.info.get("duration") or 40))
                        frame = gif.convert("RGB").resize(
                            (self.width, self.height),
                            Image.Resampling.BILINEAR, box=box)
                        if self.darken != 1.0:
                            frame = frame.point(lut)
                        apply_edge_fades(frame, self.fades)
                        while not self.stop_event.is_set():
                            try:
                                self.queue.put((frame, duration), timeout=0.25)
                                break
                            except queue.Full:
                                continue
        except Exception as exc:                        # noqa: BLE001
            if not self.stop_event.is_set():
                self.error = f"{type(exc).__name__}: {exc}"


class AnimatedBackground:
    """Play a looping GIF into one canvas image item, cover-cropped to the
    window.

    **Why frames are made as they play rather than up front.** The supplied
    GIF is 622 frames; at window size each is about 2.8 MB in Tk, so the
    whole loop would need well over a gigabyte. Instead a worker thread
    (``_FrameProducer``) makes a few frames ahead into a small queue -- all
    Pillow, no Tk -- and the Tk thread only pastes the next finished frame
    into a single PhotoImage on an ``after()`` timer. The worker blocks while
    the queue is full, so it never runs ahead of what is shown.

    **Threads.** Everything on this object -- the widget, the canvas, the
    PhotoImage, the ``after()`` job -- belongs to the Tk thread and is only
    touched there. The worker sees only the producer. ``stop()`` cancels the
    timer, tells the worker to finish, optionally waits for it, and releases
    the PhotoImage, all from the Tk thread.

    Frame timing follows the GIF's own per-frame durations against a clock,
    so a late tick does not slow the loop down, and after the last frame it
    goes straight back to the first: the loop is as seamless as the GIF.

    Playback pauses while the window is minimised (the queue fills and the
    worker sleeps). ``on_fail`` is called on the Tk thread if the GIF cannot
    be opened or decoded; the caller shows its static image instead."""

    QUEUE_FRAMES = 4

    def __init__(self, widget, canvas, item, path: str, width: int,
                 height: int, *, darken: float = 0.93, fades=None,
                 on_fail=None, on_image=None):
        self.widget, self.canvas, self.item = widget, canvas, item
        self.path, self.width, self.height = path, width, height
        self.darken, self.on_fail = darken, on_fail
        self.fades = fades or []
        self.on_image = on_image     # told the PhotoImage once it exists
        self.photo = None
        self.error: str | None = None
        self._producer: _FrameProducer | None = None
        self._stopped = False
        self._job = None
        self._due = 0.0
        self._pending = None         # (image, duration) waiting for its time

    # ── lifecycle (Tk thread) ────────────────────────────────────────────

    def start(self) -> None:
        if Image is None or ImageTk is None:
            self._fail("Pillow is not available")
            return
        self._producer = _FrameProducer(self.path, self.width, self.height,
                                        self.darken, self.fades,
                                        self.QUEUE_FRAMES)
        self._producer.start()
        self._schedule(15)

    def stop(self, wait: float = 0.0) -> bool:
        """Stop drawing. Safe to call twice. Returns True once the worker
        thread has exited.

        Cancels the timer, tells the worker to finish and -- with ``wait`` --
        waits for it, then releases the PhotoImage here on the Tk thread. The
        canvas item keeps showing the last frame's name until the caller puts
        something else there, which callers do straight away."""
        self._stopped = True
        if self._job is not None:
            try:
                self.widget.after_cancel(self._job)
            except (tk.TclError, RuntimeError):
                pass
            self._job = None
        gone = True
        if self._producer is not None:
            self._producer.stop()
            gone = self._producer.join(wait) if wait else not self._producer.thread.is_alive()
        self._pending = None
        self.photo = None
        return gone

    # ── Tk thread ────────────────────────────────────────────────────────

    def _schedule(self, delay_ms: int) -> None:
        if self._stopped:
            return
        try:
            self._job = self.widget.after(max(1, int(delay_ms)), self._tick)
        except (tk.TclError, RuntimeError):
            self.stop()

    def _fail(self, why: str) -> None:
        self.error = why
        self.stop()
        if self.on_fail:
            self.on_fail(why)

    def _tick(self) -> None:
        self._job = None
        if self._stopped:
            return
        if self._producer is not None and self._producer.error:
            self._fail(self._producer.error)
            return
        try:
            if self.widget.state() in ("iconic", "withdrawn"):   # not visible
                self._due = 0.0
                self._schedule(250)
                return
        except (tk.TclError, RuntimeError):
            self.stop()
            return

        if self._pending is None:
            try:
                self._pending = self._producer.queue.get_nowait()
            except queue.Empty:
                self._schedule(10)                   # worker still decoding
                return

        now = time.monotonic()
        if self._due and now < self._due:
            self._schedule((self._due - now) * 1000)
            return

        frame, duration = self._pending
        self._pending = None
        try:
            if self.photo is None:
                self.photo = ImageTk.PhotoImage(frame, master=self.widget)
                self.canvas.itemconfigure(self.item, image=self.photo)
                if self.on_image:
                    self.on_image(self.photo)
            else:
                self.photo.paste(frame)
        except (tk.TclError, RuntimeError, ValueError) as exc:
            self._fail(f"{type(exc).__name__}: {exc}")
            return
        # Keep time against the clock; resynchronise after a long stall
        # (a modal dialog, a suspended laptop) instead of racing to catch up.
        self._due = (self._due or now) + duration / 1000.0
        if self._due < now - 0.25:
            self._due = now + duration / 1000.0
        self._schedule((self._due - time.monotonic()) * 1000)


def _hex_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def blend(a: str, b: str, t: float) -> str:
    """Colour ``a`` moved ``t`` (0..1) of the way towards colour ``b``."""
    return _mix(a, b, t)


def _mix(a: str, b: str, t: float) -> str:
    ar, ag, ab = _hex_rgb(a)
    br, bg, bb = _hex_rgb(b)
    vals = (round(ar + (br - ar) * t),
            round(ag + (bg - ag) * t),
            round(ab + (bb - ab) * t))
    return "#%02x%02x%02x" % vals


@dataclass(frozen=True)
class GradientPalette:
    top: str
    bottom: str
    hover_top: str
    hover_bottom: str
    disabled_top: str
    disabled_bottom: str
    fg: str = "#ffffff"
    disabled_fg: str = "#738199"
    border: str = "#243b59"
    hover_border: str = "#54739b"
    #: When set, a disabled button is drawn in its normal colours faded this
    #: far (0..1) towards the canvas background, instead of in the
    #: ``disabled_*`` colours: the same button, dimmed, not a grey one.
    disabled_fade: float | None = None


class GradientButton(tk.Canvas):
    """Small keyboard-accessible Canvas button with a restrained gradient."""

    def __init__(self, parent, *, width: int, height: int, text: str,
                 palette: GradientPalette, command=None, font_factory=None,
                 **kwargs):
        super().__init__(parent, width=width, height=height,
                         highlightthickness=0, bd=0, takefocus=1, **kwargs)
        self._width_px = int(width)
        self._height_px = int(height)
        self._text = text
        self._palette = palette
        self._command = command
        self._font_factory = font_factory
        self._enabled = True
        self._hover = False
        self._pressed = False
        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._leave())
        self.bind("<ButtonPress-1>", lambda e: self._press())
        self.bind("<ButtonRelease-1>", lambda e: self._release(e))
        self.bind("<space>", lambda e: self.invoke())
        self.bind("<Return>", lambda e: self.invoke())
        self.bind("<FocusIn>", lambda e: self._paint())
        self.bind("<FocusOut>", lambda e: self._paint())
        self._paint()

    def set_text(self, text: str) -> None:
        self._text = text
        self._paint()

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        self.configure(cursor="hand2" if self._enabled else "arrow")
        if not self._enabled:
            self._pressed = False
        self._paint()

    def set_palette(self, palette: GradientPalette) -> None:
        self._palette = palette
        self._paint()

    def refresh(self) -> None:
        self._paint()

    def invoke(self) -> None:
        if self._enabled and self._command:
            self._command()

    def _set_hover(self, value: bool) -> None:
        self._hover = value
        self._paint()

    def _leave(self) -> None:
        self._hover = False
        self._pressed = False
        self._paint()

    def _press(self) -> None:
        if self._enabled:
            self._pressed = True
            self._paint()

    def _release(self, event) -> None:
        if not self._enabled:
            return
        inside = 0 <= event.x <= self._width_px and 0 <= event.y <= self._height_px
        was_pressed = self._pressed
        self._pressed = False
        self._paint()
        if was_pressed and inside:
            self.invoke()

    def _paint(self) -> None:
        self.delete("all")
        p = self._palette
        if not self._enabled and p.disabled_fade is not None:
            under, f = self.cget("bg"), p.disabled_fade
            top, bottom = _mix(p.top, under, f), _mix(p.bottom, under, f)
            fg, border = _mix(p.fg, under, f), _mix(p.border, under, f)
        elif not self._enabled:
            top, bottom, fg, border = p.disabled_top, p.disabled_bottom, p.disabled_fg, p.border
        elif self._hover:
            top, bottom, fg, border = p.hover_top, p.hover_bottom, p.fg, p.hover_border
        else:
            top, bottom, fg, border = p.top, p.bottom, p.fg, p.border
        if self._pressed and self._enabled:
            top, bottom = _mix(bottom, "#000000", .10), _mix(bottom, "#000000", .18)

        inner_h = max(1, self._height_px - 2)
        for y in range(1, self._height_px - 1):
            t = (y - 1) / max(1, inner_h - 1)
            self.create_line(1, y, self._width_px - 1, y, fill=_mix(top, bottom, t))
        self.create_rectangle(0, 0, self._width_px - 1, self._height_px - 1,
                              outline=border, width=1)
        if self.focus_get() is self and self._enabled:
            self.create_rectangle(2, 2, self._width_px - 3, self._height_px - 3,
                                  outline=_mix(border, "#ffffff", .35), width=1)
        yoff = 1 if self._pressed and self._enabled else 0
        font = self._font_factory() if self._font_factory else None
        self.create_text(self._width_px // 2, self._height_px // 2 + yoff,
                         text=self._text, fill=fg, font=font)
