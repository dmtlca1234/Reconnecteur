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


@dataclass(frozen=True)
class Paire:
    """Un dossier rapide et SON archive : même rangement des deux côtés (comme une paire FreeFileSync)."""
    rapide: str
    lent: str


@dataclass(frozen=True)
class Racines:
    """Les paires de dossiers choisies, par ordre de priorité.
    Un clip ne passe jamais que d'un dossier à son jumeau, au même chemin relatif."""
    paires: Tuple[Paire, ...]

    @staticmethod
    def depuis(paires) -> "Racines":
        """paires : liste de (rapide, lent), de dicts {"rapide", "lent"} ou de Paire."""
        out: List[Paire] = []
        for x in paires or []:
            if isinstance(x, Paire):
                r, l = x.rapide, x.lent
            elif isinstance(x, dict):
                r, l = x.get("rapide", ""), x.get("lent", "")
            else:
                r, l = x
            if r and r.strip() and l and l.strip():
                out.append(Paire(racine_normalisee(r), racine_normalisee(l)))
        return Racines(tuple(out))

    @property
    def rapides(self) -> Tuple[str, ...]:
        return tuple(p.rapide for p in self.paires)

    @property
    def lents(self) -> Tuple[str, ...]:
        return tuple(p.lent for p in self.paires)

    @property
    def toutes(self) -> Tuple[str, ...]:
        return self.rapides + self.lents

    @property
    def principal(self) -> str:
        return self.paires[0].rapide if self.paires else ""

    def niveau(self, racine: str) -> str:
        return RAPIDE if racine in self.rapides else LENT

    def paire_de(self, racine: str) -> Optional[Paire]:
        for p in self.paires:
            if racine in (p.rapide, p.lent):
                return p
        return None

    def probleme(self) -> Optional[str]:
        """Configuration invalide ? Retourne un message, sinon None."""
        if not self.paires:
            return "Ajoute au moins une paire « dossier rapide ⇄ archive »."
        toutes = self.toutes
        if len(set(toutes)) != len(toutes):
            return "Le même dossier est utilisé deux fois."
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
        self._stats: Dict[str, Optional[Tuple[int, float]]] = {}

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

    def stat(self, chemin: Optional[str]) -> Optional[Tuple[int, float]]:
        """(taille en octets, date de modification) ; pour une séquence, ceux de la première image."""
        if not chemin:
            return None
        c = nfc(chemin)
        dossier, nom = os.path.split(c)
        m = _SEQ_PRINTF.search(nom)
        if m:  # « frame_%04d.dpx » : la première image présente dans le dossier
            motif = re.compile(re.escape(nom[:m.start()]) + r"\d+" + re.escape(nom[m.end():]) + r"$")
            images = sorted(n for n in (self.noms(dossier) or ()) if motif.match(n))
            if not images:
                return None
            nom = images[0]
        c = os.path.join(dossier, premiere_image(nom))
        if c not in self._stats:
            try:
                st = os.stat(c)
                self._stats[c] = (st.st_size, st.st_mtime)
            except OSError:
                self._stats[c] = None
        return self._stats[c]

    def taille(self, chemin: str) -> Optional[int]:
        st = self.stat(chemin)
        return st[0] if st else None

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


TOLERANCE_DATE = 2.0  # secondes (les disques exFAT/FAT arrondissent les dates à 2 s)


def identique(cible: str, disque: "Disque", date_ref: Optional[float] = None,
              source: Optional[str] = None) -> Tuple[bool, str]:
    """Le fichier « cible » est-il le même fichier que celui du clip ? Validation rapide, sans lire le contenu :
    même NOM (garanti par l'appelant), même DATE de modification et, si l'original est lisible, même TAILLE.
    date_ref : la date de modification que Resolve a gardée en mémoire (marche même original hors ligne).
    Retourne (identique, preuve ou motif du refus)."""
    sc = disque.stat(cible)
    if sc is None:
        return False, "fichier cible illisible"
    ss = disque.stat(source) if source else None
    if ss is not None:
        if ss[0] != sc[0]:
            return False, f"taille différente ({nombre(ss[0])} ≠ {nombre(sc[0])} octets)"
        if abs(ss[1] - sc[1]) > TOLERANCE_DATE:
            return False, "date de modification différente"
        return True, "nom, date et taille identiques"
    if date_ref is not None:
        if abs(date_ref - sc[1]) > TOLERANCE_DATE:
            return False, "date de modification différente de celle connue par Resolve"
        return True, "nom et date identiques (original hors ligne)"
    return True, "nom identique seulement (aucune date connue)"


