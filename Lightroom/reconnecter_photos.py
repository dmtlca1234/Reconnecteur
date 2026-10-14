#!/usr/bin/env python3
"""Reconnecte dans le catalogue Lightroom les dossiers déplacés entre le SSD 4tb et le disque 12tb.

Principe : les deux disques ont la même arborescence (1.Medias/...). Le 4tb (SSD) a la priorité :
un dossier complet sur le 4tb y est connecté ; s'il n'est plus complet sur le 4tb mais complet sur le 12tb,
il est connecté au 12tb.

- Lightroom Classic doit être fermé.
- Si le 12tb n'est pas branché (vraiment monté, pas un dossier résiduel dans /Volumes), le script
  ne fait que ramener vers le 4tb ce qui s'y trouve. Si le 4tb n'est pas monté, il ne fait rien.
- Chemins comparés en Unicode NFC ; sauvegarde par l'API SQLite (WAL inclus) ; vérification après
  coup, et restauration automatique de la sauvegarde si l'intégrité du catalogue n'est pas « ok ».
- Une sauvegarde du catalogue est faite avant chaque modification (5 dernières conservées).

Usage : python3 reconnecter_photos.py [--catalog chemin.lrcat] [--oui] [--verifier]
  --verifier : aperçu en lecture seule (fonctionne même Lightroom ouvert, sur une copie temporaire)
"""
import argparse, fcntl, glob, os, shutil, sqlite3, subprocess, sys, tempfile, unicodedata, uuid
from datetime import datetime

SSD = "/Volumes/Belvoir_DO–4tb/"
HDD = "/Volumes/Belvoir_DO_12tb/"
DOSSIER_CATALOGUES = os.path.join(SSD, "6. Lightroom", "Belvoir_2026")
GARDER_SAUVEGARDES = 5
JOURNAL = os.path.join(SSD, "6. Lightroom", "Journal Lightroom.md")


def nfc(chemin):
    return unicodedata.normalize("NFC", chemin or "")


def disque_branche(racine):
    """Vrai seulement si le volume est réellement monté : un dossier résiduel dans /Volumes
    (disque débranché) ne doit jamais passer pour le disque."""
    parties = racine.rstrip("/").split("/")
    if len(parties) >= 3 and parties[1] == "Volumes":
        return os.path.ismount("/".join(parties[:3])) and os.path.isdir(racine)
    return os.path.isdir(racine)


def catalogue_par_defaut():
    cats = glob.glob(os.path.join(DOSSIER_CATALOGUES, "*.lrcat"))
    if not cats:
        sys.exit(f"Aucun catalogue .lrcat trouvé dans {DOSSIER_CATALOGUES}")
    return max(cats, key=os.path.getmtime)


def lightroom_ouvert(cat):
    r = subprocess.run(["pgrep", "-x", "Adobe Lightroom Classic"], capture_output=True)
    return r.returncode == 0 or os.path.exists(cat + ".lock")


def sauvegarder(cat):
    dossier = os.path.join(os.path.dirname(cat), "Backups", "Avant_reconnexion")
    os.makedirs(dossier, exist_ok=True)
    nom = os.path.splitext(os.path.basename(cat))[0]
    dest = os.path.join(dossier, f"{nom}_{datetime.now():%Y-%m-%d_%H%M%S}.lrcat")
    # API de sauvegarde SQLite : copie cohérente, y compris ce qui est encore dans le journal WAL
    src, dst = sqlite3.connect(cat), sqlite3.connect(dest)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    anciennes = sorted(glob.glob(os.path.join(dossier, f"{nom}_*.lrcat")))
    for vieille in anciennes[:-GARDER_SAUVEGARDES]:
        os.remove(vieille)
    return dest


