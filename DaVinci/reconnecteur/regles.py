"""Cœur du Reconnecteur : la règle « rapide d'abord, lent sinon », sans aucune dépendance à Resolve.

Tout ce module est pur (aucun appel à Resolve) et testable hors de Resolve :
- les chemins sont comparés en Unicode NFC (le tiret « – » d'un nom de volume peut arriver en NFC
  ou en NFD selon la source) ;
- l'existence des fichiers passe par un cache de listings de dossiers (un seul accès disque par
  dossier, même sur un disque dur lent) et comprend les séquences d'images de Resolve
  (« frame_[0001-0100].dpx ») et les motifs printf (« frame_%04d.dpx ») ;
- le plan est une liste d'actions par clip (identifiant unique Resolve), jamais par chemin :
  deux clips qui partagent le même fichier sont deux actions distinctes ;
- la vérification compare deux instantanés (avant / après) et ne croit jamais un simple « True ».
"""
from __future__ import annotations

import os
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional, Tuple

# --------------------------------------------------------------------------- chemins


def nfc(chemin: Optional[str]) -> str:
    return unicodedata.normalize("NFC", chemin or "")


def racine_normalisee(chemin: str) -> str:
    """Chemin absolu, NFC, sans « ~ », terminé par « / »."""
    c = nfc(os.path.abspath(os.path.expanduser(chemin.strip())))
    return c if c.endswith("/") else c + "/"


def volume_de(chemin: str) -> str:
    """« /Volumes/Disque/... » → « /Volumes/Disque » ; sinon « / » (disque interne)."""
    parties = nfc(chemin).split("/")
    if len(parties) > 2 and parties[1] == "Volumes" and parties[2]:
        return "/Volumes/" + parties[2]
    return "/"


GARANTIE = ("Aucun fichier n'est copié, déplacé ni effacé : seul le lien vers le fichier change "
            "dans Resolve. Tes médias restent exactement où ils sont, sur tous les disques.")

RAPIDE, LENT = "rapide", "lent"
SIGNE = {RAPIDE: "⚡", LENT: "🐢"}


def nom_disque(racine: str) -> str:
    """Nom lisible d'une racine : le nom du volume (« Belvoir_DO–4tb »), sinon le nom du dossier."""
    vol = volume_de(racine)
    if vol != "/":
        return vol.split("/")[-1]
    return os.path.basename(racine.rstrip("/")) or "Mac"


def _liste(valeur) -> List[str]:
    if not valeur:
        return []
    if isinstance(valeur, str):
        valeur = [valeur]
    vus: List[str] = []
    for v in valeur:
        if v and v.strip():
            r = racine_normalisee(v)
            if r not in vus:
                vus.append(r)
    return vus


@dataclass(frozen=True)
class Racines:
    """Les disques (dossiers racines) où peuvent se trouver les médias.
    rapides : par ordre de priorité ; lents : archives, utilisés en dernier recours."""
    rapides: Tuple[str, ...]
    lents: Tuple[str, ...] = ()

    @staticmethod
    def depuis(rapides, lents=()) -> "Racines":
        return Racines(tuple(_liste(rapides)), tuple(_liste(lents)))

    @property
    def toutes(self) -> Tuple[str, ...]:
        return self.rapides + self.lents

    @property
    def principal(self) -> str:
        return self.rapides[0] if self.rapides else ""

    def niveau(self, racine: str) -> str:
        return RAPIDE if racine in self.rapides else LENT

    def probleme(self) -> Optional[str]:
        """Configuration invalide ? Retourne un message, sinon None."""
        if not self.rapides:
            return "Ajoute au moins un disque rapide."
        toutes = self.toutes
        if len(set(toutes)) != len(toutes):
            return "Le même dossier est choisi deux fois."
        for a in toutes:
            if a == "/":
                return "Choisis des dossiers précis, pas la racine du Mac."
            for b in toutes:
                if a != b and b.startswith(a):
                    return f"« {b} » est à l'intérieur de « {a} » : choisis des dossiers séparés."
        return None

    def racine_de(self, chemin: str) -> Optional[str]:
        c = nfc(chemin)
        for r in self.toutes:
            if c.startswith(r):
                return r
        return None

    def nom(self, racine: str) -> str:
        """« Belvoir_DO–4tb », ou « Belvoir_DO_12tb › 1B. Mariage » si plusieurs dossiers sur le même disque."""
        vol = volume_de(racine)
        meme_disque = [r for r in self.toutes if volume_de(r) == vol]
        base = nom_disque(racine)
        if len(meme_disque) > 1 and vol != "/" and racine.rstrip("/") != vol:
            return f"{base} › {os.path.basename(racine.rstrip('/'))}"
        return base

    def nom_signe(self, racine: str) -> str:
        return f"{SIGNE[self.niveau(racine)]} {self.nom(racine)}"


