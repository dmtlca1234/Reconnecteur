"""Faux DaVinci Resolve, fidèle aux comportements mesurés sur Resolve 21.1 (banc d'essai du 2026-10-09) :
- RelinkClips(objets, dossier) ne reconnecte que les objets passés, si le fichier existe dans le dossier ;
- les sous-titres sont refusés ;
- LinkProxyMedia relie le proxy si le fichier existe ;
- les uid sont stables."""
import datetime
import itertools
import os

_ids = itertools.count(1)


def date_resolve(chemin):
    """Date Modified au format de Resolve (« Fri Aug  7 15:58:29 2026 »), comme Resolve la mémorise à l'import."""
    try:
        return datetime.datetime.fromtimestamp(os.stat(chemin).st_mtime).strftime("%a %b %e %H:%M:%S %Y")
    except OSError:
        return ""


class Clip:
    def __init__(self, chemin, type_="Video + Audio", proxy=""):
        self.uid = f"uid-{next(_ids):04d}"
        self.props = {"File Path": chemin, "Proxy Media Path": proxy, "Type": type_,
                      "Clip Name": os.path.basename(chemin), "Date Modified": date_resolve(chemin)}

    def GetUniqueId(self):
        return self.uid

    def GetClipProperty(self, cle=None):
        return dict(self.props) if cle is None else self.props.get(cle, "")

    def LinkProxyMedia(self, chemin):
        if os.path.exists(chemin):
            self.props["Proxy Media Path"] = chemin
            return True
        return False


class Dossier:
    def __init__(self, nom, clips=(), sous=()):
        self.nom, self.clips, self.sous = nom, list(clips), list(sous)

    def GetName(self):
        return self.nom

    def GetClipList(self):
        return list(self.clips)

    def GetSubFolderList(self):
        return list(self.sous)


class MediaPool:
    def __init__(self, racine, refuse_tout=False):
        self.racine, self.refuse_tout, self.appels = racine, refuse_tout, []

    def GetRootFolder(self):
        return self.racine

    def RelinkClips(self, objets, dossier):
        self.appels.append((len(objets), dossier))
        if self.refuse_tout:
            return False
        ok = True
        for c in objets:
            nouveau = os.path.join(dossier.rstrip("/"), os.path.basename(c.props["File Path"]))
            if c.props["Type"] != "Subtitle" and os.path.exists(nouveau):
                c.props["File Path"] = nouveau
            else:
                ok = False
        return ok


class Projet:
    def __init__(self, nom, racine, **kw):
        self.nom, self.mp = nom, MediaPool(racine, **kw)

    def GetName(self):
        return self.nom

    def GetUniqueId(self):
        return "projet-" + self.nom

    def GetMediaPool(self):
        return self.mp


class ProjectManager:
    def __init__(self, projet):
        self.projet, self.exports, self.sauves = projet, [], 0

    def GetCurrentProject(self):
        return self.projet

    def ExportProject(self, nom, chemin, avec_stills=True):
        with open(chemin, "w") as f:
            f.write("drp factice")
        self.exports.append(chemin)
        return True

    def SaveProject(self):
        self.sauves += 1
        return True


class Resolve:
    def __init__(self, projet):
        self.pm = ProjectManager(projet)

    def GetProjectManager(self):
        return self.pm