@dataclass(frozen=True)
class Trouve:
    chemin: str
    racine: str
    comment: str


@dataclass(frozen=True)
class Ambigu:
    candidats: Tuple[str, ...]


def chercher_ailleurs(chemin: str, racines: "Racines", dispo: Callable[[str], bool], disque: "Disque",
                      index: Index, date_ref: Optional[float]):
    """Pour un clip HORS LIGNE qui pointe hors des paires choisies : cherche un fichier de même nom ET de même
    date dans les dossiers choisis (rapides d'abord, par priorité). Sans date connue, exige en plus un dossier
    parent distinctif identique. Plusieurs fichiers différents possibles → Ambigu (on ne touche à rien)."""
    nom = os.path.basename(nfc(chemin))
    if _SEQ_PRINTF.search(nom):
        return None
    ordre = [r for r in racines.rapides + racines.lents if dispo(r)]
    cands = []
    for prio, r in enumerate(ordre):
        for c in index.candidats(r, premiere_image(nom)):
            cible = nfc(os.path.join(os.path.dirname(c), nom))
            ok, preuve = identique(cible, disque, date_ref)
            if not ok:
                continue
            if date_ref is None and score_parents(chemin, c) == 0:
                continue
            cands.append((prio, cible, r, preuve))
    if not cands:
        return None
    meilleur = min(c[0] for c in cands)
    haut = [c for c in cands if c[0] == meilleur]
    tailles = {disque.stat(c[1]) for c in haut}
    if len(haut) > 1 and (date_ref is None or len(tailles) > 1):
        return Ambigu(tuple(sorted(c[1] for c in haut)))
    _, cible, racine, preuve = sorted(haut)[0]
    return Trouve(cible, racine, "retrouvé par nom — " + preuve)


# --------------------------------------------------------------------------- décision

DEPLACER = "deplacer"          # à reconnecter vers le dossier jumeau
EN_PLACE = "en_place"          # déjà sur le bon dossier
INTROUVABLE = "introuvable"    # absent des deux dossiers de la paire
DIFFERENT = "different"        # un fichier de même nom existe, mais date ou taille différente : on ne touche à rien
AMBIGU = "ambigu"              # plusieurs fichiers possibles : on ne touche à rien
A_VERIFIER = "a_verifier"      # introuvable, mais un dossier de la paire n'est pas branché
HORS_RACINES = "hors_racines"  # en ligne, hors des paires choisies : on n'y touche pas
SANS_FICHIER = "sans_fichier"  # timeline, compound, générateur…
BLOQUE = "bloque"              # le dossier rapide principal n'est pas disponible : on ne décide rien


@dataclass(frozen=True)
class Decision:
    statut: str
    cible: str = ""
    racine_cible: str = ""
    racine_source: str = ""     # "" si le clip pointe hors des paires choisies
    comment: str = ""
    candidats: Tuple[str, ...] = ()