@dataclass(frozen=True)
class EtatDossier:
    disponible: bool
    raison: str = ""


def etat_dossier(racine: str, ismount: Callable[[str], bool] = os.path.ismount,
                 isdir: Callable[[str], bool] = os.path.isdir) -> EtatDossier:
    """Un dossier sur un disque externe n'est disponible que si son volume est réellement monté :
    un dossier résiduel « /Volumes/Disque » (disque débranché) ne doit jamais passer pour le disque."""
    vol = volume_de(racine)
    if vol != "/" and not ismount(vol):
        if isdir(vol):
            return EtatDossier(False, "disque non monté (dossier résiduel dans /Volumes)")
        return EtatDossier(False, "disque non branché")
    if not isdir(racine.rstrip("/") or "/"):
        return EtatDossier(False, "dossier introuvable")
    return EtatDossier(True)


# --------------------------------------------------------------------------- existence

_SEQ_CROCHETS = re.compile(r"\[(\d+)-(\d+)\]")
_SEQ_PRINTF = re.compile(r"%0?(\d*)d")


class Disque:
    """Oracle d'existence avec cache de listings : un seul listdir par dossier.

    Sur un disque dur lent, 7 500 os.path.exists coûtent cher ; ici chaque dossier n'est lu
    qu'une fois. Les noms sont comparés en NFC ; en cas d'échec on retombe sur os.path.exists
    (système de fichiers insensible à la casse, liens symboliques…)."""

    def __init__(self, listdir: Callable[[str], List[str]] = os.listdir,
                 exists: Callable[[str], bool] = os.path.exists):
        self._listdir = listdir
        self._exists = exists
        self._cache: Dict[str, Optional[frozenset]] = {}
        self._sous: Dict[str, int] = {}
        self._tailles: Dict[str, Optional[int]] = {}

    def noms(self, dossier: str) -> Optional[frozenset]:
        d = nfc(dossier).rstrip("/") or "/"
        if d not in self._cache:
            try:
                self._cache[d] = frozenset(nfc(n) for n in self._listdir(d))
            except OSError:
                self._cache[d] = None
        return self._cache[d]

    def nb_sous_dossiers(self, dossier: str) -> int:
        d = nfc(dossier).rstrip("/") or "/"
        if d not in self._sous:
            try:
                self._sous[d] = sum(1 for e in os.scandir(d) if e.is_dir() and not e.name.startswith("."))
            except OSError:
                self._sous[d] = 0
        return self._sous[d]

    def taille(self, chemin: str) -> Optional[int]:
        """Taille en octets (None si illisible ou séquence d'images)."""
        c = nfc(chemin)
        if _SEQ_CROCHETS.search(os.path.basename(c)) or _SEQ_PRINTF.search(os.path.basename(c)):
            return None
        if c not in self._tailles:
            try:
                self._tailles[c] = os.stat(c).st_size
            except OSError:
                self._tailles[c] = None
        return self._tailles[c]

    def existe(self, chemin: str) -> bool:
        c = nfc(chemin)
        dossier, nom = os.path.split(c)
        noms = self.noms(dossier)
        m = _SEQ_CROCHETS.search(nom)
        if m:  # séquence Resolve : on teste la première image, padding conservé
            premier = nom[:m.start()] + m.group(1) + nom[m.end():]
            return (noms is not None and premier in noms) or self._exists(os.path.join(dossier, premier))
        m = _SEQ_PRINTF.search(nom)
        if m:
            motif = re.compile(re.escape(nom[:m.start()]) + r"\d+" + re.escape(nom[m.end():]) + r"$")
            return noms is not None and any(motif.match(n) for n in noms)
        if noms is not None and nom in noms:
            return True
        return self._exists(c)


# --------------------------------------------------------------------------- index (recherche par nom)

_IGNORER = (".lrdata", ".lrcat-data", ".cocatalog", ".photoslibrary", ".fcpbundle", ".Trashes", ".Spotlight-V100")


