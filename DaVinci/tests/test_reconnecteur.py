"""Tests du Reconnecteur (hors Resolve). Lancer depuis le dossier DaVinci :
    python3 -m unittest discover -s tests -v
"""
import os
import shutil
import sys
import tempfile
import time
import unicodedata
import unittest

ICI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(ICI))
os.environ["RECONNECTEUR_DOSSIER"] = tempfile.mkdtemp(prefix="reco_cfg_")

from reconnecteur import config, moteur, regles  # noqa: E402
from reconnecteur.regles import Clip, Disque, EtatDossier, Index, Racines  # noqa: E402

import faux_resolve as fr  # noqa: E402

OK = EtatDossier(True)
ABSENT = EtatDossier(False, "disque non branché")
JADIS = time.time() - 86400 * 30   # une date de tournage


def creer(chemin, contenu="x", date=JADIS):
    """Crée un fichier avec une date de modification fixe (une copie garde la date de l'original)."""
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    with open(chemin, "w") as f:
        f.write(contenu)
    os.utime(chemin, (date, date))


class Banc(unittest.TestCase):
    """Deux paires dans un dossier temporaire (hors /Volumes : toujours disponibles) :
    Rapide ⇄ Lent (rangement 1.Medias) et Backup ⇄ Lent2 (le miroir d'un disque de mariage)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="reco_")
        self.R, self.L = os.path.join(self.tmp, "Rapide") + "/", os.path.join(self.tmp, "Lent") + "/"
        self.B, self.L2 = os.path.join(self.tmp, "Backup") + "/", os.path.join(self.tmp, "Lent2") + "/"
        for d in (self.R, self.L, self.B, self.L2):
            os.makedirs(d)
        self.racines = Racines.depuis([(self.R, self.L)])
        self.racines2 = Racines.depuis([(self.R, self.L), (self.B, self.L2)])

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def deux(self, rel, contenu="x"):
        creer(self.R + rel, contenu)
        creer(self.L + rel, contenu)

    def etats(self, racines, **absents):
        noms = {"R": self.R, "L": self.L, "B": self.B, "L2": self.L2}
        absents_ = {regles.racine_normalisee(noms[k]) for k, v in absents.items() if v}
        return {r: (ABSENT if r in absents_ else OK) for r in racines.toutes}

    def d(self, chemin, racines=None, date=None, **absents):
        racines = racines or self.racines
        return regles.decider(chemin, racines, self.etats(racines, **absents), Disque(), Index(), date)


class TestDecision(Banc):
    def test_table_de_verite(self):
        self.deux("1.Medias/A/a.mp4")
        creer(self.L + "1.Medias/B/b.mp4")             # archivé
        creer(self.R + "1.Medias/C/c.mp4")             # récent, pas encore archivé
        cas = [
            (self.L + "1.Medias/A/a.mp4", {}, regles.DEPLACER, self.R),            # sur l'archive, existe sur le rapide
            (self.R + "1.Medias/A/a.mp4", {}, regles.EN_PLACE, None),
            (self.R + "1.Medias/B/b.mp4", {}, regles.DEPLACER, self.L),            # effacé du rapide
            (self.L + "1.Medias/B/b.mp4", {}, regles.EN_PLACE, None),
            (self.R + "1.Medias/C/c.mp4", {"L": True}, regles.EN_PLACE, None),
            (self.L + "1.Medias/C/c.mp4", {"L": True}, regles.DEPLACER, self.R),   # archive débranchée : retour rapide OK
            (self.R + "1.Medias/B/b.mp4", {"L": True}, regles.A_VERIFIER, None),   # archive débranchée : on ne sait pas
            (self.R + "1.Medias/Z/z.mp4", {}, regles.INTROUVABLE, None),
            (self.L + "1.Medias/A/a.mp4", {"R": True}, regles.BLOQUE, None),       # rapide principal absent : RIEN
            ("/Volumes/Autre/x.mp4", {}, regles.HORS_RACINES, None),
            ("", {}, regles.SANS_FICHIER, None),
        ]
        for chemin, absents, statut, vers in cas:
            with self.subTest(chemin=chemin, absents=absents):
                d = self.d(chemin, **absents)
                self.assertEqual(d.statut, statut)
                if vers:
                    self.assertTrue(d.cible.startswith(regles.nfc(vers)))
                    self.assertTrue(d.comment.startswith("même chemin"))

    def test_nfd_et_nfc(self):
        self.deux("Tournage – été/a.mp4")
        d = self.d(unicodedata.normalize("NFD", self.L + "Tournage – été/a.mp4"))
        self.assertEqual(d.statut, regles.DEPLACER)
        self.assertEqual(d.cible, regles.nfc(self.R + "Tournage – été/a.mp4"))

    def test_sequences(self):
        for i in range(12, 15):
            self.deux(f"seq/DJI_{i:04d}.DNG")
        self.assertEqual(self.d(self.L + "seq/DJI_[0012-0014].DNG").statut, regles.DEPLACER)
        self.assertEqual(self.d(self.L + "seq/DJI_%04d.DNG").statut, regles.DEPLACER)
        self.assertEqual(self.d(self.L + "seq/DJI_[0099-0100].DNG").statut, regles.INTROUVABLE)

    def test_cache_un_listdir_par_dossier(self):
        for i in range(50):
            creer(self.R + f"d/f{i}.mp4")
        appels = []

        def listdir(d):
            appels.append(d)
            return os.listdir(d)
        disque = Disque(listdir=listdir)
        for i in range(50):
            self.assertTrue(disque.existe(self.R + f"d/f{i}.mp4"))
        self.assertEqual(len(appels), 1)


class TestIdentite(Banc):
    """Validation rapide « même fichier » : nom + date + taille, sans lire le contenu."""

    def test_taille_differente_jamais_reliee(self):
        creer(self.L + "1.Medias/T/a.mp4", "original")
        creer(self.R + "1.Medias/T/a.mp4", "autre version plus longue")
        d = self.d(self.L + "1.Medias/T/a.mp4")
        self.assertEqual(d.statut, regles.EN_PLACE)   # en ligne sur l'archive : on ne touche à rien

    def test_date_differente_jamais_reliee(self):
        creer(self.L + "1.Medias/T/a.mp4", "pareil", date=JADIS)
        creer(self.R + "1.Medias/T/a.mp4", "pareil", date=JADIS + 3600)
        self.assertEqual(self.d(self.L + "1.Medias/T/a.mp4").statut, regles.EN_PLACE)

    def test_original_hors_ligne_valide_par_la_date_de_resolve(self):
        creer(self.L + "1.Medias/T/b.mp4", date=JADIS)
        bonne = self.d(self.R + "1.Medias/T/b.mp4", date=JADIS)
        self.assertEqual(bonne.statut, regles.DEPLACER)
        self.assertIn("nom et date identiques", bonne.comment)
        mauvaise = self.d(self.R + "1.Medias/T/b.mp4", date=JADIS - 86400)
        self.assertEqual(mauvaise.statut, regles.DIFFERENT)

    def test_tolerance_deux_secondes_exfat(self):
        creer(self.L + "1.Medias/T/c.mp4", date=JADIS + 1.5)
        self.assertEqual(self.d(self.R + "1.Medias/T/c.mp4", date=JADIS).statut, regles.DEPLACER)

    def test_preuve_complete_quand_les_deux_sont_lisibles(self):
        self.deux("1.Medias/T/d.mp4")
        self.assertIn("nom, date et taille identiques", self.d(self.L + "1.Medias/T/d.mp4").comment)


class TestPaires(Banc):
    """Le cas réel : le disque Backup Mariage est le miroir de Lent2 (« 1B. Mariage »), mais contient AUSSI des
    copies de tournages qui ne sont pas des mariages. Ils ne doivent jamais y être reliés."""

    def test_un_clip_ne_change_jamais_de_paire(self):
        creer(self.L + "1.Medias/00016. Visite/130_1328.MXF")
        creer(self.B + "1.Medias/00016. Visite/130_1328.MXF")            # copie parasite sur le Backup
        creer(self.B + "MEDIAS DE 12tb/00016. Visite/130_1328.MXF")       # idem, rangée autrement
        d = self.d(self.L + "1.Medias/00016. Visite/130_1328.MXF", self.racines2)
        self.assertEqual(d.statut, regles.EN_PLACE)                      # reste sur son archive, pas de Backup

    def test_miroir_mariage_relie_au_backup(self):
        creer(self.L2 + "1. MEDIAS/A001/C0007.MP4")
        creer(self.B + "1. MEDIAS/A001/C0007.MP4")
        d = self.d(self.L2 + "1. MEDIAS/A001/C0007.MP4", self.racines2)
        self.assertEqual(d.statut, regles.DEPLACER)
        self.assertEqual(d.racine_cible, regles.nfc(self.B))

    def test_backup_debranche_reste_sur_son_miroir(self):
        creer(self.L2 + "1. MEDIAS/A001/C0007.MP4")
        d = self.d(self.B + "1. MEDIAS/A001/C0007.MP4", self.racines2, date=JADIS, B=True)
        self.assertEqual(d.statut, regles.DEPLACER)
        self.assertEqual(d.racine_cible, regles.nfc(self.L2))

    def test_clip_hors_ligne_hors_paires_retrouve_par_nom_et_date(self):
        creer(self.R + "1.Medias/00038. Mariage/A001/C0042.MP4", date=JADIS)
        d = self.d("/Volumes/Disque Oublié/Mariage/A001/C0042.MP4", date=JADIS)
        self.assertEqual(d.statut, regles.DEPLACER)
        self.assertIn("retrouvé par nom", d.comment)
        self.assertEqual(self.d("/Volumes/Disque Oublié/Mariage/A001/C0042.MP4", date=JADIS - 99).statut,
                         regles.HORS_RACINES)

    def test_hors_paires_sans_date_exige_un_dossier_distinctif(self):
        creer(self.R + "1.Medias/T1/DCIM/100MSDCF/DSC0001.ARW")
        self.assertEqual(self.d("/Volumes/X/T9/DCIM/100MSDCF/DSC0001.ARW").statut, regles.HORS_RACINES)
        self.assertEqual(self.d("/Volumes/X/T1/DCIM/100MSDCF/DSC0001.ARW").statut, regles.DEPLACER)

    def test_hors_paires_deux_fichiers_differents_ambigu(self):
        creer(self.R + "1.Medias/T1/C0001.MP4", "aaaa", date=JADIS)
        creer(self.R + "1.Medias/T2/C0001.MP4", "bb", date=JADIS)
        self.assertEqual(self.d("/Volumes/X/T9/C0001.MP4", date=JADIS).statut, regles.AMBIGU)

    def test_priorite_entre_paires_hors_paires(self):
        creer(self.R + "1.Medias/T1/x.mp4", date=JADIS)
        creer(self.B + "autre/T1/x.mp4", date=JADIS)
        d = self.d("/Volumes/X/T1/x.mp4", self.racines2, date=JADIS)
        self.assertEqual(d.racine_cible, regles.nfc(self.R))

    def test_index_ignore_bundles_et_caches(self):
        creer(self.L + "Catalogue.lrdata/x/C0001.MP4")
        creer(self.L + ".Trashes/C0001.MP4")
        creer(self.L + "1.Medias/T1/C0001.MP4")
        self.assertEqual(Index().candidats(regles.racine_normalisee(self.L), "c0001.mp4"),
                         [regles.nfc(self.L + "1.Medias/T1/C0001.MP4")])


class TestConfigEtNoms(unittest.TestCase):
    def test_paires_invalides(self):
        self.assertIsNotNone(Racines.depuis([("/a/b", "/a/b/")]).probleme())
        self.assertIsNotNone(Racines.depuis([("/a/b", "/a/b/c")]).probleme())
        self.assertIsNotNone(Racines.depuis([]).probleme())
        self.assertIsNone(Racines.depuis([("/a/b", "/a/c"), ("/d", "/e")]).probleme())
        self.assertIsNone(Racines.depuis([("/Volumes/X", "/Volumes/X 2")]).probleme())

    def test_noms(self):
        r = Racines.depuis([("/Volumes/Belvoir_DO–4tb/1.Medias", "/Volumes/Belvoir_DO_12tb/1.Medias"),
                            ("/Volumes/Backup Mariage", "/Volumes/Belvoir_DO_12tb/1B. Mariage")])
        self.assertEqual(r.nom(r.rapides[0]), "Belvoir_DO–4tb")
        self.assertEqual(r.nom(r.lents[1]), "Belvoir_DO_12tb › 1B. Mariage")
        self.assertEqual(r.paire_de(r.lents[1]).rapide, r.rapides[1])
        self.assertEqual(regles.nom_volume("/Volumes/Belvoir_DO_12tb", r), "Belvoir_DO_12tb, hors des dossiers choisis")
        self.assertEqual(regles.nom_volume("/"), "Disque du Mac")

    def test_dossier_residuel_dans_volumes(self):
        e = regles.etat_dossier("/Volumes/Disque/", ismount=lambda p: False, isdir=lambda p: True)
        self.assertFalse(e.disponible)
        self.assertIn("résiduel", e.raison)

    def test_date_resolve(self):
        self.assertIsNotNone(regles.lire_date_resolve("Fri Aug  7 15:58:29 2026"))
        self.assertIsNotNone(regles.lire_date_resolve("Mon Sep 28 2020 15:38:05"))
        self.assertIsNone(regles.lire_date_resolve(""))
        self.assertIsNone(regles.lire_date_resolve(None))

    def test_textes(self):
        self.assertEqual(regles.pluriel(1, "clip"), "1 clip")
        self.assertEqual(regles.pluriel(7518, "clip"), "7 518 clips")
        self.assertEqual(regles.nom_court("/V/1. MEDIAS/A001"), "1. MEDIAS/A001")

    def test_reprise_des_anciennes_configurations(self):
        for contenu, attendu in [
            ('{"rapide": "/A/", "lent": "/B/"}', [{"rapide": "/A/", "lent": "/B/"}]),
            ('{"rapides": ["/A/", "/C/"], "lents": ["/B/", "/D/"]}',
             [{"rapide": "/A/", "lent": "/B/"}, {"rapide": "/C/", "lent": "/D/"}]),
        ]:
            with open(config.CONFIG, "w") as f:
                f.write(contenu)
            self.assertEqual(config.charger()["paires"], attendu)
        os.remove(config.CONFIG)


class TestPlan(Banc):
    def plan(self, clips, racines=None, **absents):
        racines = racines or self.racines
        return regles.construire_plan(clips, racines, self.etats(racines, **absents), Disque(), Index())

    def test_groupes_doublons_sous_titres_proxys(self):
        for t in ("T1", "T2", "T3", "T4"):
            self.deux(f"1.Medias/{t}/a.mp4")
        self.deux("1.Medias/T1/s.srt")
        self.deux("Proxy/a.mov")
        clips = [
            Clip("u1", "Bin1", "a", "Video", self.L + "1.Medias/T1/a.mp4", self.L + "Proxy/a.mov"),
            Clip("u2", "Bin2", "a", "Video", self.L + "1.Medias/T1/a.mp4"),      # doublon
            Clip("u3", "Bin1", "s", "Subtitle", self.L + "1.Medias/T1/s.srt"),
            Clip("u4", "Bin1", "t", "Timeline", ""),
            Clip("u5", "Bin1", "x", "Video", "/Volumes/Inexistant/x.mp4"),
        ] + [Clip(f"v{t}", "B", "a", "Video", self.L + f"1.Medias/{t}/a.mp4") for t in ("T2", "T3", "T4")]
        p = self.plan(clips)
        self.assertEqual([regles.nom_court(g) for g in p.groupes()], ["T1", "T2", "T3", "T4", "Proxy"])
        self.assertTrue(all(a.doublon for a in p.medias() if a.uid in ("u1", "u2")))
        self.assertEqual(len(p.proxys()), 1)
        self.assertEqual(len(p.sous_titres), 1)
        self.assertEqual(p.sans_fichier, 1)
        self.assertEqual(p.hors_racines["/Volumes/Inexistant"], [1, 1])

    def test_differents_signales(self):
        creer(self.L + "1.Medias/T/b.mp4", date=JADIS)
        p = self.plan([Clip("u1", "B", "b", "Video", self.R + "1.Medias/T/b.mp4", date=JADIS - 86400)])
        self.assertEqual(len(p.differents), 1)
        self.assertEqual(p.actions, [])
        self.assertIn("pas identique", regles.resume_plan(p))
        self.assertIn("PAS le même fichier", "\n".join(regles.lignes_rapport(p)))

    def test_rien_a_faire_ne_cache_pas_les_problemes(self):
        p = self.plan([Clip("u1", "B", "z", "Video", self.R + "absent.mp4")])
        self.assertIn("Rien à reconnecter", regles.resume_plan(p))
        self.assertIn("introuvable", regles.resume_plan(p))

    def test_rapport_sans_troncature_silencieuse(self):
        p = self.plan([Clip(f"u{i}", "B", f"z{i}", "Video", self.R + f"absent{i}.mp4") for i in range(60)])
        self.assertIn("… et 20 autres", "\n".join(regles.lignes_rapport(p, limite=40)))

    def test_trajets_deux_paires(self):
        self.deux("1.Medias/00038/a.mp4")
        creer(self.L2 + "1. MEDIAS/A001/c.mp4")
        creer(self.B + "1. MEDIAS/A001/c.mp4")
        clips = [Clip("u1", "B", "a", "Video", self.L + "1.Medias/00038/a.mp4"),
                 Clip("u2", "B", "c", "Video", self.L2 + "1. MEDIAS/A001/c.mp4")]
        p = self.plan(clips, self.racines2)
        self.assertEqual(regles.bilan_directions(p.racines, p.actions),
                         ["⚡ 1 clip : Lent ⟶ Rapide", "⚡ 1 clip : Lent2 ⟶ Backup"])
        rapport = "\n".join(regles.lignes_rapport(p))
        self.assertIn("Aucun fichier n'est copié, déplacé ni effacé", rapport)


class TestMoteurAvecFauxResolve(Banc):
    def monter(self, **kw):
        self.deux("1.Medias/T1/a.mp4")
        self.deux("1.Medias/T1/b.mp4")
        creer(self.L + "1.Medias/T2/c.mp4")              # archivé
        creer(self.L + "1.Medias/T3/b.mp4")              # homonyme dans un autre tournage
        self.deux("1.Medias/T1/s.srt")
        self.deux("Proxy/a.mov")
        creer(self.R + "1.Medias/T2/c.mp4")              # présent à l'import…
        self.a1 = fr.Clip(self.L + "1.Medias/T1/a.mp4", proxy=self.L + "Proxy/a.mov")
        self.a2 = fr.Clip(self.L + "1.Medias/T1/a.mp4")   # doublon dans un autre chutier
        self.b = fr.Clip(self.L + "1.Medias/T1/b.mp4")
        self.c = fr.Clip(self.R + "1.Medias/T2/c.mp4")
        os.remove(self.R + "1.Medias/T2/c.mp4")          # …puis effacé du rapide (archivé)
        self.homo = fr.Clip(self.L + "1.Medias/T3/b.mp4")
        self.srt = fr.Clip(self.L + "1.Medias/T1/s.srt", type_="Subtitle")
        racine = fr.Dossier("Master", [self.b], [fr.Dossier("Bin1", [self.a1, self.srt, self.c]),
                                                 fr.Dossier("Bin2", [self.a2, self.homo])])
        self.projet = fr.Projet("Test", racine, **kw)
        self.resolve = fr.Resolve(self.projet)

    def test_bout_en_bout(self):
        self.monter()
        plan = moteur.analyser(self.resolve, self.projet, self.racines)
        self.assertEqual({a.uid for a in plan.medias()}, {self.a1.uid, self.a2.uid, self.b.uid, self.c.uid})
        r = moteur.reconnecter(self.resolve, self.projet, plan)
        self.assertEqual((r.erreur, len(r.echecs), len(r.reussis)), ("", 0, 5))
        self.assertTrue(self.a2.props["File Path"].startswith(regles.nfc(self.R)))
        self.assertTrue(self.c.props["File Path"].startswith(regles.nfc(self.L)))
        self.assertTrue(self.a1.props["Proxy Media Path"].startswith(regles.nfc(self.R)))
        self.assertTrue(self.homo.props["File Path"].startswith(regles.nfc(self.L)))  # homonyme intact
        self.assertEqual(r.non_prevus, [])
        self.assertTrue(r.enregistre)
        self.assertTrue(os.path.exists(r.sauvegarde))
        self.assertTrue(moteur.journaliser("Test", plan, r)[0])
        plan2 = moteur.analyser(self.resolve, self.projet, self.racines)
        self.assertEqual(plan2.actions, [])
        self.assertEqual(len(plan2.sous_titres), 1)

    def test_refus_de_resolve_compte_en_echec(self):
        self.monter(refuse_tout=True)
        plan = moteur.analyser(self.resolve, self.projet, self.racines)
        r = moteur.reconnecter(self.resolve, self.projet, plan)
        self.assertEqual(len([1 for a, _ in r.echecs if a.genre == "media"]), 4)
        self.assertFalse(r.tout_bon)

    def test_change_depuis_analyse(self):
        self.monter()
        plan = moteur.analyser(self.resolve, self.projet, self.racines)
        self.b.props["File Path"] = "/ailleurs/b.mp4"
        r = moteur.reconnecter(self.resolve, self.projet, plan)
        self.assertEqual([a.uid for a, _ in r.ignores], [self.b.uid])
        self.assertEqual(self.b.props["File Path"], "/ailleurs/b.mp4")

    def test_selection_partielle(self):
        self.monter()
        plan = moteur.analyser(self.resolve, self.projet, self.racines)
        t1 = [g for g in plan.groupes() if g.endswith("T1")]
        r = moteur.reconnecter(self.resolve, self.projet, plan, t1)
        self.assertTrue(self.c.props["File Path"].startswith(regles.nfc(self.R)))  # T2 non coché : intact
        self.assertTrue(all(a.groupe in t1 for a in r.reussis))

    def test_dossier_cible_disparu_avant_application(self):
        self.monter()
        plan = moteur.analyser(self.resolve, self.projet, self.racines)
        shutil.rmtree(self.R)
        r = moteur.reconnecter(self.resolve, self.projet, plan)
        self.assertIn("n'est plus disponible", r.erreur)
        self.assertEqual(self.a1.props["File Path"], regles.nfc(self.L + "1.Medias/T1/a.mp4"))

    def test_verrou(self):
        self.monter()
        plan = moteur.analyser(self.resolve, self.projet, self.racines)
        with config.verrou():
            r = moteur.reconnecter(self.resolve, self.projet, plan)
        self.assertIn("déjà en cours", r.erreur)


class TestAucunFichierEfface(Banc):
    """Garantie demandée : le Reconnecteur ne copie, ne déplace et n'efface AUCUN fichier."""

    INTERDITS = ("os.remove", "os.unlink", "os.rmdir", "os.removedirs", "os.rename", "os.renames",
                 "shutil.rmtree", "shutil.move", "shutil.copy", "send2trash", ".unlink(", ".rmdir(", "rm -", "mv ")

    def test_aucun_appel_destructeur_dans_le_code(self):
        pkg = os.path.join(os.path.dirname(ICI), "reconnecteur")
        fautifs = []
        for nom in sorted(os.listdir(pkg)):
            if nom.endswith(".py"):
                with open(os.path.join(pkg, nom), encoding="utf-8") as f:
                    for n, ligne in enumerate(f, 1):
                        if any(x in ligne.split("#")[0] for x in self.INTERDITS):
                            fautifs.append(f"{nom}:{n}: {ligne.strip()}")
        self.assertEqual(fautifs, [], "appel capable d'effacer, déplacer ou copier un fichier")

    def test_tous_les_disques_identiques_apres_reconnexion(self):
        def inventaire():
            res = {}
            for racine in (self.R, self.L, self.B, self.L2):
                for d, _, fichiers in os.walk(racine):
                    for f in fichiers:
                        st = os.stat(os.path.join(d, f))
                        res[os.path.join(d, f)] = (st.st_size, st.st_mtime_ns)
            return res
        TestMoteurAvecFauxResolve.monter(self)
        avant = inventaire()
        plan = moteur.analyser(self.resolve, self.projet, self.racines2)
        r = moteur.reconnecter(self.resolve, self.projet, plan)
        self.assertTrue(r.reussis)
        self.assertEqual(inventaire(), avant, "un fichier média a été modifié, déplacé ou effacé")

    def test_copies_de_securite_toutes_conservees(self):
        TestMoteurAvecFauxResolve.monter(self)
        ancien = self.b.props["File Path"]
        avant = set(os.listdir(config.SAUVEGARDES)) if os.path.isdir(config.SAUVEGARDES) else set()
        for tour in range(12):
            self.b.props["File Path"] = ancien
            r = moteur.reconnecter(self.resolve, self.projet, moteur.analyser(self.resolve, self.projet, self.racines))
            self.assertTrue(r.sauvegarde, f"tour {tour} : pas de copie de sécurité")
            time.sleep(1.01)
        self.assertEqual(len(set(os.listdir(config.SAUVEGARDES)) - avant), 12, "une copie de sécurité a été effacée")


if __name__ == "__main__":
    unittest.main()
