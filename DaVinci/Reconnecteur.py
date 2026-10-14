"""Reconnecteur — lanceur.

- Dans DaVinci Resolve (Workspace → Scripts → Reconnecteur) : ouvre la fenêtre.
  Resolve fournit lui-même les variables « resolve », « fusion » et « bmd ».
- Dans un terminal : ResolvePython Reconnecteur.py [--analyser | --appliquer] [--rapide …] [--lent …]

Le code de l'application est dans le dossier « reconnecteur » à côté de ce fichier
(ou dans ~/Library/Application Support/Reconnecteur/app une fois installé).
"""
import importlib
import os
import sys

_ICI = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else ""
_INSTALLE = os.path.expanduser("~/Library/Application Support/Reconnecteur/app")
for _d in (_ICI, _INSTALLE):
    if _d and os.path.isdir(os.path.join(_d, "reconnecteur")):
        if _d not in sys.path:
            sys.path.insert(0, _d)
        break

import reconnecteur  # noqa: E402

# Resolve garde l'interpréteur entre deux lancements : on recharge pour prendre les mises à jour.
for _nom in ("regles", "config", "resolve_io", "moteur", "fenetre", "__main__"):
    _mod = sys.modules.get(f"reconnecteur.{_nom}")
    if _mod is not None:
        importlib.reload(_mod)
from reconnecteur.__main__ import principal  # noqa: E402

_g = globals()
_dans_resolve = _g.get("resolve") is not None
if _dans_resolve:
    principal([], resolve=_g.get("resolve"), fusion=_g.get("fusion"), bmd=_g.get("bmd"))
elif __name__ == "__main__":
    sys.exit(principal(sys.argv[1:]))