def premiere_image(nom: str) -> str:
    """« frame_[0001-0100].dpx » → « frame_0001.dpx » (nom réel cherché sur le disque)."""
    m = _SEQ_CROCHETS.search(nom)
    return nom[:m.start()] + m.group(1) + nom[m.end():] if m else nom


class Index:
    """Tous les fichiers d'un disque choisi, par nom (insensible à la casse, NFC).
    Construit une seule fois par disque et seulement si on en a besoin (≈ 0,5 s pour 50 000 fichiers)."""

    def __init__(self, walk: Callable = os.walk):
        self._walk = walk
        self._index: Dict[str, Dict[str, List[str]]] = {}

    def candidats(self, racine: str, nom: str) -> List[str]:
        if racine not in self._index:
            table: Dict[str, List[str]] = defaultdict(list)
            for dossier, sous, fichiers in self._walk(racine):
                sous[:] = [d for d in sous if not d.startswith(".") and not d.endswith(_IGNORER)]
                for f in fichiers:
                    if not f.startswith("."):
                        table[nfc(f).casefold()].append(nfc(os.path.join(dossier, f)))
            self._index[racine] = table
        return self._index[racine].get(nfc(nom).casefold(), [])


# Dossiers de cartes mémoire et de caméras : identiques d'un tournage à l'autre, ils ne prouvent rien.
_GENERIQUES = re.compile(
    r"^(dcim|private|m4root|xdroot|clip|clips|sub|thmbnl|general|avchd|bdmv|stream|bpav|clpr|contents|"
    r"video|audio|card ?\d*|a\d{3,4}(\s*-.*)?|b\d{3,4}(\s*-.*)?|\d{3}[a-z_]{5}|\d{8}|\d{3}media|"
    r"camera ?\d*|cam ?[a-z0-9]?|\d{3}gopro|misc|uploads?|photos?|videos?|medias?|1\. ?medias?)$")


def est_generique(dossier: str) -> bool:
    return bool(_GENERIQUES.match(nfc(dossier).casefold().strip()))


def score_parents(chemin_a: str, chemin_b: str) -> int:
    """Nombre de dossiers parents DISTINCTIFS identiques, en remontant depuis le fichier tant que les
    dossiers correspondent (« 00016. Visite/130_1328.MXF » → 1 ; « DCIM/100MSDCF/x » → 0)."""
    a = [p.casefold() for p in nfc(os.path.dirname(chemin_a)).split("/") if p]
    b = [p.casefold() for p in nfc(os.path.dirname(chemin_b)).split("/") if p]
    n = distinctifs = 0
    while n < len(a) and n < len(b) and a[-1 - n] == b[-1 - n]:
        if not est_generique(a[-1 - n]):
            distinctifs += 1
        n += 1
    return distinctifs


@dataclass(frozen=True)
class Trouve:
    chemin: str
    racine: str
    comment: str


@dataclass(frozen=True)
class Ambigu:
    candidats: Tuple[str, ...]


def chercher(chemin: str, rel: Optional[str], racines_ordre: Iterable[str], dispo: Callable[[str], bool],
             disque: "Disque", index: Index, taille: Optional[int] = None):
    """Cherche le fichier sur une famille de disques (par ordre de priorité).
    1) même chemin relatif ; 2) même nom de fichier, départagé par les dossiers parents.
    Si la taille du fichier actuel est connue (il est lisible), un candidat de taille différente
    est rejeté : ce n'est pas le même fichier.
    Retourne Trouve, Ambigu (plusieurs fichiers possibles : on ne touche à rien) ou None."""
    ordre = [r for r in racines_ordre if dispo(r)]
    meme = lambda c: taille is None or disque.taille(c) in (None, taille)
    if rel is not None:
        for r in ordre:
            if disque.existe(r + rel) and meme(r + rel):
                return Trouve(r + rel, r, "même chemin")
    nom = os.path.basename(nfc(chemin))
    if _SEQ_PRINTF.search(nom):
        return None
    cands = [(score_parents(chemin, c), ordre.index(r), c, r) for r in ordre
             for c in index.candidats(r, premiere_image(nom)) if meme(c)]
    if not cands:
        return None
    meilleur = max(c[0] for c in cands)
    if meilleur == 0:
        # même nom mais aucun dossier distinctif en commun : rien ne prouve que c'est le même fichier
        return Ambigu(tuple(sorted(c[2] for c in cands))) if len(cands) > 1 else None
    haut = [c for c in cands if c[0] == meilleur]
    prio = min(c[1] for c in haut)
    haut = [c for c in haut if c[1] == prio]
    if len(haut) > 1:
        return Ambigu(tuple(sorted(c[2] for c in haut)))
    _, _, trouve, racine = haut[0]
    comment = f"retrouvé par nom ({pluriel(meilleur, 'dossier parent')} identique{'s' if meilleur > 1 else ''})"
    return Trouve(nfc(os.path.join(os.path.dirname(trouve), nom)), racine, comment)


