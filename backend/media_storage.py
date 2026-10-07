"""Lokální úložiště obrázků (Game Enrichment B) – nejmenší bezpečná abstrakce pro soukromý self-hosted Standa Hub.

- Soubory leží v MEDIA_DIR (výchozí ./media, gitignore), podsložka podle účelu (např. „wot-screenshots").
- Název souboru generuje server (uuid4 hex + přípona podle SKUTEČNÉHO obsahu); původní název je jen metadata v DB.
- Typ se ověřuje podle signatury souboru (PNG / JPEG / WebP), přípona původního názvu musí odpovídat (je-li uvedená).
- Čtení i mazání jen přes uložený název, který znovu projde regexem a musí ležet uvnitř složky (žádný traversal).
Žádný cloud, žádné servírování libovolných cest.
"""
from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from env_config import env_int

MEDIA_DIR = os.environ.get("MEDIA_DIR", "./media")
MAX_BYTES = min(env_int("WOT_SCREENSHOT_MAX_MB", 10, minimum=1), 50) * 1024 * 1024

# typ → (přípona uloženého souboru, povolené přípony původního názvu)
IMAGE_TYPES = {
    "image/png": ("png", {"png"}),
    "image/jpeg": ("jpg", {"jpg", "jpeg"}),
    "image/webp": ("webp", {"webp"}),
}
STORED_NAME_RE = re.compile(r"^[0-9a-f]{32}\.(png|jpg|webp)$")


class MediaError(ValueError):
    """Neplatný soubor (typ, velikost, název) – API vrací 400/413 s českým textem."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class StoredImage:
    stored_name: str
    content_type: str
    size_bytes: int


def sniff_image_type(data: bytes) -> str | None:
    """Typ podle signatury obsahu – hlavičce Content-Type ani příponě se nevěří."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def clean_original_name(name: str | None) -> str | None:
    """Původní název jen pro zobrazení: bez cesty a řídicích znaků, max. 255 znaků."""
    if not name:
        return None
    base = re.split(r"[\\/]", str(name))[-1]
    base = "".join(ch for ch in base if ch.isprintable()).strip()
    return base[:255] or None


def _folder(purpose: str) -> Path:
    if not re.fullmatch(r"[a-z0-9-]+", purpose):
        raise ValueError("neplatná složka")
    p = (Path(MEDIA_DIR) / purpose).resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


def path_for(purpose: str, stored_name: str) -> Path:
    """Cesta k uloženému souboru – jen pro název vygenerovaný serverem a jen uvnitř složky."""
    if not STORED_NAME_RE.fullmatch(stored_name or ""):
        raise MediaError("Neplatný název souboru.")
    folder = _folder(purpose)
    p = (folder / stored_name).resolve()
    if p.parent != folder:
        raise MediaError("Neplatná cesta.")
    return p


def validate_image(data: bytes, original_name: str | None) -> str:
    if not data:
        raise MediaError("Soubor je prázdný.")
    if len(data) > MAX_BYTES:
        raise MediaError(f"Soubor je větší než {MAX_BYTES // (1024 * 1024)} MB.", status=413)
    ctype = sniff_image_type(data)
    if ctype is None:
        raise MediaError("Podporované jsou jen obrázky PNG, JPEG a WebP.")
    name = clean_original_name(original_name)
    if name and "." in name:
        ext = name.rsplit(".", 1)[1].lower()
        if ext not in IMAGE_TYPES[ctype][1]:
            raise MediaError(f"Přípona .{ext} neodpovídá obsahu souboru ({ctype}).")
    return ctype


def save_image(purpose: str, data: bytes, original_name: str | None) -> StoredImage:
    ctype = validate_image(data, original_name)
    stored = f"{uuid.uuid4().hex}.{IMAGE_TYPES[ctype][0]}"
    target = path_for(purpose, stored)
    # exkluzivní vytvoření: nikdy nepřepíše existující soubor
    with open(target, "xb") as fh:
        fh.write(data)
    return StoredImage(stored_name=stored, content_type=ctype, size_bytes=len(data))


def delete_file(purpose: str, stored_name: str) -> bool:
    """Smaže uložený soubor (chybějící = nic se neděje). Vrací, zda soubor existoval."""
    try:
        p = path_for(purpose, stored_name)
    except MediaError:
        return False
    try:
        p.unlink()
        return True
    except FileNotFoundError:
        return False
