"""Réglages, journal, verrou et sauvegardes du Reconnecteur.

Tout est rangé dans ~/Library/Application Support/Reconnecteur/ (modifiable par la variable
d'environnement RECONNECTEUR_DOSSIER, utilisée par les tests) :
  config.json      les paires « dossier rapide ⇄ archive » (par priorité) et les options
  Journal.md       une entrée par reconnexion (lisible par un humain)
  Sauvegardes/     copies .drp du projet faites avant chaque reconnexion (toutes conservées :
                   le Reconnecteur n'efface JAMAIS aucun fichier)
  erreurs.log      traces techniques en cas de problème
"""
from __future__ import annotations

import contextlib
import fcntl
import glob
import json
import os
import re
import traceback
from datetime import datetime
from typing import Iterator, List, Optional, Tuple

DOSSIER = os.environ.get("RECONNECTEUR_DOSSIER") or os.path.expanduser("~/Library/Application Support/Reconnecteur")
CONFIG = os.path.join(DOSSIER, "config.json")
JOURNAL = os.path.join(DOSSIER, "Journal.md")
SAUVEGARDES = os.path.join(DOSSIER, "Sauvegardes")
ERREURS = os.path.join(DOSSIER, "erreurs.log")
VERROU = os.path.join(DOSSIER, ".verrou")

DEFAUTS = {"paires": [], "sauvegarde_avant": True}


def charger() -> dict:
    try:
        with open(CONFIG, encoding="utf-8") as f:
            donnees = json.load(f)
    except (OSError, ValueError):
        return {k: (list(v) if isinstance(v, list) else v) for k, v in DEFAUTS.items()}
    # anciennes versions : 1.0 (« rapide » / « lent »), 1.1 (listes « rapides » / « lents ») → paires dans l'ordre
    if "paires" not in donnees:
        rapides = donnees.get("rapides") or ([donnees["rapide"]] if donnees.get("rapide") else [])
        lents = donnees.get("lents") or ([donnees["lent"]] if donnees.get("lent") else [])
        donnees["paires"] = [{"rapide": r, "lent": l} for r, l in zip(rapides, lents)]
    r = {k: donnees.get(k, v) for k, v in DEFAUTS.items()}
    r["paires"] = [{"rapide": p["rapide"], "lent": p["lent"]} for p in r["paires"]
                   if isinstance(p, dict) and p.get("rapide") and p.get("lent")]
    return r


def enregistrer(reglages: dict) -> None:
    os.makedirs(DOSSIER, exist_ok=True)
    tmp = CONFIG + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({k: reglages.get(k, v) for k, v in DEFAUTS.items()}, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG)  # écriture atomique


class Occupe(Exception):
    """Une autre reconnexion est déjà en cours (autre fenêtre, terminal…)."""


@contextlib.contextmanager
def verrou() -> Iterator[None]:
    os.makedirs(DOSSIER, exist_ok=True)
    f = open(VERROU, "w")
    try:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise Occupe("Une autre reconnexion est déjà en cours.")
        f.write(str(os.getpid()))
        f.flush()
        yield
    finally:
        try:
            fcntl.flock(f, fcntl.LOCK_UN)
        finally:
            f.close()


def journaliser(titre: str, lignes: List[str]) -> Tuple[bool, str]:
    """Ajoute une entrée au journal. Retourne (réussi, message d'erreur) — jamais d'échec silencieux."""
    try:
        os.makedirs(DOSSIER, exist_ok=True)
        neuf = not os.path.exists(JOURNAL) or os.path.getsize(JOURNAL) == 0
        with open(JOURNAL, "a", encoding="utf-8") as j:
            if neuf:
                j.write("# Journal du Reconnecteur\n\nUne entrée par reconnexion, la plus récente en bas.\n")
            j.write(f"\n## {datetime.now():%Y-%m-%d %H:%M} — {titre}\n\n```\n")
            j.write("\n".join(lignes).rstrip() + "\n```\n")
        return True, ""
    except OSError as e:
        return False, str(e)


def noter_erreur(contexte: str) -> str:
    """Écrit la trace de l'exception courante dans erreurs.log et retourne un résumé d'une ligne."""
    trace = traceback.format_exc()
    try:
        os.makedirs(DOSSIER, exist_ok=True)
        with open(ERREURS, "a", encoding="utf-8") as f:
            f.write(f"\n=== {datetime.now():%Y-%m-%d %H:%M:%S} — {contexte}\n{trace}")
    except OSError:
        pass
    derniere = [l for l in trace.strip().splitlines() if l.strip()]
    return derniere[-1] if derniere else "erreur inconnue"


def nom_fichier_sur(texte: str) -> str:
    return re.sub(r'[/:\\*?"<>|]+', "_", texte).strip() or "projet"


def chemin_sauvegarde(projet: str) -> str:
    os.makedirs(SAUVEGARDES, exist_ok=True)
    return os.path.join(SAUVEGARDES, f"{nom_fichier_sur(projet)} — {datetime.now():%Y-%m-%d %H%M%S}.drp")


def derniere_sauvegarde(projet: str) -> Optional[str]:
    motif = os.path.join(SAUVEGARDES, glob.escape(nom_fichier_sur(projet)) + " — *.drp")
    fichiers = sorted(glob.glob(motif))
    return fichiers[-1] if fichiers else None