# --------------------------------------------------------------------------- décision

DEPLACER = "deplacer"          # à reconnecter vers un autre disque
EN_PLACE = "en_place"          # déjà sur le bon disque
INTROUVABLE = "introuvable"    # absent de tous les disques choisis
AMBIGU = "ambigu"              # plusieurs fichiers possibles : on ne touche à rien
A_VERIFIER = "a_verifier"      # introuvable, mais un des disques choisis n'est pas branché
HORS_RACINES = "hors_racines"  # en ligne, hors des disques choisis : on n'y touche pas
SANS_FICHIER = "sans_fichier"  # timeline, compound, générateur…
BLOQUE = "bloque"              # le disque rapide principal n'est pas disponible : on ne décide rien


@dataclass(frozen=True)
class Decision:
    statut: str
    cible: str = ""
    racine_cible: str = ""
    racine_source: str = ""     # "" si le clip pointe hors des disques choisis
    comment: str = ""
    candidats: Tuple[str, ...] = ()


def decider(chemin: str, racines: Racines, etats: Dict[str, "EtatDossier"], disque: "Disque",
            index: Optional[Index] = None) -> Decision:
    """La règle (choisie par l'utilisateur) :
    - un clip relié à un disque RAPIDE où son fichier existe ne bouge pas ;
    - sinon on cherche le fichier sur les disques rapides (par priorité), puis sur les lents ;
    - un clip en ligne sur un disque lent passe sur un rapide si le fichier y est ;
    - garde-fou : si le disque rapide principal n'est pas disponible, on ne propose RIEN."""
    index = index or Index()
    if not chemin:
        return Decision(SANS_FICHIER)
    c = nfc(chemin)
    src = racines.racine_de(c)
    dispo = lambda r: etats.get(r, EtatDossier(False)).disponible
    if not dispo(racines.principal):
        return Decision(BLOQUE)
    ici = disque.existe(c) if (src is None or dispo(src)) else False
    taille = disque.taille(c) if ici else None
    if src is None and ici:
        return Decision(HORS_RACINES)
    rel = c[len(src):] if src else None
    if ici and racines.niveau(src) == RAPIDE:
        return Decision(EN_PLACE)
    t = chercher(c, rel, racines.rapides, dispo, disque, index, taille)
    if isinstance(t, Trouve) and t.chemin != c:
        return Decision(DEPLACER, t.chemin, t.racine, src or "", t.comment)
    if ici:  # en ligne sur un disque lent, pas de copie sûre sur un rapide
        return Decision(EN_PLACE)
    if isinstance(t, Ambigu):
        return Decision(AMBIGU, racine_source=src or "", candidats=t.candidats)
    t = chercher(c, rel, racines.lents, dispo, disque, index, taille)
    if isinstance(t, Trouve):
        return Decision(DEPLACER, t.chemin, t.racine, src or "", t.comment)
    if isinstance(t, Ambigu):
        return Decision(AMBIGU, racine_source=src or "", candidats=t.candidats)
    if src is None:
        return Decision(HORS_RACINES)
    if not all(dispo(r) for r in racines.toutes):
        return Decision(A_VERIFIER, racine_source=src)
    return Decision(INTROUVABLE, racine_source=src)


# --------------------------------------------------------------------------- plan


@dataclass(frozen=True)
class Clip:
    """Instantané d'un clip du média pool (aucune référence à l'objet Resolve)."""
    uid: str
    chutier: str
    nom: str
    type: str
    chemin: str
    proxy: str = ""


