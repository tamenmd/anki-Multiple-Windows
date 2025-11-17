# -*- coding: utf-8 -*-
# Multiple windows for selected Anki dialogs
# Original idea and code base: Arthur Milchior, anki-Multiple-Windows
# This version is simplified and adapted for newer Anki versions (Qt6, Python 3.9+).

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from aqt import dialogs, mw
from aqt.qt import qconnect


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
_ORIGINAL_ATTR = "__multiple_windows_original_open__"
_original_open = getattr(DialogManager, _ORIGINAL_ATTR, None)
if _original_open is None:
    _original_open = DialogManager.open
    setattr(DialogManager, _ORIGINAL_ATTR, _original_open)


def _resolve_creator(manager: DialogManager, name: str) -> Optional[Callable[..., Any]]:
    """Return the dialog creator function stored in DialogManager.

def _resolve_creator(name: str) -> Optional[Callable[..., Any]]:
    """Return the dialog creator function stored in DialogManager.

    In recent Anki versions ``DialogManager`` keeps ``DialogState`` dataclasses
    instead of ``(creator, instance)`` tuples in ``_dialogs``.  The helper is
    tolerant to both layouts so the add-on keeps working on older as well as
    current builds.
    """

    try:
        entry = dialogs._dialogs[name]  # type: ignore[attr-defined]
    except Exception:
        return None

    # Classic tuple-based storage used on older Anki builds.
    if isinstance(entry, tuple):
        if entry:
            creator = entry[0]
            if callable(creator):
                return creator  # type: ignore[return-value]
        return None

    # Newer versions expose dataclass-like objects with a ``creator`` attribute.
    creator = getattr(entry, "creator", None)
    if callable(creator):
        return creator

    # Some nightly builds briefly used ``creator_func`` as attribute name.
    creator = getattr(entry, "creator_func", None)
    if callable(creator):
        return creator

    return None


def _remove_instance(instance: Any) -> None:
    """Remove ``instance`` from the bookkeeping list if present."""

    if instance in _open_multi_dialogs:
        _open_multi_dialogs.remove(instance)


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

    creator = _resolve_creator(name)
    if creator is None:
        # Fallback – der Dialog wurde entweder nie registriert oder das Layout
        # des DialogManagers ist unerwartet.  Besser das Originalverhalten
        # beibehalten als Anki zu crashen.
        return _original_open(name, *args, **kwargs)

    # Neue Instanz erzeugen, ohne die gespeicherte Singleton-Instanz zu überschreiben
    instance = creator(*args, **kwargs)
    _open_multi_dialogs.append(instance)

    # Dafür sorgen, dass beim Schließen die Instanz aus unserer Liste fliegt
    _wrap_close_for_instance(instance)
    _watch_qobject(instance)

    return instance


def _wrap_close_for_instance(instance: Any) -> None:
    """
    close Methode der Instanz wrapen, damit sie aus _open_multi_dialogs
    entfernt wird, wenn das Fenster geschlossen wird.
    """
    if not hasattr(instance, "close"):
        return

    if getattr(instance, "__multiple_windows_close_wrapped__", False):
        return

    original_close = instance.close

    def wrapped_close(*args: Any, **kwargs: Any) -> Any:
        _remove_instance(instance)
        return original_close(*args, **kwargs)

    # type: ignore, da wir dynamisch zur Laufzeit patchen
    instance.close = wrapped_close  # type: ignore[assignment]
    instance.__multiple_windows_close_wrapped__ = True  # type: ignore[attr-defined]


def _watch_qobject(instance: Any) -> None:
    """Ensure cleanup if Qt destroys the widget without calling ``close``."""

    destroyed = getattr(instance, "destroyed", None)
    if destroyed is None:
        return

    def on_destroyed(*_args: Any, **_kwargs: Any) -> None:
        _remove_instance(instance)

    try:
        qconnect(destroyed, on_destroyed)
    except Exception:
        # Some dialogs expose ``destroyed`` as signal-like stub only once.  If
        # connecting fails we still have the wrapped ``close`` fallback.
        pass


# Patch aktivieren
DialogManager.open = _open_patched
