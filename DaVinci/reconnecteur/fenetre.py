"""Fenêtre du Reconnecteur (Fusion UI Manager, s'affiche dans DaVinci Resolve).

Disposition inspirée de FreeFileSync : les disques rapides à gauche (par ordre de priorité), les
disques lents à droite ; pour chaque tournage, le disque d'origine, une flèche et le disque cible ;
des filtres et une barre de bilan en bas.

Le Reconnecteur ne copie, ne déplace et n'efface AUCUN fichier : il ne change que les liens dans Resolve."""
from __future__ import annotations

import os
import subprocess
from collections import Counter
from typing import Dict, List, Tuple

from . import VERSION, config, moteur, regles, resolve_io
from .regles import RAPIDE, LENT, SIGNE, Racines

ID_FENETRE = "ReconnecteurFenetre"
VERT, GRIS, ORANGE, BLEU = "#3fb950", "#8b949e", "#d29922", "#58a6ff"
COL_TOURNAGE, COL_CLIPS, COL_DE, COL_LIEN, COL_VERS = range(5)
FLECHE = "━━━━▶"


def _dispatcher(ui, bmd=None):
    if bmd is not None and hasattr(bmd, "UIDispatcher"):
        return bmd.UIDispatcher(ui)
    import DaVinciResolveScript as dvr
    return dvr.UIDispatcher(ui)


def _choisir_dossier(fusion, depart: str) -> str:
    """Sélecteur de dossier de Resolve ; à défaut, celui de macOS."""
    try:
        choix = fusion.RequestDir(depart or "/Volumes/")
        if choix:
            return str(choix)
    except Exception:
        pass
    try:
        script = (f'POSIX path of (choose folder with prompt "Choisis un disque ou un dossier" '
                  f'default location POSIX file "{(depart or "/Volumes/").replace(chr(34), "")}")')
        return subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=600).stdout.strip()
    except Exception:
        return ""