@dataclass(frozen=True)
class Action:
    uid: str
    genre: str          # « media » | « proxy »
    chutier: str
    nom: str
    ancien: str
    nouveau: str
    sens: str           # « Belvoir_DO_12tb ⟶ Belvoir_DO–4tb » (disque d'origine ⟶ disque cible)
    relatif: str        # chemin du fichier relatif au disque cible
    racine_cible: str = ""
    vers_rapide: bool = True
    comment: str = ""   # « même chemin » | « retrouvé par nom (…) »
    groupe: str = ""    # dossier de tournage (chemin absolu), rempli à la construction du plan
    doublon: bool = False

    @property
    def dossier_cible(self) -> str:
        return os.path.dirname(self.nouveau)


@dataclass
class Plan:
    racines: Racines
    etats: Dict[str, "EtatDossier"] = field(default_factory=dict)
    nb_clips: int = 0
    actions: List[Action] = field(default_factory=list)
    introuvables: List[Tuple[Clip, str]] = field(default_factory=list)              # (clip, genre)
    ambigus: List[Tuple[Clip, str, Tuple[str, ...]]] = field(default_factory=list)  # (clip, genre, candidats)
    a_verifier: List[Clip] = field(default_factory=list)
    sous_titres: List[Clip] = field(default_factory=list)
    hors_racines: Dict[str, List[int]] = field(default_factory=dict)                 # volume → [total, hors ligne]
    en_place: int = 0
    sans_fichier: int = 0

    def dispo(self, racine: str) -> bool:
        return self.etats.get(racine, EtatDossier(False)).disponible

    def raison(self, racine: str) -> str:
        return self.etats.get(racine, EtatDossier(False, "inconnu")).raison

    @property
    def bloque(self) -> bool:
        return not self.dispo(self.racines.principal)

    @property
    def absents(self) -> List[str]:
        return [r for r in self.racines.toutes if not self.dispo(r)]

    @property
    def nb_a_verifier(self) -> int:
        """Ce qui demande vraiment l'attention."""
        return (len(self.introuvables) + len(self.ambigus) + len(self.a_verifier) + len(self.sous_titres)
                + sum(h for _, h in self.hors_racines.values()))

    def medias(self) -> List[Action]:
        return [a for a in self.actions if a.genre == "media"]

    def proxys(self) -> List[Action]:
        return [a for a in self.actions if a.genre == "proxy"]

    def groupes(self) -> List[str]:
        return sorted({a.groupe for a in self.actions}, key=lambda g: nfc(g).casefold())

    def actions_des_groupes(self, groupes: Iterable[str]) -> List[Action]:
        g = set(groupes)
        return [a for a in self.actions if a.groupe in g]

    def actions_choisies(self, selection=None) -> List[Action]:
        """selection : None (tout), des groupes, ou des couples (groupe, sens) comme dans la fenêtre."""
        if selection is None:
            return list(self.actions)
        sel = set(selection)
        return [a for a in self.actions if a.groupe in sel or (a.groupe, a.sens) in sel]

    def lignes(self) -> List[Tuple[str, str]]:
        """Lignes de l'affichage : un couple (groupe, sens) par tournage et par trajet."""
        vus: List[Tuple[str, str]] = []
        for a in sorted(self.actions, key=lambda a: (not a.vers_rapide, nfc(a.groupe).casefold(), a.sens)):
            if (a.groupe, a.sens) not in vus:
                vus.append((a.groupe, a.sens))
        return vus


SEUIL_CONTENEUR = 4  # un dossier avec au moins 4 sous-dossiers est un « conteneur » (ex. 1.Medias)


def regrouper(dossiers_relatifs: Iterable[str], est_conteneur: Callable[[str], bool] = lambda d: False) -> Dict[str, str]:
    """Associe chaque dossier relatif (au disque) à son « dossier de tournage ».

    Le tournage est le premier dossier sous la racine ; si ce premier dossier est un conteneur
    (beaucoup de sous-dossiers sur le disque, comme « 1.Medias »), c'est le dossier juste en dessous."""
    groupes: Dict[str, str] = {}
    for d in set(dossiers_relatifs):
        parts = [p for p in d.split("/") if p]
        if not parts:
            groupes[d] = ""
        elif len(parts) >= 2 and est_conteneur(parts[0]):
            groupes[d] = parts[0] + "/" + parts[1]
        else:
            groupes[d] = parts[0]
    return groupes