def racine(cur, chemin, compteur):
    """Retourne l'id du dossier racine pour ce disque, en le créant au besoin."""
    for rid, absolu in cur.execute("select id_local, absolutePath from AgLibraryRootFolder").fetchall():
        if nfc(absolu) == nfc(chemin):
            return rid, compteur
    compteur += 1
    nom = os.path.basename(chemin.rstrip("/"))
    cur.execute("insert into AgLibraryRootFolder(id_local,id_global,absolutePath,name,relativePathFromCatalog) "
                "values(?,?,?,?,NULL)", (compteur, str(uuid.uuid4()).upper(), chemin, nom))
    return compteur, compteur


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", default=None)
    ap.add_argument("--oui", action="store_true", help="appliquer sans demander confirmation")
    ap.add_argument("--verifier", action="store_true", help="aperçu seulement, aucune modification")
    args = ap.parse_args()
    cat = args.catalog or catalogue_par_defaut()
    print(f"Catalogue : {os.path.basename(cat)}\n")

    # Une seule exécution à la fois (plugin + lancement manuel)
    verrou = open(os.path.join(tempfile.gettempdir(), "reconnecter_photos.lock"), "w")
    fcntl.flock(verrou, fcntl.LOCK_EX)

    if args.verifier:
        # Lightroom garde le catalogue verrouillé : on lit une copie temporaire
        tmp = tempfile.mkdtemp(prefix="lrverif_")
        for ext in ("", "-wal"):
            if os.path.exists(cat + ext):
                shutil.copy2(cat + ext, os.path.join(tmp, "c.lrcat" + ext))
        cat = os.path.join(tmp, "c.lrcat")

    if not disque_branche(SSD):
        sys.exit("Le disque Belvoir_DO–4tb n'est pas monté sous son nom habituel : aucune modification.")
    hdd_branche = disque_branche(HDD)
    if not hdd_branche:
        print("Le 12tb n'est pas branché : on ne fait que ramener sur le 4tb ce qui s'y trouve.\n")
    if args.catalog is None and not args.verifier and lightroom_ouvert(cat):
        sys.exit("Lightroom Classic est ouvert. Ferme-le (Cmd+Q) puis relance le script.")

    db = sqlite3.connect(cat)
    cur = db.cursor()
    racines = {rid: nfc(chemin) for rid, chemin in cur.execute("select id_local, absolutePath from AgLibraryRootFolder")}

    # Règle : le 4tb (SSD) en priorité ; le 12tb seulement si le dossier n'est plus complet sur le 4tb.
    a_deplacer, problemes = [], []
    for fid, rid, rel in cur.execute("select id_local, rootFolder, pathFromRoot from AgLibraryFolder").fetchall():
        base = racines.get(rid)
        if base not in (SSD, HDD):
            continue
        fichiers = [f"{b}.{e}" for b, e in cur.execute(
            "select baseName, extension from AgLibraryFile where folder=?", (fid,))]

        def manquants(disque):
            if not os.path.isdir(disque + rel):
                return fichiers or [None]
            return [f for f in fichiers if not os.path.exists(disque + rel + f)]

        if not manquants(SSD):
            cible = SSD
        elif hdd_branche and not manquants(HDD):
            cible = HDD
        else:
            if hdd_branche:
                m = manquants(base)
                problemes.append(f"{len(m)}/{len(fichiers)} photos introuvables sur les deux disques : {rel or '(racine)'}")
            continue
        if cible != base:
            a_deplacer.append((fid, rel, base, cible, len(fichiers)))  # rel vide = racine du disque

    if not a_deplacer:
        print("Aucun dossier à reconnecter.")
    else:
        print("Dossiers à reconnecter :")
        for _, rel, base, cible, n in a_deplacer:
            print(f"  {n:5d} photos  {rel or '(racine)'}  ({os.path.basename(base.rstrip('/'))} → {os.path.basename(cible.rstrip('/'))})")
    if problemes:
        print("\nÀ régler à la main dans Lightroom (clic droit → Rechercher le dossier manquant) :")
        for p in problemes:
            print("  - " + p)
    if args.verifier:
        shutil.rmtree(os.path.dirname(cat), ignore_errors=True)
        if a_deplacer:
            print("\n(Aperçu seulement : ce sera appliqué à la fermeture de Lightroom.)")
        return
    if not a_deplacer:
        return

    if not args.oui and input("\nAppliquer ? (o/n) ").strip().lower() not in ("o", "oui", "y"):
        print("Annulé, aucune modification.")
        return

    sauvegarde = sauvegarder(cat)
    print(f"\nSauvegarde : {sauvegarde}")
    cur.execute("BEGIN")
    compteur = int(float(cur.execute(
        "select value from Adobe_variablesTable where name='Adobe_entityIDCounter'").fetchone()[0]))
    ids = {}
    for chemin in (SSD, HDD):
        ids[chemin], compteur = racine(cur, chemin, compteur)
    faits, journal = 0, []
    for fid, rel, base, cible, n in a_deplacer:
        if cur.execute("select 1 from AgLibraryFolder where rootFolder=? and pathFromRoot=?",
                       (ids[cible], rel)).fetchone():
            print(f"  ignoré (déjà présent dans le catalogue sur {cible}) : {rel}")
            continue
        cur.execute("update AgLibraryFolder set rootFolder=? where id_local=?", (ids[cible], fid))
        faits += 1
        journal.append(f"- {rel or '(racine)'} — {n} photos ({os.path.basename(base.rstrip('/'))} → {os.path.basename(cible.rstrip('/'))})")
    cur.execute("update Adobe_variablesTable set value=? where name='Adobe_entityIDCounter'",
                (float(compteur + 100),))
    db.commit()
    ok = cur.execute("pragma integrity_check").fetchone()[0]
    # vérification : chaque dossier prévu pointe bien vers sa cible
    rates = [rel for fid, rel, base, cible, n in a_deplacer
             if cur.execute("select rootFolder from AgLibraryFolder where id_local=?", (fid,)).fetchone()[0] != ids[cible]]
    db.close()
    if ok != "ok":
        shutil.copy2(sauvegarde, cat)
        for ext in ("-wal", "-shm"):
            if os.path.exists(cat + ext):
                os.remove(cat + ext)
        sys.exit(f"⚠ Intégrité du catalogue : {ok}. Le catalogue d'avant a été RESTAURÉ ({sauvegarde}). Aucune modification.")
    print(f"\n{faits} dossier(s) reconnecté(s). Intégrité du catalogue : {ok}")
    if rates:
        print(f"⚠ {len(rates)} dossier(s) non reconnecté(s) (déjà présents sur l'autre disque) : " + ", ".join(r or "(racine)" for r in rates))
    if args.catalog is None:
        try:
            with open(JOURNAL, "a", encoding="utf-8") as j:
                j.write(f"\n### {datetime.now():%Y-%m-%d %H:%M} — {faits} dossier(s) reconnecté(s)\n"
                        f"Catalogue : `{os.path.basename(cat)}` · intégrité : {ok} · sauvegarde : `{os.path.basename(sauvegarde)}`\n\n")
                j.write("\n".join(journal) + "\n")
                if rates:
                    j.write("\nNon reconnectés (déjà présents sur l'autre disque) :\n" + "\n".join("- " + (r or "(racine)") for r in rates) + "\n")
                if problemes:
                    j.write("\nÀ régler à la main :\n" + "\n".join("- " + p for p in problemes) + "\n")
            print(f"Journal mis à jour : {JOURNAL}")
        except OSError as e:
            print(f"⚠ Journal NON écrit ({e}) : garde ce résumé.")


if __name__ == "__main__":
    main()
