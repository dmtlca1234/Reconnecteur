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


def creer(chemin, contenu="x"):
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    with open(chemin, "w") as f:
        f.write(contenu)


class Banc(unittest.TestCase):
    """Trois « disques » dans un dossier temporaire (pas sous /Volumes : toujours disponibles) :
    Rapide (structure 1.Medias), Rapide2 (rangement différent : « 1. MEDIAS ») et Lent."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="reco_")
        self.R = os.path.join(self.tmp, "Rapide") + "/"
        self.R2 = os.path.join(self.tmp, "Rapide2") + "/"
        self.L = os.path.join(self.tmp, "Lent") + "/"
        for d in (self.R, self.R2, self.L):
            os.makedirs(d)
        self.racines = Racines.depuis([self.R], [self.L])
        self.racines3 = Racines.depuis([self.R, self.R2], [self.L])

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def deux(self, rel):
        creer(self.R + rel)
        creer(self.L + rel)

    def etats(self, racines, **absents):
        noms = {"R": self.R, "R2": self.R2, "L": self.L}
        absents_ = {regles.racine_normalisee(noms[k]) for k, v in absents.items() if v}
        return {r: (ABSENT if r in absents_ else OK) for r in racines.toutes}

    def d(self, chemin, racines=None, **absents):
        racines = racines or self.racines
        return regles.decider(chemin, racines, self.etats(racines, **absents), Disque(), Index())


class TestDecision(Banc):
    def test_table_de_verite_deux_disques(self):
        self.deux("1.Medias/A/a.mp4")
        creer(self.L + "1.Medias/B/b.mp4")             # archivé
        creer(self.R + "1.Medias/C/c.mp4")             # récent, pas encore archivé
        cas = [
            (self.L + "1.Medias/A/a.mp4", {}, regles.DEPLACER, self.R),            # sur lent, existe sur rapide
            (self.R + "1.Medias/A/a.mp4", {}, regles.EN_PLACE, None),
            (self.R + "1.Medias/B/b.mp4", {}, regles.DEPLACER, self.L),            # effacé du rapide
            (self.L + "1.Medias/B/b.mp4", {}, regles.EN_PLACE, None),
            (self.R + "1.Medias/C/c.mp4", {"L": True}, regles.EN_PLACE, None),
            (self.L + "1.Medias/C/c.mp4", {"L": True}, regles.DEPLACER, self.R),   # lent débranché : retour rapide OK
            (self.R + "1.Medias/B/b.mp4", {"L": True}, regles.A_VERIFIER, None),   # lent débranché : on ne sait pas
            (self.R + "1.Medias/Z/z.mp4", {}, regles.INTROUVABLE, None),
            (self.L + "1.Medias/A/a.mp4", {"R": True}, regles.BLOQUE, None),       # rapide principal absent : RIEN
            ("/Volumes/Autre/x.mp4", {}, regles.HORS_RACINES, None),               # hors ligne, introuvable ailleurs
            ("", {}, regles.SANS_FICHIER, None),
        ]
        for chemin, absents, statut, vers in cas:
            with self.subTest(chemin=chemin, absents=absents):
                d = self.d(chemin, **absents)
                self.assertEqual(d.statut, statut)
                if vers:
                    self.assertTrue(d.cible.startswith(regles.nfc(vers)))
                    self.assertEqual(d.comment, "même chemin")

    def test_nfd_et_nfc(self):
        self.deux("Tournage – été/a.mp4")
        d = self.d(unicodedata.normalize("NFD", self.L + "Tournage – été/a.mp4"))
        self.assertEqual(d.statut, regles.DEPLACER)
        self.assertEqual(d.cible, regles.nfc(self.R + "Tournage – été/a.mp4"))

    def test_sequences(self):
        for i in range(12, 15):
            creer(self.R + f"seq/DJI_{i:04d}.DNG")
            creer(self.L + f"seq/DJI_{i:04d}.DNG")
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


class TestTroisiemeDisque(Banc):
    """Le cas réel : un 2e disque rapide (« Backup Mariage ») rangé différemment."""

    def test_garder_le_lien_actuel_sur_un_rapide(self):
        creer(self.R2 + "1. MEDIAS/00016. Visite/130_1328.MXF")
        creer(self.R + "1.Medias/00016. Visite/130_1328.MXF")
        d = self.d(self.R2 + "1. MEDIAS/00016. Visite/130_1328.MXF", self.racines3)
        self.assertEqual(d.statut, regles.EN_PLACE)  # pas de bascule vers le disque prioritaire

    def test_rangement_different_retrouve_par_nom_et_dossier_parent(self):
        # le clip pointe vers le 3e disque (débranché) ; le fichier est sur le lent, rangé autrement
        creer(self.L + "1.Medias/00016. Visite/130_1328.MXF")
        chemin = self.R2 + "MEDIAS DE 12tb pas sur 4tb/00016. Visite/130_1328.MXF"
        d = self.d(chemin, self.racines3, R2=True)
        self.assertEqual(d.statut, regles.DEPLACER)
        self.assertEqual(d.cible, regles.nfc(self.L + "1.Medias/00016. Visite/130_1328.MXF"))
        self.assertIn("1 dossier parent", d.comment)

    def test_noms_de_camera_ambigus_on_ne_touche_a_rien(self):
        creer(self.L + "1.Medias/T1/C0001.MP4")
        creer(self.L + "1.Medias/T2/C0001.MP4")
        d = self.d(self.R2 + "Autre rangement/T9/C0001.MP4", self.racines3, R2=True)
        self.assertEqual(d.statut, regles.AMBIGU)
        self.assertEqual(len(d.candidats), 2)

    def test_dossier_parent_departage_les_homonymes(self):
        creer(self.L + "1.Medias/T1/C0001.MP4")
        creer(self.L + "1.Medias/T2/C0001.MP4")
        d = self.d(self.R2 + "Autre rangement/T2/C0001.MP4", self.racines3, R2=True)
        self.assertEqual(d.statut, regles.DEPLACER)
        self.assertTrue(d.cible.endswith("/1.Medias/T2/C0001.MP4"))

    def test_lent_vers_rapide2_si_seul_rapide_qui_l_a(self):
        creer(self.L + "1B. Mariage/1. MEDIAS/00117. Mariage Exemple/A001/C0007.MP4")
        creer(self.R2 + "1. MEDIAS/00117. Mariage Exemple/A001/C0007.MP4")
        d = self.d(self.L + "1B. Mariage/1. MEDIAS/00117. Mariage Exemple/A001/C0007.MP4", self.racines3)
        self.assertEqual(d.statut, regles.DEPLACER)
        self.assertEqual(d.racine_cible, regles.nfc(self.R2))

    def test_priorite_entre_rapides(self):
        creer(self.R + "1.Medias/T1/x.mp4")
        creer(self.R2 + "1.Medias/T1/x.mp4")
        creer(self.L + "1.Medias/T1/x.mp4")
        d = self.d(self.L + "1.Medias/T1/x.mp4", self.racines3)
        self.assertEqual(d.racine_cible, regles.nfc(self.R))
        inverse = Racines.depuis([self.R2, self.R], [self.L])
        self.assertEqual(regles.decider(self.L + "1.Medias/T1/x.mp4", inverse,
                                        {r: OK for r in inverse.toutes}, Disque(), Index()).racine_cible,
                         regles.nfc(self.R2))

    def test_clip_hors_ligne_sur_disque_non_choisi_retrouve(self):
        creer(self.R + "1.Medias/00038. Mariage/A001/C0042.MP4")
        d = self.d("/Volumes/Disque Oublié/Mariage/00038. Mariage/A001/C0042.MP4")
        self.assertEqual(d.statut, regles.DEPLACER)
        self.assertEqual(d.racine_source, "")

    def test_rapide2_debranche_et_introuvable_ailleurs(self):
        d = self.d(self.R2 + "1. MEDIAS/T/zz.mp4", self.racines3, R2=True)
        self.assertEqual(d.statut, regles.A_VERIFIER)

    def test_homonyme_sans_dossier_distinctif_jamais_relie(self):
        # même nom, dossiers de carte identiques (DCIM/100MSDCF) mais tournages différents
        creer(self.R + "1.Medias/00039. Tournage B/DCIM/100MSDCF/DSC0001.ARW")
        d = self.d(self.R2 + "1. MEDIAS/00038. Mariage/A0001 - a7v/DCIM/100MSDCF/DSC0001.ARW", self.racines3, R2=True)
        self.assertNotEqual(d.statut, regles.DEPLACER)
        self.assertEqual(regles.score_parents("/x/A0001 - a7v/DCIM/100MSDCF/f", "/y/A0001 - a7v/DCIM/100MSDCF/f"), 0)
        self.assertEqual(regles.score_parents("/x/00038. Mariage/DCIM/100MSDCF/f", "/y/00038. Mariage/DCIM/100MSDCF/f"), 1)

    def test_taille_differente_jamais_reliee(self):
        creer(self.L + "1.Medias/00016. Visite/130_1328.MXF", "contenu original")
        creer(self.R2 + "Autre/00016. Visite/130_1328.MXF", "autre version, plus longue")
        creer(self.R + "1.Medias/00016. Visite/130_1328.MXF", "autre version aussi")
        d = self.d(self.L + "1.Medias/00016. Visite/130_1328.MXF", self.racines3)
        self.assertEqual(d.statut, regles.EN_PLACE)   # en ligne sur le lent, aucune copie identique ailleurs
        creer(self.R2 + "Autre/00016. Visite/130_1328.MXF", "contenu original")
        d = self.d(self.L + "1.Medias/00016. Visite/130_1328.MXF", self.racines3)
        self.assertEqual(d.statut, regles.DEPLACER)
        self.assertEqual(d.racine_cible, regles.nfc(self.R2))

    def test_nom_court(self):
        self.assertEqual(regles.nom_court("/V/1.Medias/00108. Visite"), "00108. Visite")
        self.assertEqual(regles.nom_court("/V/1. MEDIAS/A001"), "1. MEDIAS/A001")

    def test_index_ignore_bundles_et_caches(self):
        creer(self.L + "Catalogue.lrdata/x/C0001.MP4")
        creer(self.L + ".Trashes/C0001.MP4")
        creer(self.L + "1.Medias/T1/C0001.MP4")
        self.assertEqual(Index().candidats(regles.racine_normalisee(self.L), "c0001.mp4"),
                         [regles.nfc(self.L + "1.Medias/T1/C0001.MP4")])


class TestRacinesEtDisques(unittest.TestCase):
    def test_racines_invalides(self):
        self.assertIsNotNone(Racines.depuis(["/a/b"], ["/a/b/"]).probleme())
        self.assertIsNotNone(Racines.depuis(["/a/b"], ["/a/b/c"]).probleme())
        self.assertIsNotNone(Racines.depuis([], ["/a/c"]).probleme())
        self.assertIsNone(Racines.depuis(["/a/b", "/a/d"], ["/a/c"]).probleme())
        self.assertIsNone(Racines.depuis(["/Volumes/X"], ["/Volumes/X 2"]).probleme())  # préfixe de nom, pas de dossier

    def test_noms(self):
        r = Racines.depuis(["/Volumes/Belvoir_DO–4tb/1.Medias"],
                           ["/Volumes/Belvoir_DO_12tb/1.Medias", "/Volumes/Belvoir_DO_12tb/1B. Mariage"])
        self.assertEqual(r.nom(r.rapides[0]), "Belvoir_DO–4tb")
        self.assertEqual(r.nom(r.lents[1]), "Belvoir_DO_12tb › 1B. Mariage")
        self.assertEqual(r.nom_signe(r.rapides[0]), "⚡ Belvoir_DO–4tb")
        self.assertEqual(regles.nom_volume("/Volumes/Belvoir_DO_12tb", r), "Belvoir_DO_12tb, hors des dossiers choisis")
        self.assertEqual(regles.nom_volume("/Volumes/Autre", r), "Autre")
        self.assertEqual(regles.nom_volume("/"), "Disque du Mac")

    def test_dossier_residuel_dans_volumes(self):
        e = regles.etat_dossier("/Volumes/Disque/", ismount=lambda p: False, isdir=lambda p: True)
        self.assertFalse(e.disponible)
        self.assertIn("résiduel", e.raison)
        self.assertTrue(regles.etat_dossier("/Volumes/Disque/1.Medias/", ismount=lambda p: True, isdir=lambda p: True).disponible)

    def test_regrouper(self):
        conteneur = lambda d: d == "1.Medias"
        g = regles.regrouper(["1.Medias/A/private/CLIP", "1.Medias/B", "1.Medias/A/x", "Proxy", "Proxy/sous"], conteneur)
        self.assertEqual(g["1.Medias/A/private/CLIP"], "1.Medias/A")
        self.assertEqual(g["Proxy/sous"], "Proxy")
        g = regles.regrouper(["00108 Visite/private/M4ROOT/CLIP", "00108 Visite/DCIM/100MSDCF"])
        self.assertEqual(set(g.values()), {"00108 Visite"})

    def test_textes(self):
        self.assertEqual(regles.pluriel(1, "clip"), "1 clip")
        self.assertEqual(regles.pluriel(7518, "clip"), "7 518 clips")
        self.assertEqual(regles.pluriel(2, "proxy", "proxys"), "2 proxys")

    def test_config_version_1_reprise(self):
        with open(config.CONFIG, "w") as f:
            f.write('{"rapide": "/Volumes/A/1.Medias/", "lent": "/Volumes/B/1.Medias/", "sauvegarde_avant": false}')
        r = config.charger()
        self.assertEqual(r["rapides"], ["/Volumes/A/1.Medias/"])
        self.assertEqual(r["lents"], ["/Volumes/B/1.Medias/"])
        self.assertFalse(r["sauvegarde_avant"])
        os.remove(config.CONFIG)


class TestPlan(Banc):
    def plan(self, clips, racines=None, **absents):
        racines = racines or self.racines
        return regles.construire_plan(clips, racines, self.etats(racines, **absents), Disque(), Index())

    def test_groupes_par_tournage(self):
        for t in ("T1", "T2", "T3", "T4"):
            self.deux(f"1.Medias/{t}/CLIP/f.mp4")
        self.deux("Proxy/f.mov")
        clips = [Clip(f"u{t}", "B", "f", "Video", self.L + f"1.Medias/{t}/CLIP/f.mp4", self.L + "Proxy/f.mov" if t == "T1" else "")
                 for t in ("T1", "T2", "T3", "T4")]
        p = self.plan(clips)
        self.assertEqual([regles.nom_court(g) for g in p.groupes()], ["T1", "T2", "T3", "T4", "Proxy"])

    def test_doublons_sous_titres_proxys_hors_racines(self):
        self.deux("1.Medias/T1/a.mp4")
        self.deux("1.Medias/T1/s.srt")
        self.deux("Proxy/a.mov")
        clips = [
            Clip("u1", "Bin1", "a", "Video", self.L + "1.Medias/T1/a.mp4", self.L + "Proxy/a.mov"),
            Clip("u2", "Bin2", "a", "Video", self.L + "1.Medias/T1/a.mp4"),      # doublon
            Clip("u3", "Bin1", "s", "Subtitle", self.L + "1.Medias/T1/s.srt"),
            Clip("u4", "Bin1", "t", "Timeline", ""),
            Clip("u5", "Bin1", "x", "Video", "/Volumes/Inexistant/x.mp4"),
        ]
        p = self.plan(clips)
        self.assertEqual({a.uid for a in p.medias()}, {"u1", "u2"})
        self.assertTrue(all(a.doublon for a in p.medias()))
        self.assertEqual(len(p.proxys()), 1)
        self.assertEqual(len(p.sous_titres), 1)
        self.assertEqual(p.sans_fichier, 1)
        self.assertEqual(p.hors_racines["/Volumes/Inexistant"], [1, 1])
        self.assertIn("en double", regles.resume_plan(p))

    def test_rien_a_faire_ne_cache_pas_les_problemes(self):
        p = self.plan([Clip("u1", "B", "z", "Video", self.R + "absent.mp4")])
        self.assertIn("Rien à reconnecter", regles.resume_plan(p))
        self.assertIn("introuvable", regles.resume_plan(p))

    def test_rapport_sans_troncature_silencieuse(self):
        p = self.plan([Clip(f"u{i}", "B", f"z{i}", "Video", self.R + f"absent{i}.mp4") for i in range(60)])
        self.assertIn("… et 20 autres", "\n".join(regles.lignes_rapport(p, limite=40)))

    def test_trajets_avec_trois_disques(self):
        creer(self.L + "1.Medias/00016/130_1328.MXF")
        creer(self.R + "1.Medias/00038/a.mp4")
        creer(self.L + "1.Medias/00038/a.mp4")
        clips = [Clip("u1", "B", "m", "Video", self.R2 + "MEDIAS/00016/130_1328.MXF"),
                 Clip("u2", "B", "a", "Video", self.L + "1.Medias/00038/a.mp4")]
        p = self.plan(clips, self.racines3, R2=True)
        bilan = regles.bilan_directions(p.racines, p.actions)
        self.assertEqual(bilan, ["⚡ 1 clip : Lent ⟶ Rapide", "🐢 1 clip : Rapide2 ⟶ Lent"])
        self.assertEqual(p.absents, [regles.nfc(self.R2)])
        self.assertIn("non branché(s) : Rapide2", regles.resume_plan(p))
        seul = p.actions_choisies([p.lignes()[1]])
        self.assertEqual([a.uid for a in seul], ["u1"])
        rapport = "\n".join(regles.lignes_rapport(p))
        self.assertIn("Rapide2 ⟶ Lent", rapport)
        self.assertIn("Aucun fichier n'est copié, déplacé ni effacé", rapport)


class TestMoteurAvecFauxResolve(Banc):
    def monter(self, **kw):
        self.deux("1.Medias/T1/a.mp4")
        self.deux("1.Medias/T1/b.mp4")
        creer(self.L + "1.Medias/T2/c.mp4")              # archivé
        creer(self.L + "1.Medias/T3/b.mp4")              # homonyme dans un autre tournage
        self.deux("1.Medias/T1/s.srt")
        self.deux("Proxy/a.mov")
        self.a1 = fr.Clip(self.L + "1.Medias/T1/a.mp4", proxy=self.L + "Proxy/a.mov")
        self.a2 = fr.Clip(self.L + "1.Medias/T1/a.mp4")   # doublon dans un autre chutier
        self.b = fr.Clip(self.L + "1.Medias/T1/b.mp4")
        self.c = fr.Clip(self.R + "1.Medias/T2/c.mp4")    # hors ligne sur le rapide
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
        self.assertEqual(r.erreur, "")
        self.assertEqual(len(r.echecs), 0)
        self.assertEqual(len(r.reussis), 5)  # 4 médias (dont le doublon) + 1 proxy
        self.assertTrue(self.a2.props["File Path"].startswith(regles.nfc(self.R)))
        self.assertTrue(self.c.props["File Path"].startswith(regles.nfc(self.L)))
        self.assertTrue(self.a1.props["Proxy Media Path"].startswith(regles.nfc(self.R)))
        self.assertTrue(self.homo.props["File Path"].startswith(regles.nfc(self.L)))  # homonyme intact
        self.assertEqual(r.non_prevus, [])
        self.assertTrue(r.enregistre)
        self.assertTrue(os.path.exists(r.sauvegarde))
        ok, err = moteur.journaliser("Test", plan, r)
        self.assertTrue(ok, err)
        plan2 = moteur.analyser(self.resolve, self.projet, self.racines)
        self.assertEqual(plan2.actions, [])
        self.assertEqual(len(plan2.sous_titres), 1)

    def test_troisieme_disque_rangement_different(self):
        self.monter()
        creer(self.L + "1.Medias/T5/m.mxf")
        m = fr.Clip(self.R2 + "MEDIAS DE 12tb/T5/m.mxf")   # 3e disque débranché
        self.projet.mp.racine.clips.append(m)
        shutil.rmtree(self.R2)
        plan = moteur.analyser(self.resolve, self.projet, self.racines3)
        self.assertFalse(plan.dispo(regles.nfc(self.R2)))
        r = moteur.reconnecter(self.resolve, self.projet, plan)
        self.assertEqual(r.erreur, "")
        self.assertEqual(m.props["File Path"], regles.nfc(self.L + "1.Medias/T5/m.mxf"))

    def test_refus_de_resolve_compte_en_echec(self):
        self.monter(refuse_tout=True)
        plan = moteur.analyser(self.resolve, self.projet, self.racines)
        r = moteur.reconnecter(self.resolve, self.projet, plan)
        self.assertEqual(len([1 for a, _ in r.echecs if a.genre == "media"]), 4)
        self.assertFalse(r.tout_bon)
        self.assertIn("Échecs", "\n".join(regles.lignes_rapport(plan, r)))

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

    def test_disque_cible_disparu_avant_application(self):
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
                        code = ligne.split("#")[0]
                        if any(x in code for x in self.INTERDITS):
                            fautifs.append(f"{nom}:{n}: {ligne.strip()}")
        self.assertEqual(fautifs, [], "appel capable d'effacer, déplacer ou copier un fichier")

    def test_tous_les_disques_identiques_apres_reconnexion(self):
        def inventaire():
            res = {}
            for racine in (self.R, self.R2, self.L):
                for d, _, fichiers in os.walk(racine):
                    for f in fichiers:
                        st = os.stat(os.path.join(d, f))
                        res[os.path.join(d, f)] = (st.st_size, st.st_mtime_ns)
            return res
        TestMoteurAvecFauxResolve.monter(self)
        avant = inventaire()
        plan = moteur.analyser(self.resolve, self.projet, self.racines3)
        r = moteur.reconnecter(self.resolve, self.projet, plan)
        self.assertTrue(r.reussis)
        self.assertEqual(inventaire(), avant, "un fichier média a été modifié, déplacé ou effacé")

    def test_copies_de_securite_toutes_conservees(self):
        TestMoteurAvecFauxResolve.monter(self)
        ancien = self.b.props["File Path"]
        avant = set(os.listdir(config.SAUVEGARDES)) if os.path.isdir(config.SAUVEGARDES) else set()
        for tour in range(12):
            self.b.props["File Path"] = ancien          # on remet du travail à faire à chaque tour
            plan = moteur.analyser(self.resolve, self.projet, self.racines)
            r = moteur.reconnecter(self.resolve, self.projet, plan)
            self.assertTrue(r.sauvegarde, f"tour {tour} : pas de copie de sécurité")
            time.sleep(1.01)                             # noms horodatés à la seconde
        self.assertEqual(len(set(os.listdir(config.SAUVEGARDES)) - avant), 12, "une copie de sécurité a été effacée")


if __name__ == "__main__":
    unittest.main()