def construire_plan(clips: Iterable[Clip], racines: Racines, etats: Dict[str, "EtatDossier"],
                    disque: "Disque", index: Optional[Index] = None) -> Plan:
    index = index or Index()
    plan = Plan(racines, dict(etats))
    brutes: List[Action] = []

    def action(clip: Clip, genre: str, ancien: str, d: Decision) -> Action:
        src = racines.nom(d.racine_source) if d.racine_source else nom_disque(ancien) + " (hors des disques choisis)"
        return Action(clip.uid, genre, clip.chutier, clip.nom, nfc(ancien), d.cible,
                      f"{src} ⟶ {racines.nom(d.racine_cible)}", d.cible[len(d.racine_cible):],
                      d.racine_cible, racines.niveau(d.racine_cible) == RAPIDE, d.comment)

    for clip in clips:
        plan.nb_clips += 1
        d = decider(clip.chemin, racines, etats, disque, index)
        if d.statut == SANS_FICHIER:
            plan.sans_fichier += 1
        elif d.statut == HORS_RACINES:
            compte = plan.hors_racines.setdefault(volume_de(clip.chemin), [0, 0])
            compte[0] += 1
            if not disque.existe(clip.chemin):
                compte[1] += 1
        elif d.statut == EN_PLACE:
            plan.en_place += 1
        elif d.statut == INTROUVABLE:
            plan.introuvables.append((clip, "media"))
        elif d.statut == AMBIGU:
            plan.ambigus.append((clip, "media", d.candidats))
        elif d.statut == A_VERIFIER:
            plan.a_verifier.append(clip)
        elif d.statut == DEPLACER:
            if clip.type == "Subtitle":  # Resolve refuse de reconnecter les sous-titres (vérifié)
                plan.sous_titres.append(clip)
            else:
                brutes.append(action(clip, "media", clip.chemin, d))
        if clip.proxy:
            p = decider(clip.proxy, racines, etats, disque, index)
            if p.statut == DEPLACER:
                brutes.append(action(clip, "proxy", clip.proxy, p))
            elif p.statut == INTROUVABLE:
                plan.introuvables.append((clip, "proxy"))
            elif p.statut == AMBIGU:
                plan.ambigus.append((clip, "proxy", p.candidats))
    # doublons : plusieurs clips (uid différents) sur le même fichier
    par_fichier: Dict[Tuple[str, str], int] = defaultdict(int)
    for a in brutes:
        par_fichier[(a.genre, a.ancien)] += 1
    # dossiers de tournage, disque cible par disque cible
    groupes: Dict[Tuple[str, str], str] = {}
    for racine in {a.racine_cible for a in brutes}:
        rels = [os.path.dirname(a.relatif) for a in brutes if a.racine_cible == racine]
        conteneur = lambda premier, r=racine: disque.nb_sous_dossiers(r + premier) >= SEUIL_CONTENEUR
        for rel, g in regrouper(rels, conteneur).items():
            groupes[(racine, rel)] = racine + g
    plan.actions = [
        Action(a.uid, a.genre, a.chutier, a.nom, a.ancien, a.nouveau, a.sens, a.relatif, a.racine_cible,
               a.vers_rapide, a.comment, groupes.get((a.racine_cible, os.path.dirname(a.relatif)), a.racine_cible),
               par_fichier[(a.genre, a.ancien)] > 1)
        for a in brutes
    ]
    return plan


# --------------------------------------------------------------------------- vérification


@dataclass
class Resultat:
    reussis: List[Action] = field(default_factory=list)
    echecs: List[Tuple[Action, str]] = field(default_factory=list)
    ignores: List[Tuple[Action, str]] = field(default_factory=list)   # changés depuis l'analyse
    non_prevus: List[Tuple[str, str, str]] = field(default_factory=list)  # (uid, avant, après)
    sauvegarde: str = ""
    enregistre: Optional[bool] = None
    erreur: str = ""

    @property
    def tout_bon(self) -> bool:
        return not self.echecs and not self.erreur and bool(self.reussis)


Instantane = Dict[str, Tuple[str, str]]  # uid → (chemin média, chemin proxy)


