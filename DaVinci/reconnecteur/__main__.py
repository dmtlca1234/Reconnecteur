"""Point d'entrée : fenêtre par défaut, ou mode terminal (--analyser / --appliquer).

  ResolvePython -m reconnecteur                 ouvre la fenêtre dans Resolve
  ResolvePython -m reconnecteur --analyser      rapport dans le terminal, aucune modification
  ResolvePython -m reconnecteur --appliquer     reconnecte tout, sans fenêtre (avec copie de sécurité)
  options : --paire RAPIDE ARCHIVE (répétable, par priorité) — sinon les paires enregistrées ;
            --sans-sauvegarde
"""
from __future__ import annotations

import argparse
import sys

from . import VERSION, config, moteur, regles, resolve_io


def principal(argv=None, resolve=None, fusion=None, bmd=None) -> int:
    ap = argparse.ArgumentParser(prog="reconnecteur", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--analyser", action="store_true")
    ap.add_argument("--appliquer", action="store_true")
    ap.add_argument("--paire", nargs=2, action="append", metavar=("RAPIDE", "ARCHIVE"))
    ap.add_argument("--sans-sauvegarde", action="store_true")
    ap.add_argument("--version", action="version", version=f"Reconnecteur {VERSION}")
    args = ap.parse_args(argv)
    if not (args.analyser or args.appliquer):
        from . import fenetre
        fenetre.ouvrir(resolve, fusion, bmd)
        return 0
    reglages = config.charger()
    racines = regles.Racines.depuis(args.paire or reglages["paires"])
    if not racines.paires:
        print("Aucune paire configurée : ouvre la fenêtre une première fois, ou passe --paire RAPIDE ARCHIVE.")
        return 2
    if racines.probleme():
        print("⚠ " + racines.probleme())
        return 2
    try:
        resolve = resolve_io.connecter(resolve)
        projet = resolve_io.projet_courant(resolve)
    except RuntimeError as e:
        print(f"⚠ {e}")
        return 3
    print(f"Projet : {projet.GetName()}", flush=True)
    plan = moteur.analyser(resolve, projet, racines)
    if args.analyser or not plan.actions:
        print("\n".join(regles.lignes_rapport(plan)))
        return 0
    r = moteur.reconnecter(resolve, projet, plan, None, not args.sans_sauvegarde,
                           lambda t: print(t, file=sys.stderr, flush=True))
    ok, err = moteur.journaliser(projet.GetName(), plan, r)
    print("\n".join(regles.lignes_rapport(plan, r)))
    if not ok:
        print(f"⚠ Journal non écrit : {err}")
    return 0 if not (r.erreur or r.echecs) else 1


if __name__ == "__main__":
    sys.exit(principal())