def ouvrir(resolve=None, fusion=None, bmd=None) -> None:
    resolve = resolve_io.connecter(resolve)
    fusion = fusion or resolve.Fusion()
    ui = fusion.UIManager
    for deja in (ui.FindWindows(ID_FENETRE) or {}).values():
        if deja.Visible:  # une seule fenêtre active à la fois (les fenêtres fermées restent en mémoire, invisibles)
            deja.Raise()
            return
    disp = _dispatcher(ui, bmd)
    reglages = config.charger()
    disques = {RAPIDE: list(reglages["rapides"]), LENT: list(reglages["lents"])}

    def panneau(niveau, titre, aide):
        """Un côté, comme les deux panneaux de FreeFileSync, avec sa liste de disques."""
        boutons = [ui.Button({"ID": f"ajouter_{niveau}", "Text": "+ Ajouter…", "Weight": 0}),
                   ui.Button({"ID": f"retirer_{niveau}", "Text": "Retirer", "Weight": 0})]
        if niveau == RAPIDE:
            boutons.append(ui.Button({"ID": "monter", "Text": "▲ Priorité", "Weight": 0}))
        return ui.VGroup({"Weight": 1}, [
            ui.Label({"Text": titre, "Weight": 0, "StyleSheet": "font-size: 14px; font-weight: bold;"}),
            ui.Label({"Text": aide, "Weight": 0, "WordWrap": True, "StyleSheet": f"color: {GRIS};"}),
            ui.Tree({"ID": f"disques_{niveau}", "Weight": 0, "MinimumSize": [200, 96], "MaximumSize": [16000, 120],
                     "RootIsDecorated": False, "AlternatingRowColors": True}),
            ui.HGroup({"Weight": 0}, boutons + [ui.HGap()]),
        ])

    win = disp.AddWindow(
        {"ID": ID_FENETRE, "WindowTitle": f"Reconnecteur {VERSION}", "Geometry": [120, 80, 1160, 780]},
        ui.VGroup({"Spacing": 8}, [
            ui.Label({"ID": "titre", "Text": "", "Weight": 0, "StyleSheet": "font-size: 15px;"}),
            ui.HGroup({"Weight": 0, "Spacing": 12}, [
                panneau(RAPIDE, "⚡  DISQUES RAPIDES", "Utilisés en priorité, dans cet ordre. Un clip déjà relié "
                                                    "à un disque rapide où son fichier existe ne bouge pas."),
                ui.Label({"Text": "⇄", "Weight": 0, "StyleSheet": "font-size: 26px; padding: 0 8px;"}),
                panneau(LENT, "🐢  DISQUES LENTS (archives)", "Utilisés seulement si le fichier n'est sur "
                                                            "aucun disque rapide."),
            ]),
            ui.HGroup({"Weight": 0}, [
                ui.Label({"Text": "Afficher :", "Weight": 0}),
                ui.CheckBox({"ID": "voir_rapide", "Text": "⚡ vers un disque rapide", "Checked": True, "Weight": 0}),
                ui.CheckBox({"ID": "voir_lent", "Text": "🐢 vers un disque lent", "Checked": True, "Weight": 0}),
                ui.CheckBox({"ID": "voir_infos", "Text": "⚠ à vérifier", "Checked": True, "Weight": 0}),
                ui.HGap(),
                ui.Button({"ID": "tout", "Text": "Tout cocher", "Weight": 0}),
                ui.Button({"ID": "rien", "Text": "Tout décocher", "Weight": 0}),
            ]),
            ui.Tree({"ID": "arbre", "SortingEnabled": False, "AlternatingRowColors": True}),
            ui.Label({"ID": "bilan", "Text": "", "WordWrap": True, "Weight": 0,
                      "StyleSheet": "font-size: 13px; font-weight: bold;"}),
            ui.Label({"ID": "resume", "Text": "", "WordWrap": True, "Weight": 0}),
            ui.Label({"ID": "garantie", "Text": "🔒  " + regles.GARANTIE, "WordWrap": True, "Weight": 0,
                      "StyleSheet": f"color: {VERT};"}),
            ui.HGroup({"Weight": 0}, [
                ui.CheckBox({"ID": "sauvegarde", "Text": "Faire une copie de sécurité du projet avant (recommandé)",
                             "Checked": bool(reglages["sauvegarde_avant"])}),
            ]),
            ui.HGroup({"Weight": 0}, [
                ui.Button({"ID": "analyser", "Text": "↻  Analyser"}),
                ui.Button({"ID": "journal", "Text": "Journal"}),
                ui.Button({"ID": "sauvegardes", "Text": "Copies de sécurité"}),
                ui.HGap(),
                ui.Button({"ID": "reconnecter", "Text": "Reconnecter la sélection", "Enabled": False}),
                ui.Button({"ID": "fermer", "Text": "Fermer"}),
            ]),
        ]))
    it = win.GetItems()
    arbre = it["arbre"]
    arbre.ColumnCount = 5
    arbre.SetHeaderLabels(["Dossier de tournage", "Clips", "De (lien actuel)", "", "Vers (nouveau lien)"])
    for col, largeur in enumerate((330, 110, 250, 70, 250)):
        try:
            arbre.ColumnWidth[col] = largeur
        except Exception:
            pass
    for niveau in (RAPIDE, LENT):
        t = it[f"disques_{niveau}"]
        t.ColumnCount = 3
        t.SetHeaderLabels(["Disque", "Dossier", "État"])
        for col, largeur in enumerate((150, 230, 150)):
            try:
                t.ColumnWidth[col] = largeur
            except Exception:
                pass

    etat: Dict = {"plan": None, "items": {}, "coches": {}, "confirmer": False, "projet": None, "resultat": None}

    def dire(texte, couleur=""):
        it["resume"].Text = texte
        it["resume"].StyleSheet = f"color: {couleur};" if couleur else ""

    def protege(fn):
        def enveloppe(ev):
            try:
                fn(ev)
            except Exception:
                dire("⚠ Erreur : " + config.noter_erreur(fn.__name__) + f"  (détails : {config.ERREURS})", ORANGE)
                it["analyser"].Enabled = True
        return enveloppe

    def racines():
        return Racines.depuis(disques[RAPIDE], disques[LENT])

    def remplir_disques():
        r = racines()
        for niveau in (RAPIDE, LENT):
            t = it[f"disques_{niveau}"]
            t.Clear()
            for i, chemin in enumerate(disques[niveau], 1):
                racine = regles.racine_normalisee(chemin)
                e = regles.etat_dossier(racine)
                item = t.NewItem()
                item.Text[0] = (f"{i}. " if niveau == RAPIDE else "") + r.nom(racine)
                item.Text[1] = racine
                item.Text[2] = "●  disponible" if e.disponible else "○  " + e.raison
                t.AddTopLevelItem(item)

    def disque_selectionne(niveau):
        item = it[f"disques_{niveau}"].CurrentItem()
        if not item:
            return None
        chemin = item.Text[1]
        for i, c in enumerate(disques[niveau]):
            if regles.racine_normalisee(c) == chemin:
                return i
        return None

    def enregistrer_disques():
        reglages.update(rapides=list(disques[RAPIDE]), lents=list(disques[LENT]),
                        sauvegarde_avant=bool(it["sauvegarde"].Checked))
        config.enregistrer(reglages)

    def annuler_confirmation():
        etat["confirmer"] = False
        it["reconnecter"].Text = "Reconnecter la sélection"

    def plan_perime():
        annuler_confirmation()
        it["reconnecter"].Enabled = False
        etat["plan"] = None
        vider_arbre()
        it["bilan"].Text = ""

    def vider_arbre():
        """Vide la liste ET oublie ses lignes : une ligne effacée ne doit plus jamais être relue."""
        memoriser_coches()
        arbre.Clear()
        etat["items"] = {}

    def memoriser_coches():
        for cle, item in list(etat["items"].items()):
            try:
                coche = item.CheckState[0]
            except (TypeError, AttributeError):  # ligne déjà effacée par Resolve
                continue
            if coche is not None:
                etat["coches"][cle] = coche == "Checked"

    def selection() -> List[Tuple[str, str]]:
        memoriser_coches()
        plan = etat["plan"]
        return [cle for cle in (plan.lignes() if plan else []) if etat["coches"].get(cle, True)]

    def maj_bilan():
        plan = etat["plan"]
        if plan is None or plan.bloque:
            it["bilan"].Text = ""
            return
        lignes = regles.bilan_directions(plan.racines, plan.actions_choisies(selection()))
        it["bilan"].Text = "     ".join(lignes) if lignes else "Rien de coché."
        it["bilan"].StyleSheet = f"font-size: 13px; font-weight: bold; color: {BLEU if lignes else GRIS};"

    def remplir_arbre():
        plan = etat["plan"]
        memoriser_coches()
        vider_arbre()
        if plan is None:
            return
        montrer = {True: bool(it["voir_rapide"].Checked), False: bool(it["voir_lent"].Checked)}
        for groupe, sens in plan.lignes():
            acts = [a for a in plan.actions if a.groupe == groupe and a.sens == sens]
            if not montrer[acts[0].vers_rapide]:
                continue
            m = [a for a in acts if a.genre == "media"]
            p = [a for a in acts if a.genre == "proxy"]
            de, vers = sens.split(" ⟶ ")
            item = arbre.NewItem()
            item.Text[COL_TOURNAGE] = regles.nom_court(groupe)
            item.Text[COL_CLIPS] = regles.nombre(len(m)) + (f" + {len(p)} px" if p else "")
            source = acts[0].ancien
            signe_de = SIGNE[plan.racines.niveau(plan.racines.racine_de(source))] if plan.racines.racine_de(source) else "⚠"
            item.Text[COL_DE] = f"{signe_de} {de}"
            item.Text[COL_LIEN] = FLECHE
            item.Text[COL_VERS] = f"{SIGNE[RAPIDE if acts[0].vers_rapide else LENT]} {vers}"
            item.CheckState[COL_TOURNAGE] = "Checked" if etat["coches"].get((groupe, sens), True) else "Unchecked"
            arbre.AddTopLevelItem(item)
            etat["items"][(groupe, sens)] = item
            sous = Counter(os.path.dirname(a.relatif) for a in m)
            for d, n in sorted(sous.items()):
                enfant = arbre.NewItem()
                rel_groupe = groupe[len(acts[0].racine_cible):]
                enfant.Text[COL_TOURNAGE] = "↳ " + (d[len(rel_groupe):].lstrip("/") or regles.nom_court(groupe))
                enfant.Text[COL_CLIPS] = regles.nombre(n)
                item.AddChild(enfant)
            for comment, n in sorted(Counter(a.comment for a in acts).items()):
                enfant = arbre.NewItem()
                enfant.Text[COL_TOURNAGE] = f"↳ {regles.pluriel(n, 'fichier')} : {comment}"
                item.AddChild(enfant)
            doublons = sum(1 for a in m if a.doublon)
            if doublons:
                enfant = arbre.NewItem()
                enfant.Text[COL_TOURNAGE] = f"↳ dont {regles.pluriel(doublons, 'clip')} en double dans le média pool (tous traités)"
                item.AddChild(enfant)
        if it["voir_infos"].Checked:
            remplir_infos(plan)
        maj_bilan()

    def remplir_infos(plan):
        def info(titre, lignes):
            if not lignes:
                return
            item = arbre.NewItem()
            item.Text[COL_TOURNAGE] = titre
            item.Text[COL_CLIPS] = regles.nombre(len(lignes))
            arbre.AddTopLevelItem(item)
            for l in lignes[:300]:
                e = arbre.NewItem()
                e.Text[COL_TOURNAGE] = "↳ " + l
                item.AddChild(e)
            if len(lignes) > 300:
                e = arbre.NewItem()
                e.Text[COL_TOURNAGE] = f"↳ … et {regles.nombre(len(lignes) - 300)} autres (voir le journal)"
                item.AddChild(e)

        info("⚠  Plusieurs fichiers possibles (non touchés)",
             [f"{c.nom} ({genre}) — {len(cands)} candidats : {' | '.join(cands[:2])}" for c, genre, cands in plan.ambigus])
        info("⚠  Introuvables sur tous les disques choisis",
             [f"{c.nom}  ({genre})  {c.proxy if genre == 'proxy' else c.chemin}" for c, genre in plan.introuvables])
        if plan.a_verifier:
            absents = ", ".join(plan.racines.nom(r) for r in plan.absents)
            info(f"ⓘ  Introuvables pour l'instant — à revoir quand {absents} sera branché",
                 [f"{c.nom}  {c.chemin}" for c in plan.a_verifier])
        info("ⓘ  Sous-titres (Resolve ne permet pas de les reconnecter)", [f"{c.nom}  {c.chemin}" for c in plan.sous_titres])
        info("ⓘ  Hors des disques choisis (non traités)",
             [f"{regles.nom_volume(vol, plan.racines)} : {regles.pluriel(t, 'clip')}, dont {regles.nombre(h)} hors ligne"
              for vol, (t, h) in sorted(plan.hors_racines.items())])

    def afficher_resultat(plan, r):
        vider_arbre()
        par_ligne: Dict[Tuple[str, str], List[int]] = {}
        for a in r.reussis:
            par_ligne.setdefault((a.groupe, a.sens), [0, 0])[0] += 1
        for a, _ in r.echecs:
            par_ligne.setdefault((a.groupe, a.sens), [0, 0])[1] += 1
        for (g, sens), (ok, ko) in sorted(par_ligne.items()):
            de, vers = sens.split(" ⟶ ")
            item = arbre.NewItem()
            item.Text[COL_TOURNAGE] = ("✓  " if not ko else "⚠  ") + regles.nom_court(g)
            item.Text[COL_CLIPS] = regles.nombre(ok) + (f"  ({ko} échec)" if ko else "")
            item.Text[COL_DE] = f"{de} — fichier conservé"
            item.Text[COL_LIEN] = FLECHE
            item.Text[COL_VERS] = f"✓ {vers} — relié ici"
            arbre.AddTopLevelItem(item)
        for a, motif in r.echecs[:300]:
            item = arbre.NewItem()
            item.Text[COL_TOURNAGE] = f"⚠  {a.nom} ({a.genre}) — {motif}"
            arbre.AddTopLevelItem(item)
        for _, av, ap in r.non_prevus[:100]:
            item = arbre.NewItem()
            item.Text[COL_TOURNAGE] = f"ⓘ  Changement non prévu : {av} → {ap}"
            arbre.AddTopLevelItem(item)
        faits = regles.bilan_directions(plan.racines, r.reussis)
        it["bilan"].Text = ("Reconnecté :  " + "     ".join(faits)) if faits else "Aucune reconnexion."
        it["bilan"].StyleSheet = f"font-size: 13px; font-weight: bold; color: {VERT if faits and not r.echecs else ORANGE};"

    @protege
    def analyser(ev):
        annuler_confirmation()
        remplir_disques()
        it["reconnecter"].Enabled = False
        etat["resultat"] = None
        r = racines()
        if not r.rapides:
            dire("Ajoute au moins un disque rapide (à gauche) avec « + Ajouter… », et tes disques d'archives à droite.")
            return
        probleme = r.probleme()
        if probleme:
            dire("⚠ " + probleme, ORANGE)
            return
        enregistrer_disques()
        it["analyser"].Enabled = False
        projet = resolve_io.projet_courant(resolve)
        etat["projet"] = projet
        it["titre"].Text = f"<b>Projet :</b> {projet.GetName()}"
        vider_arbre()
        it["bilan"].Text = ""
        dire("Lecture du média pool…")
        plan = moteur.analyser(resolve, projet, r, dire)
        etat["plan"], etat["coches"] = plan, {}
        n_rapide = sum(1 for a in plan.actions if a.vers_rapide)
        n_lent = len(plan.actions) - n_rapide
        it["voir_rapide"].Text = f"⚡ vers un disque rapide ({regles.nombre(n_rapide)})"
        it["voir_lent"].Text = f"🐢 vers un disque lent ({regles.nombre(n_lent)})"
        it["voir_infos"].Text = f"⚠ à vérifier ({regles.nombre(plan.nb_a_verifier)})"
        remplir_arbre()
        dire(regles.resume_plan(plan), ORANGE if plan.bloque else "")
        it["reconnecter"].Enabled = bool(plan.actions)
        it["analyser"].Enabled = True

    @protege
    def reconnecter(ev):
        plan = etat["plan"]
        if plan is None:
            return
        choix = selection()
        actions = plan.actions_choisies(choix)
        if not actions:
            dire("Coche au moins un dossier à reconnecter.", ORANGE)
            return
        if not etat["confirmer"]:  # premier clic : on montre exactement ce qui va se passer
            etat["confirmer"] = True
            vers = Counter(plan.racines.nom(a.racine_cible) for a in actions)
            it["reconnecter"].Text = "Confirmer : " + ", ".join(f"{regles.nombre(n)} vers {nom}" for nom, n in vers.most_common())
            dire(regles.resume_plan(plan, choix) + "  Clique à nouveau pour confirmer.")
            return
        annuler_confirmation()
        it["reconnecter"].Enabled = it["analyser"].Enabled = False
        projet = resolve_io.projet_courant(resolve)
        if projet.GetUniqueId() != etat["projet"].GetUniqueId():
            dire("⚠ Le projet ouvert a changé depuis l'analyse. Relance l'analyse.", ORANGE)
            it["analyser"].Enabled = True
            return
        enregistrer_disques()
        r = moteur.reconnecter(resolve, projet, plan, choix, reglages["sauvegarde_avant"], dire)
        etat["resultat"] = r
        ok_journal, err_journal = moteur.journaliser(projet.GetName(), plan, r)
        afficher_resultat(plan, r)
        if r.erreur:
            texte, coul = "⚠ " + r.erreur, ORANGE
        elif r.echecs:
            texte, coul = (f"⚠ {regles.pluriel(len(r.reussis), 'reconnexion')} réussie(s), "
                           f"{regles.pluriel(len(r.echecs), 'échec')} (détail ci-dessus et dans le journal)."), ORANGE
        else:
            texte, coul = f"✓ {regles.pluriel(len(r.reussis), 'reconnexion')} vérifiée(s) clip par clip.", VERT
        if r.ignores:
            texte += f" {regles.pluriel(len(r.ignores), 'clip')} ignoré(s) car modifié(s) depuis l'analyse."
        if r.enregistre is not None:
            texte += " Projet enregistré." if r.enregistre else " ⚠ Projet NON enregistré : fais Cmd+S."
        if r.sauvegarde:
            texte += " Copie de sécurité faite."
        if not ok_journal:
            texte += f" ⚠ Journal non écrit ({err_journal})."
        dire(texte, coul)
        it["analyser"].Enabled = True

    @protege
    def ajouter(ev):
        niveau = RAPIDE if ev["who"] == "ajouter_rapide" else LENT
        chemin = _choisir_dossier(fusion, "/Volumes/")
        if not chemin:
            return
        racine = regles.racine_normalisee(chemin)
        if any(regles.racine_normalisee(c) == racine for c in disques[RAPIDE] + disques[LENT]):
            dire("Ce dossier est déjà dans la liste.", ORANGE)
            return
        disques[niveau].append(racine)
        plan_perime()
        remplir_disques()
        probleme = racines().probleme()
        if probleme:
            disques[niveau].remove(racine)
            remplir_disques()
            dire("⚠ " + probleme, ORANGE)
            return
        enregistrer_disques()
        analyser(ev)

    @protege
    def retirer(ev):
        niveau = RAPIDE if ev["who"] == "retirer_rapide" else LENT
        i = disque_selectionne(niveau)
        if i is None:
            dire("Clique d'abord sur un disque de la liste, puis sur « Retirer ».", ORANGE)
            return
        disques[niveau].pop(i)
        plan_perime()
        remplir_disques()
        enregistrer_disques()
        dire("Disque retiré de la liste (rien n'est effacé sur le disque). Clique sur Analyser.")

    @protege
    def monter(ev):
        i = disque_selectionne(RAPIDE)
        if i is None or i == 0:
            dire("Clique sur un disque rapide (pas le premier), puis sur « ▲ Priorité ».", ORANGE)
            return
        disques[RAPIDE][i - 1], disques[RAPIDE][i] = disques[RAPIDE][i], disques[RAPIDE][i - 1]
        plan_perime()
        remplir_disques()
        enregistrer_disques()
        dire("Priorité changée. Clique sur Analyser.")

    @protege
    def filtre(ev):
        if etat["resultat"] is None:
            remplir_arbre()

    @protege
    def tout_cocher(ev):
        plan = etat["plan"]
        if plan is None or etat["resultat"] is not None:
            return
        valeur = ev["who"] == "tout"
        for cle in plan.lignes():
            etat["coches"][cle] = valeur
        for item in etat["items"].values():
            item.CheckState[COL_TOURNAGE] = "Checked" if valeur else "Unchecked"
        annuler_confirmation()
        maj_bilan()

    @protege
    def clic_arbre(ev):  # une case cochée ou décochée : on met le bilan à jour
        if etat["resultat"] is None:
            annuler_confirmation()
            maj_bilan()

    def ouvrir_fichier(chemin):
        if not os.path.exists(chemin):
            dire(f"Pas encore de {os.path.basename(chemin)} : il sera créé à la première reconnexion.")
            return
        subprocess.Popen(["open", chemin])

    win.On.analyser.Clicked = analyser
    win.On.reconnecter.Clicked = reconnecter
    win.On.ajouter_rapide.Clicked = ajouter
    win.On.ajouter_lent.Clicked = ajouter
    win.On.retirer_rapide.Clicked = retirer
    win.On.retirer_lent.Clicked = retirer
    win.On.monter.Clicked = monter
    win.On.voir_rapide.Clicked = filtre
    win.On.voir_lent.Clicked = filtre
    win.On.voir_infos.Clicked = filtre
    win.On.tout.Clicked = tout_cocher
    win.On.rien.Clicked = tout_cocher
    win.On.arbre.ItemClicked = clic_arbre
    win.On.journal.Clicked = lambda ev: ouvrir_fichier(config.JOURNAL)
    win.On.sauvegardes.Clicked = lambda ev: (os.makedirs(config.SAUVEGARDES, exist_ok=True), ouvrir_fichier(config.SAUVEGARDES))
    win.On.fermer.Clicked = lambda ev: disp.ExitLoop()
    getattr(win.On, ID_FENETRE).Close = lambda ev: disp.ExitLoop()

    try:
        projet = resolve_io.projet_courant(resolve)
        it["titre"].Text = f"<b>Projet :</b> {projet.GetName()}"
    except RuntimeError as e:
        it["titre"].Text = f"<b>⚠ {e}</b>"
    remplir_disques()
    win.Show()
    if disques[RAPIDE]:
        ui.QueueEvent(it["analyser"], "Clicked", {})  # analyse automatique à l'ouverture
    else:
        dire("Bienvenue ! Ajoute tes disques rapides à gauche et tes disques d'archives à droite avec « + Ajouter… ».")
    disp.RunLoop()
    # Hide() est sans effet depuis un script externe (vérifié sur Resolve 21.1) : Visible = False fonctionne.
    win.Visible = False
    win.Hide()