def verifier(actions: List[Action], avant: Instantane, apres: Instantane,
             ignores: Dict[Tuple[str, str], str]) -> Resultat:
    """Compare l'état réel après application à ce qui était prévu, clip par clip (par uid)."""
    r = Resultat()
    prevus = set()
    for a in actions:
        cle = (a.uid, a.genre)
        prevus.add(cle)
        if cle in ignores:
            r.ignores.append((a, ignores[cle]))
            continue
        etat = apres.get(a.uid)
        if etat is None:
            r.echecs.append((a, "clip disparu du média pool"))
            continue
        actuel = nfc(etat[0] if a.genre == "media" else etat[1])
        if actuel == nfc(a.nouveau):
            r.reussis.append(a)
        elif actuel == nfc(a.ancien):
            r.echecs.append((a, "Resolve a refusé la reconnexion (toujours sur l'ancien chemin)"))
        else:
            r.echecs.append((a, "reconnecté ailleurs que prévu : " + actuel))
    for uid, (chemin_av, proxy_av) in avant.items():
        etat = apres.get(uid)
        if etat is None:
            continue
        if (uid, "media") not in prevus and nfc(etat[0]) != nfc(chemin_av):
            r.non_prevus.append((uid, chemin_av, etat[0]))
        if (uid, "proxy") not in prevus and nfc(etat[1]) != nfc(proxy_av):
            r.non_prevus.append((uid, proxy_av, etat[1]))
    return r


# --------------------------------------------------------------------------- textes


def nombre(n: int) -> str:
    """7518 → « 7 518 » (espace fine insécable)."""
    return f"{n:,}".replace(",", " ")


def pluriel(n: int, mot: str, pluriel_mot: str = "") -> str:
    return f"{nombre(n)} {mot if n <= 1 else (pluriel_mot or mot + 's')}"


def nom_volume(vol: str, racines: Optional[Racines] = None) -> str:
    """Nom lisible d'un emplacement hors des disques choisis."""
    if racines is not None:
        for racine in racines.toutes:
            if volume_de(racine) == vol and vol != "/":
                return f"{vol.split('/')[-1]}, hors des dossiers choisis"
    return "Disque du Mac" if vol == "/" else vol.split("/")[-1]


def nom_court(groupe: str) -> str:
    """« …/00108. Visite » → « 00108. Visite » ; « …/1. MEDIAS/A001 » → « 1. MEDIAS/A001 »."""
    parts = [p for p in groupe.rstrip("/").split("/") if p]
    if not parts:
        return "(racine)"
    if est_generique(parts[-1]) and len(parts) > 1:
        return f"{parts[-2]}/{parts[-1]}"
    return parts[-1]


def bilan_directions(racines: Racines, actions: List[Action]) -> List[str]:
    """Une phrase par trajet : « ⚡ 633 clips : Belvoir_DO_12tb ⟶ Belvoir_DO–4tb »."""
    compte: Dict[Tuple[bool, str], List[int]] = defaultdict(lambda: [0, 0])
    for a in actions:
        compte[(a.vers_rapide, a.sens)][0 if a.genre == "media" else 1] += 1
    out = []
    for (vers_rapide, sens), (m, p) in sorted(compte.items(), key=lambda x: (not x[0][0], x[0][1])):
        quoi = " + ".join(([pluriel(m, "clip")] if m else []) + ([pluriel(p, "proxy", "proxys")] if p else []))
        out.append(f"{SIGNE[RAPIDE if vers_rapide else LENT]} {quoi} : {sens}")
    return out


def resume_plan(plan: Plan, selection=None) -> str:
    if plan.bloque:
        return (f"Le disque rapide principal ({plan.racines.nom(plan.racines.principal)}) n'est pas disponible "
                f"({plan.raison(plan.racines.principal)}). Rien n'est proposé.")
    actions = plan.actions_choisies(selection)
    doublons = sum(1 for a in actions if a.genre == "media" and a.doublon)
    morceaux = []
    if actions:
        morceaux.append("À reconnecter : " + "  ·  ".join(bilan_directions(plan.racines, actions))
                        + (f" (dont {nombre(doublons)} clips en double dans le média pool)" if doublons else ""))
    else:
        morceaux.append("Rien à reconnecter : tous les médias sont déjà sur le bon disque")
    if plan.absents:
        morceaux.append("non branché(s) : " + ", ".join(plan.racines.nom(r) for r in plan.absents))
    if plan.a_verifier:
        morceaux.append(f"{pluriel(len(plan.a_verifier), 'clip')} introuvable(s) pour l'instant (disque débranché)")
    if plan.ambigus:
        morceaux.append(f"{pluriel(len(plan.ambigus), 'clip')} avec plusieurs fichiers possibles (non touchés)")
    if plan.introuvables:
        morceaux.append(f"{pluriel(len(plan.introuvables), 'fichier')} introuvable(s) sur tous les disques")
    if plan.sous_titres:
        morceaux.append(f"{pluriel(len(plan.sous_titres), 'sous-titre')} que Resolve ne sait pas reconnecter")
    hors_ligne = sum(v[1] for v in plan.hors_racines.values())
    if hors_ligne:
        morceaux.append(f"{pluriel(hors_ligne, 'clip')} hors ligne ailleurs")
    return " · ".join(morceaux) + "."