def decider(chemin: str, racines: Racines, etats: Dict[str, "EtatDossier"], disque: "Disque",
            index: Optional[Index] = None, date_ref: Optional[float] = None) -> Decision:
    """La règle, par paire « rapide ⇄ archive » :
    - un clip sur le dossier RAPIDE dont le fichier existe ne bouge pas ;
    - un clip sur l'ARCHIVE passe sur le rapide si le même fichier (même chemin, nom + date + taille) y est ;
    - un clip sur le rapide dont le fichier a disparu passe sur l'archive si le même fichier y est ;
    - jamais d'une paire à une autre : un mariage ne peut pas être relié à un autre tournage ;
    - un clip hors ligne hors des paires est recherché par nom + date (chercher_ailleurs) ;
    - garde-fou : si le dossier rapide principal n'est pas disponible, on ne propose RIEN."""
    index = index or Index()
    if not chemin:
        return Decision(SANS_FICHIER)
    c = nfc(chemin)
    src = racines.racine_de(c)
    dispo = lambda r: etats.get(r, EtatDossier(False)).disponible
    if not dispo(racines.principal):
        return Decision(BLOQUE)
    ici = disque.existe(c) if (src is None or dispo(src)) else False
    if src is None:
        if ici:
            return Decision(HORS_RACINES)
        t = chercher_ailleurs(c, racines, dispo, disque, index, date_ref)
        if isinstance(t, Trouve):
            return Decision(DEPLACER, t.chemin, t.racine, "", t.comment)
        if isinstance(t, Ambigu):
            return Decision(AMBIGU, candidats=t.candidats)
        return Decision(HORS_RACINES)
    paire = racines.paire_de(src)
    rel = c[len(src):]
    jumeau = paire.lent if src == paire.rapide else paire.rapide
    if src == paire.rapide and ici:
        return Decision(EN_PLACE)
    cible = jumeau + rel
    if dispo(jumeau) and disque.existe(cible):
        ok, preuve = identique(cible, disque, date_ref, c if ici else None)
        if ok:
            return Decision(DEPLACER, cible, jumeau, src, "même chemin — " + preuve)
        if not ici:
            return Decision(DIFFERENT, racine_source=src, comment=preuve, candidats=(cible,))
    if ici:
        return Decision(EN_PLACE)   # en ligne sur l'archive, pas de copie identique sur le rapide
    if not dispo(jumeau) or not dispo(src):
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
    date: Optional[float] = None   # date de modification du fichier, telle que Resolve la connaît


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
    differents: List[Tuple[Clip, str, str, str]] = field(default_factory=list)        # (clip, genre, fichier, motif)
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
        return (len(self.introuvables) + len(self.ambigus) + len(self.differents) + len(self.a_verifier) + len(self.sous_titres)
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
        d = decider(clip.chemin, racines, etats, disque, index, clip.date)
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
        elif d.statut == DIFFERENT:
            plan.differents.append((clip, "media", d.candidats[0], d.comment))
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
            elif p.statut == DIFFERENT:
                plan.differents.append((clip, "proxy", p.candidats[0], p.comment))
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


def lire_date_resolve(texte: Optional[str]) -> Optional[float]:
    """« Fri Aug  7 15:58:29 2026 » (Date Modified de Resolve) → horodatage ; None si absente ou illisible.
    Vérifié sur 9 057 clips : égale à la date de modification du fichier (±2 s) dans 9 056 cas."""
    import datetime as _dt
    t = " ".join((texte or "").split())
    for f in ("%a %b %d %H:%M:%S %Y", "%a %b %d %Y %H:%M:%S"):
        try:
            return _dt.datetime.strptime(t, f).timestamp()
        except ValueError:
            pass
    return None


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
        return (f"Le dossier rapide principal ({plan.racines.nom(plan.racines.principal)}) n'est pas disponible "
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
    if plan.differents:
        morceaux.append(f"{pluriel(len(plan.differents), 'fichier')} de même nom mais pas identique(s) (non touchés)")
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
    section("Même nom mais PAS le même fichier — date ou taille différente (non touchés) :",
            [f"{c.nom} [{genre}] — {motif} : {f}" for c, genre, f, motif in plan.differents])
    section("Plusieurs fichiers possibles (non touchés, à relier à la main) :",
            [f"{c.nom} [{genre}] — {len(cands)} candidats : " + " | ".join(cands[:3]) for c, genre, cands in plan.ambigus])
    section("Introuvables sur tous les disques choisis :",
            [f"{c.nom} [{genre}] — {c.proxy if genre == 'proxy' else c.chemin}" for c, genre in plan.introuvables])
    section("Introuvables pour l'instant (un disque choisi n'est pas branché) :", [f"{c.nom} — {c.chemin}" for c in plan.a_verifier])
    section("Sous-titres (Resolve ne permet pas de les reconnecter par script) :", [f"{c.nom} — {c.chemin}" for c in plan.sous_titres])
    section("Clips hors des disques choisis (non traités) :",
            [f"{nom_volume(vol, plan.racines)} : {pluriel(t, 'clip')}, dont {nombre(h)} hors ligne" for vol, (t, h) in sorted(plan.hors_racines.items())])
    return L
