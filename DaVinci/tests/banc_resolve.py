"""Test d'intégration sur le VRAI DaVinci Resolve (ouvert, scripting externe activé).

Crée un banc de petits médias dans un dossier temporaire, un projet jetable
« ZZ Test Reconnecteur (temporaire) », lance le moteur complet, vérifie, puis supprime le projet.
Ne touche à aucun autre projet ni à aucun média réel.

    ResolvePython tests/banc_resolve.py
"""
import os
import shutil
import subprocess
import sys
import tempfile

ICI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(ICI))
os.environ["RECONNECTEUR_DOSSIER"] = tempfile.mkdtemp(prefix="reco_cfg_")

from reconnecteur import moteur, regles, resolve_io  # noqa: E402

NOM = "ZZ Test Reconnecteur (temporaire)"


def video(chemin, teinte):
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=25:duration=1",
                    "-vf", f"hue=h={teinte}", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-y", chemin], check=True)


def construire_banc(base):
    R, L = base + "/RAPIDE/", base + "/LENT/"
    video(L + "1.Medias/T01 Tournage – été/clip_a.mp4", 0)
    video(L + "1.Medias/T01 Tournage – été/clip_x.mp4", 90)
    video(L + "1.Medias/T02 Archivé/clip_b.mp4", 180)
    video(L + "1.Medias/T03 Homonyme/clip_x.mp4", 270)
    os.makedirs(L + "1.Medias/T04 Sequence")
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=25:duration=0.2",
                    "-start_number", "1", "-y", L + "1.Medias/T04 Sequence/frame_%04d.png"], check=True)
    with open(L + "1.Medias/T01 Tournage – été/sous.srt", "w") as f:
        f.write("1\n00:00:00,000 --> 00:00:00,900\nBonjour\n")
    video(L + "Proxy/clip_a.mov", 0)
    shutil.copytree(L, R)                                   # tout existe sur les deux…
    shutil.rmtree(R + "1.Medias/T03 Homonyme")              # …sauf l'homonyme (seulement sur le lent)
    return R, L


def preparer():
    """Banc + projet de test prêts : (resolve, projet, R, L, base)."""
    base = tempfile.mkdtemp(prefix="banc_reco_")
    R, L = construire_banc(base)
    resolve = resolve_io.connecter()
    pm = resolve.GetProjectManager()
    pm.GotoRootFolder()
    courant = pm.GetCurrentProject()
    if courant and courant.GetName() == NOM:  # reste d'un essai précédent : on le ferme avant de le supprimer
        pm.CloseProject(courant)
    if NOM in (pm.GetProjectListInCurrentFolder() or []):
        assert pm.DeleteProject(NOM), "suppression de l'ancien projet de test impossible"
    projet = pm.CreateProject(NOM)
    assert projet, "création du projet de test impossible"
    mp, ms = projet.GetMediaPool(), resolve.GetMediaStorage()
    racine = mp.GetRootFolder()
    b1, b2 = mp.AddSubFolder(racine, "Bin 1"), mp.AddSubFolder(racine, "Bin 2")

    def importer(dossier, chemin):
        mp.SetCurrentFolder(dossier)
        return (ms.AddItemListToMediaPool([{"media": chemin}]) or [None])[0]

    a1 = importer(b1, L + "1.Medias/T01 Tournage – été/clip_a.mp4")
    importer(b2, L + "1.Medias/T01 Tournage – été/clip_a.mp4")          # doublon
    importer(b1, L + "1.Medias/T01 Tournage – été/clip_x.mp4")
    importer(b2, L + "1.Medias/T03 Homonyme/clip_x.mp4")
    importer(b1, L + "1.Medias/T01 Tournage – été/sous.srt")
    importer(b1, R + "1.Medias/T02 Archivé/clip_b.mp4")                  # puis on l'« archive »
    mp.SetCurrentFolder(b2)
    mp.ImportMedia([{"FilePath": L + "1.Medias/T04 Sequence/frame_%04d.png", "StartIndex": 1, "EndIndex": 5}])
    a1.LinkProxyMedia(L + "Proxy/clip_a.mov")
    os.remove(R + "1.Medias/T02 Archivé/clip_b.mp4")
    return resolve, projet, R, L, base


def nettoyer(resolve, base):
    pm = resolve.GetProjectManager()
    p = pm.GetCurrentProject()
    if p and p.GetName() == NOM:
        pm.CloseProject(p)
    pm.DeleteProject(NOM)
    shutil.rmtree(base, ignore_errors=True)


def main():
    resolve, projet, R, L, base = preparer()
    pm = resolve.GetProjectManager()
    racines = regles.Racines.depuis(R, L)
    plan = moteur.analyser(resolve, projet, racines)
    print("\n".join(regles.lignes_rapport(plan)))
    attendu_medias = 5   # clip_a ×2, clip_x (T01), séquence, clip_b
    erreurs = []
    if len(plan.medias()) != attendu_medias:
        erreurs.append(f"plan : {len(plan.medias())} médias au lieu de {attendu_medias}")
    if len(plan.proxys()) != 1 or len(plan.sous_titres) != 1:
        erreurs.append("plan : proxy ou sous-titre mal détecté")
    r = moteur.reconnecter(resolve, projet, plan)
    print("\n".join(regles.lignes_rapport(plan, r)))
    if r.erreur or r.echecs or len(r.reussis) != attendu_medias + 1 or r.non_prevus:
        erreurs.append(f"application : erreur={r.erreur!r} échecs={len(r.echecs)} réussis={len(r.reussis)} non_prévus={len(r.non_prevus)}")
    if not (r.sauvegarde and os.path.getsize(r.sauvegarde) > 0):
        erreurs.append("copie de sécurité .drp absente")
    etat = {c.nom + "|" + c.chutier: c for c in resolve_io.lire_clips(projet)}
    homo = [c for c in etat.values() if "T03 Homonyme" in c.chemin]
    if len(homo) != 1:
        erreurs.append("l'homonyme a été touché")
    plan2 = moteur.analyser(resolve, projet, racines)
    if plan2.actions:
        erreurs.append(f"2e analyse : encore {len(plan2.actions)} actions")
    nettoyer(resolve, base)
    print("\n" + ("✓ BANC RÉUSSI" if not erreurs else "✗ ÉCHECS :\n  " + "\n  ".join(erreurs)))
    return 0 if not erreurs else 1


if __name__ == "__main__":
    sys.exit(main())