def lignes_rapport(plan: Plan, resultat: Optional[Resultat] = None, limite: int = 40) -> List[str]:
    """Rapport texte (terminal et journal). Aucune troncature silencieuse : « … et N autres »."""
    L: List[str] = []

    def section(titre: str, elements: List[str]) -> None:
        if not elements:
            return
        L.append(titre)
        L.extend("  " + e for e in elements[:limite])
        if len(elements) > limite:
            L.append(f"  … et {nombre(len(elements) - limite)} autres")
        L.append("")

    def par_groupe(actions: List[Action]) -> List[str]:
        compte: Dict[Tuple[str, str], List[int]] = defaultdict(lambda: [0, 0])
        for a in actions:
            compte[(a.groupe, a.sens)][0 if a.genre == "media" else 1] += 1
        out = []
        for (g, sens), (nm, np_) in sorted(compte.items(), key=lambda x: nfc(x[0][0]).casefold()):
            morceaux = ([pluriel(nm, "clip")] if nm else []) + ([pluriel(np_, "proxy", "proxys")] if np_ else [])
            out.append(f"{' + '.join(morceaux):>11}  {nom_court(g)}  ({sens})")
        return out

    for r in plan.racines.toutes:
        etat = "disponible" if plan.dispo(r) else plan.raison(r)
        L.append(f"{plan.racines.nom_signe(r):<28} {r}  [{etat}]")
    L += [GARANTIE, f"{pluriel(plan.nb_clips, 'clip')} lus dans le média pool.", ""]
    if resultat is None:
        L += [resume_plan(plan), ""]
        section("À reconnecter :", par_groupe(plan.actions))
    else:
        if resultat.erreur:
            L += [f"⚠ ERREUR : {resultat.erreur}", ""]
        if resultat.sauvegarde:
            L += [f"Copie de sécurité du projet : {resultat.sauvegarde}", ""]
        L += [f"✓ {b}" for b in bilan_directions(plan.racines, resultat.reussis)] + ([""] if resultat.reussis else [])
        section(f"✓ Reconnectés ({nombre(len(resultat.reussis))}) :", par_groupe(resultat.reussis))
        section(f"⚠ Échecs ({nombre(len(resultat.echecs))}) :",
                [f"{a.nom} [{a.genre}] — {motif}" for a, motif in resultat.echecs])
        section(f"Ignorés, modifiés depuis l'analyse ({nombre(len(resultat.ignores))}) :",
                [f"{a.nom} [{a.genre}] — {motif}" for a, motif in resultat.ignores])
        section(f"Changements non prévus détectés ({nombre(len(resultat.non_prevus))}) :",
                [f"{os.path.basename(av)} : {av} → {ap}" for _, av, ap in resultat.non_prevus])
        if resultat.enregistre is not None:
            L += ["Projet enregistré." if resultat.enregistre else "⚠ Projet NON enregistré : fais Cmd+S.", ""]
    section("Plusieurs fichiers possibles (non touchés, à relier à la main) :",
            [f"{c.nom} [{genre}] — {len(cands)} candidats : " + " | ".join(cands[:3]) for c, genre, cands in plan.ambigus])
    section("Introuvables sur tous les disques choisis :",
            [f"{c.nom} [{genre}] — {c.proxy if genre == 'proxy' else c.chemin}" for c, genre in plan.introuvables])
    section("Introuvables pour l'instant (un disque choisi n'est pas branché) :", [f"{c.nom} — {c.chemin}" for c in plan.a_verifier])
    section("Sous-titres (Resolve ne permet pas de les reconnecter par script) :", [f"{c.nom} — {c.chemin}" for c in plan.sous_titres])
    section("Clips hors des disques choisis (non traités) :",
            [f"{nom_volume(vol, plan.racines)} : {pluriel(t, 'clip')}, dont {nombre(h)} hors ligne" for vol, (t, h) in sorted(plan.hors_racines.items())])
    return L
