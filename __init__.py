# -*- coding: utf-8 -*-
# Multiple windows for selected Anki dialogs
# Original idea and code base: Arthur Milchior, anki-Multiple-Windows
# This version is simplified and adapted for newer Anki versions (Qt6, Python 3.9+).

from __future__ import annotations

from typing import Any, Dict, List

import aqt
from aqt import dialogs, mw


# ---------------------------------------------------------------------------
# Config handling
# ---------------------------------------------------------------------------

def _get_config() -> Dict[str, Any]:
    """Return add-on config dict, always nonempty."""
    cfg = mw.addonManager.getConfig(__name__) or {}
    multiple = cfg.get("multiple")

    # Ersteinrichtung: sinnvolle Defaults setzen
    if multiple is None:
        multiple = {
            "default": True,
            # Standarddialoge, bei denen mehrere Instanzen meist keinen Sinn machen
            "About": False,
            "Preferences": False,
        }
        cfg["multiple"] = multiple
        mw.addonManager.writeConfig(__name__, cfg)

    return cfg


def should_be_multiple(name: str) -> bool:
    """Return True if dialog `name` darf mehrfach geöffnet werden."""
    cfg = _get_config()
    multiple = cfg.get("multiple", {})
    if name in multiple:
        return bool(multiple[name])
    return bool(multiple.get("default", True))


# ---------------------------------------------------------------------------
# Mehrere Instanzen offen halten
# ---------------------------------------------------------------------------

_open_multi_dialogs: List[Any] = []

# Originalfunktion sichern, damit wir bei Bedarf zurückfallen können
_original_open = dialogs.open


def _open_patched(name: str, *args: Any, **kwargs: Any) -> Any:
    """
    Patched version von dialogs.open.

    - Falls der Dialogname laut Config nur einfach geöffnet werden darf,
      rufe die Originalfunktion auf.
    - Falls Mehrfachöffnen erlaubt ist, erzeuge eine neue Instanz über
      DialogManager._dialogs und tracke sie in _open_multi_dialogs.
    """
    # Single-instance Dialoge unverändert lassen
    if not should_be_multiple(name):
        return _original_open(name, *args, **kwargs)

    dm = dialogs  # aqt.DialogManager Instanz

    # Versuche, den Creator aus der internen _dialogs Tabelle zu holen
    try:
        creator, _existing_instance = dm._dialogs[name]  # type: ignore[attr-defined]
    except Exception:
        # Wenn das aus irgendeinem Grund fehlschlägt, lieber sicher zurückfallen
        # auf das Standardverhalten, statt Anki abzuschießen.
        return _original_open(name, *args, **kwargs)

    # Neue Instanz erzeugen, ohne die gespeicherte Singleton-Instanz zu überschreiben
    instance = creator(*args, **kwargs)
    _open_multi_dialogs.append(instance)

    # Dafür sorgen, dass beim Schließen die Instanz aus unserer Liste fliegt
    _wrap_close_for_instance(instance)

    return instance


def _wrap_close_for_instance(instance: Any) -> None:
    """
    close Methode der Instanz wrapen, damit sie aus _open_multi_dialogs
    entfernt wird, wenn das Fenster geschlossen wird.
    """
    if not hasattr(instance, "close"):
        return

    original_close = instance.close

    def wrapped_close(*args: Any, **kwargs: Any) -> Any:
        if instance in _open_multi_dialogs:
            _open_multi_dialogs.remove(instance)
        return original_close(*args, **kwargs)

    # type: ignore, da wir dynamisch zur Laufzeit patchen
    instance.close = wrapped_close  # type: ignore[assignment]


# Patch aktivieren
dialogs.open = _open_patched
