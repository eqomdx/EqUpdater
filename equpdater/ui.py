"""Visual helpers for EqUpdater.

The UI deliberately keeps the update/business logic in :mod:`equpdater.app`.
This module only owns presentation primitives that Tk does not provide well:
font-family switching, cover-cropped background artwork, and subtle gradient
buttons.
"""

from __future__ import annotations

import glob
import os
import sys
import zipfile
import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass

from . import branding

try:
    from PIL import Image, ImageEnhance, ImageTk
except Exception:  # pragma: no cover - source can still start without Pillow
    Image = ImageEnhance = ImageTk = None


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
    # Also support user-supplied fonts without requiring an app rebuild. This
    # is especially useful for OpenDyslexic: dropping its .otf files into
    # %LOCALAPPDATA%\EqUpdater\fonts makes the selector work on next launch.
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


def _extract_local_font_archives() -> None:
    """Import user-supplied font archives placed beside EqUpdater.

    Font binaries are not part of EqUpdater itself.  If the user already has
    one of the supported font archives, dropping it beside the app/project is
    enough: the relevant .ttf/.otf files are copied into the user's EqUpdater
    data directory and can then be registered privately for this process.
    """
    dest = os.path.join(branding.app_data_dir(), "fonts")
    patterns = (
        "opendyslexic*.zip",
        "friz-quadrata*.zip",
        "friz*.zip",
        "arial*.zip",
    )
    archives = []
    search_bases = [branding.app_dir(), branding.app_data_dir()]
    home = os.path.expanduser("~")
    for extra in (os.path.join(home, "Downloads"), os.path.join(home, "Desktop"), os.path.join(home, "Documents")):
        if extra not in search_bases:
            search_bases.append(extra)
    for base in search_bases:
        for pattern in patterns:
            archives.extend(glob.glob(os.path.join(base, pattern)))
    if not archives:
        return
    try:
        os.makedirs(dest, exist_ok=True)
    except OSError:
        return
    for archive in sorted(set(archives)):
        try:
            with zipfile.ZipFile(archive) as zf:
                for info in zf.infolist():
                    name = os.path.basename(info.filename)
                    if not name or not name.lower().endswith((".ttf", ".otf")):
                        continue
                    target = os.path.join(dest, name)
                    if os.path.exists(target):
                        continue
                    with zf.open(info) as src, open(target, "wb") as out:
                        out.write(src.read())
        except (OSError, zipfile.BadZipFile, KeyError):
            continue


def _register_private_fonts() -> None:
    """Register bundled font files for the current process on Windows.

    Tk can only select a family name that the OS knows about.  Shipping the
    font files beside the app is therefore not enough on Windows unless they
    are registered with GDI first.  ``FR_PRIVATE`` keeps the registration
    process-local rather than installing anything system-wide.
    """
    if os.name != "nt":
        return
    _extract_local_font_archives()
    try:
        import ctypes
        from ctypes import wintypes
        gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        add_font = gdi32.AddFontResourceExW
        add_font.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.LPVOID]
        add_font.restype = wintypes.INT
        FR_PRIVATE = 0x10
        WM_FONTCHANGE = 0x001D
        HWND_BROADCAST = 0xFFFF
        for path in _bundled_font_paths():
            norm = os.path.normpath(path)
            if norm in _REGISTERED_PRIVATE_FONTS or not os.path.isfile(norm):
                continue
            added = add_font(norm, FR_PRIVATE, None)
            if added:
                _REGISTERED_PRIVATE_FONTS.add(norm)
        if _REGISTERED_PRIVATE_FONTS:
            try:
                user32.SendMessageW(HWND_BROADCAST, WM_FONTCHANGE, 0, 0)
            except Exception:
                pass
    except Exception:
        pass


class FontManager:
    """Resolve the EqUpdater font family in one place.

    Friz Quadrata is the default face, but the user can switch to Arial or
    OpenDyslexic live from Settings.  When bundled font files are present they
    are registered privately for this process on Windows so the choices work
    even without a system-wide install.
    """

    def __init__(self, root: tk.Misc, choice: str = "friz"):
        _register_private_fonts()
        self.root = root
        self.friz = _first_installed(root, FRIZ_FAMILIES)
        self.arial = _first_installed(root, ARIAL_FAMILIES)
        self.open_dyslexic = _first_installed(root, OPEN_DYSLEXIC_FAMILIES)
        self.fallback = _first_installed(root, (FALLBACK_FAMILY, "Times New Roman", "TkDefaultFont")) or FALLBACK_FAMILY
        self.choice = "friz"
        self.set_choice(choice)

    @property
    def available_choices(self) -> dict[str, bool]:
        return {
            "friz": self.friz is not None,
            "arial": self.arial is not None,
            "opendyslexic": self.open_dyslexic is not None,
        }

    @property
    def family(self) -> str:
        families = FONT_CHOICES.get(self.choice, FRIZ_FAMILIES)
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

    def _scaled_size(self, logical_size: int | float, choice: str | None = None) -> int:
        selected = choice or self.choice
        scale = FONT_SIZE_SCALE.get(selected, 1.0)
        # Never collapse small labels to unreadable sizes.
        return max(7, int(round(float(logical_size) * scale)))

    @property
    def dyslexic(self) -> bool:
        return self.choice == "opendyslexic"

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

    def set_dyslexic(self, enabled: bool) -> None:
        self.choice = "opendyslexic" if enabled else "friz"

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


def _hex_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


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
        if not self._enabled:
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
