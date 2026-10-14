"""Couche Resolve : lecture du média pool, application des reconnexions, sauvegarde.

Leçons tirées des essais et de l'audit (2026-10-09, Resolve 21.1) :
- RelinkClips(clips, dossier) ne reconnecte QUE les objets passés : deux clips du même fichier
  dans deux chutiers sont deux objets à passer. On travaille donc par identifiant unique (uid).
- On ne garde jamais des milliers de références d'objets Resolve en mémoire : on relit des objets
  frais, chutier par chutier, au moment de s'en servir.
- On ne croit pas un « True » : on relit l'état réel après coup et on compare (regles.verifier).
- Les sous-titres ne sont reconnectables ni par RelinkClips ni par ReplaceClip.
"""
from __future__ import annotations

import os
from collections import defaultdict
from typing import Callable, Dict, Iterator, List, Optional, Tuple

from . import regles
from .regles import Action, Clip, Instantane, nfc

Progression = Callable[[str], None]


def _rien(_: str) -> None:
    pass


def connecter(resolve=None):
    """Retourne l'objet Resolve (déjà fourni dans le menu Scripts, sinon via le scripting externe)."""
    if resolve is not None:
        return resolve
    import DaVinciResolveScript as dvr  # disponible dans ResolvePython
    r = dvr.scriptapp("Resolve")
    if r is None:
        raise RuntimeError("DaVinci Resolve n'est pas ouvert, ou le scripting externe est désactivé "
                           "(Préférences → Système → Général → Scripting externe : Local).")
    return r


def projet_courant(resolve):
    pm = resolve.GetProjectManager()
    p = pm.GetCurrentProject() if pm else None
    if p is None:
        raise RuntimeError("Aucun projet ouvert dans Resolve.")
    return p


def chutiers(projet) -> Iterator[Tuple[object, str]]:
    """Parcourt tous les chutiers (dossiers du média pool) : (objet dossier, chemin lisible)."""
    racine = projet.GetMediaPool().GetRootFolder()
    pile = [(racine, racine.GetName() or "Master")]
    while pile:
        dossier, nom = pile.pop()
        yield dossier, nom
        for sous in reversed(dossier.GetSubFolderList() or []):
            pile.append((sous, f"{nom}/{sous.GetName()}"))


def _props(clip) -> Tuple[str, str, str, str, Optional[float]]:
    """(chemin, proxy, type, nom, date de modification connue par Resolve).
    Forme canonique GetClipProperty() (dict) ; la forme par clé est dépréciée depuis Resolve 21.1."""
    d = clip.GetClipProperty() or {}
    return (d.get("File Path") or "", d.get("Proxy Media Path") or "",
            d.get("Type") or "", d.get("Clip Name") or "", regles.lire_date_resolve(d.get("Date Modified")))


def lire_clips(projet, progression: Progression = _rien) -> List[Clip]:
    clips: List[Clip] = []
    for dossier, nom_chutier in chutiers(projet):
        for c in dossier.GetClipList() or []:
            chemin, proxy, type_, nom, date = _props(c)
            clips.append(Clip(c.GetUniqueId(), nom_chutier, nom, type_, chemin, proxy, date))
            if len(clips) % 250 == 0:
                progression(f"Lecture du média pool… {regles.nombre(len(clips))} clips")
    return clips


def instantane(projet, progression: Progression = _rien) -> Instantane:
    etat: Instantane = {}
    for dossier, _ in chutiers(projet):
        for c in dossier.GetClipList() or []:
            chemin, proxy = _props(c)[:2]
            etat[c.GetUniqueId()] = (chemin, proxy)
            if len(etat) % 500 == 0:
                progression(f"Vérification… {regles.nombre(len(etat))} clips relus")
    return etat


def appliquer(projet, actions: List[Action], progression: Progression = _rien) -> Dict[Tuple[str, str], str]:
    """Applique les actions, chutier par chutier, sur des objets frais.

    Retourne les actions ignorées {(uid, genre): motif} — le clip a changé depuis l'analyse.
    Le succès réel se mesure ensuite avec instantane() + regles.verifier()."""
    mp = projet.GetMediaPool()
    medias = {a.uid: a for a in actions if a.genre == "media"}
    proxys = {a.uid: a for a in actions if a.genre == "proxy"}
    ignores: Dict[Tuple[str, str], str] = {}
    faits = 0
    total = len(actions)
    for dossier, _ in chutiers(projet):
        par_cible: Dict[str, list] = defaultdict(list)
        a_proxyfier: List[str] = []
        for c in dossier.GetClipList() or []:
            uid = c.GetUniqueId()
            if uid not in medias and uid not in proxys:
                continue
            chemin, proxy = _props(c)[:2]
            a = medias.get(uid)
            if a is not None:
                if nfc(chemin) != nfc(a.ancien):
                    ignores[(uid, "media")] = "le clip a changé depuis l'analyse"
                else:
                    par_cible[a.dossier_cible].append(c)
            if uid in proxys:
                if nfc(proxy) != nfc(proxys[uid].ancien):
                    ignores[(uid, "proxy")] = "le proxy a changé depuis l'analyse"
                else:
                    a_proxyfier.append(uid)
        for cible, objets in par_cible.items():
            mp.RelinkClips(objets, cible + "/")
            faits += len(objets)
            progression(f"Reconnexion… {regles.nombre(faits)} / {regles.nombre(total)}")
        if a_proxyfier:
            frais = {c.GetUniqueId(): c for c in dossier.GetClipList() or []}  # objets frais après RelinkClips
            for uid in a_proxyfier:
                c = frais.get(uid)
                if c is not None:
                    c.LinkProxyMedia(proxys[uid].nouveau)
                faits += 1
            progression(f"Reconnexion… {regles.nombre(faits)} / {regles.nombre(total)}")
    return ignores


def sauvegarder_drp(resolve, projet, chemin: str) -> bool:
    """Copie de sécurité du projet (.drp, sans stills ni LUTs pour rester léger)."""
    pm = resolve.GetProjectManager()
    return bool(pm.ExportProject(projet.GetName(), chemin, False)) and os.path.exists(chemin)


def enregistrer(resolve) -> bool:
    return bool(resolve.GetProjectManager().SaveProject())
