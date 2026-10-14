"""Test de la vraie fenêtre dans Resolve, clics simulés (QueueEvent) :
ouverture → analyse auto → Tout décocher → Tout cocher → filtre → Reconnecter → Confirmer → Fermer ;
vérifie les noms de disques (bilan, bouton de confirmation, flèches) ; puis réouverture (pas de fenêtre fantôme)."""
import os
import sys

ICI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ICI)
import banc_resolve  # noqa: E402  (fixe RECONNECTEUR_DOSSIER sur un dossier temporaire)
from reconnecteur import config, fenetre, moteur, regles  # noqa: E402

resolve, projet, R, L, base = banc_resolve.preparer()
config.enregistrer({"rapides": [R], "lents": [L], "sauvegarde_avant": True})
ui = resolve.Fusion().UIManager
journal = {}
vrai_analyser, vrai_reconnecter = moteur.analyser, moteur.reconnecter
vrai_resume = regles.resume_plan


def items():
    return ui.FindWindow(fenetre.ID_FENETRE).GetItems()


def analyser_espion(*a, **k):
    plan = vrai_analyser(*a, **k)
    journal.setdefault("analyses", []).append(len(plan.actions))
    if len(journal["analyses"]) == 1:   # après la 1re analyse : les nouveaux contrôles, puis Reconnecter ×2
        it = items()
        for bouton in ("rien", "tout", "voir_lent", "reconnecter", "reconnecter"):
            ui.QueueEvent(it[bouton], "Clicked", {})
    return plan


def resume_espion(plan, selection=None):
    if selection is not None:          # appelé au 1er clic : le bouton vient d'afficher la confirmation
        journal["confirmation"] = items()["reconnecter"].Text
    return vrai_resume(plan, selection)


def reconnecter_espion(*a, **k):
    it = items()
    journal["bilan"] = it["bilan"].Text
    journal["filtres"] = (it["voir_rapide"].Text, it["voir_lent"].Text)
    try:
        premier = it["arbre"].TopLevelItem(0)
        journal["ligne"] = [premier.Text[c] for c in range(5)]
    except Exception as e:
        journal["ligne"] = repr(e)
    r = vrai_reconnecter(*a, **k)
    journal["resultat"] = r
    ui.QueueEvent(items()["fermer"], "Clicked", {})
    return r


moteur.analyser, moteur.reconnecter = analyser_espion, reconnecter_espion
regles.resume_plan = resume_espion
erreurs = []
try:
    fenetre.ouvrir(resolve)
    r = journal.get("resultat")
    if not r:
        erreurs.append(f"aucune reconnexion (analyses : {journal.get('analyses')})")
    elif r.erreur or r.echecs or len(r.reussis) != 6:
        erreurs.append(f"résultat : erreur={r.erreur!r} échecs={len(r.echecs)} réussis={len(r.reussis)}")
    print("bilan        :", journal.get("bilan"))
    print("confirmation :", journal.get("confirmation"))
    print("filtres      :", journal.get("filtres"))
    print("1re ligne    :", journal.get("ligne"))
    if "LENT ⟶ RAPIDE" not in (journal.get("bilan") or "") or "RAPIDE ⟶ LENT" not in (journal.get("bilan") or ""):
        erreurs.append("le bilan ne nomme pas les deux disques")
    if journal.get("confirmation") != "Confirmer : 5 vers RAPIDE, 1 vers LENT":
        erreurs.append(f"bouton de confirmation inattendu : {journal.get('confirmation')!r}")
    visibles = [w for w in (ui.FindWindows(fenetre.ID_FENETRE) or {}).values() if w.Visible]
    print("fenêtres encore visibles après fermeture :", len(visibles))
    if visibles:
        erreurs.append("fenêtre encore visible après fermeture")
    # réouverture : doit créer une fenêtre neuve et fonctionnelle (analyse auto puis fermeture)
    journal.clear()
    journal["analyses"] = [0]  # pas de clics Reconnecter cette fois

    def analyser_puis_fermer(*a, **k):
        plan = vrai_analyser(*a, **k)
        journal["analyses"].append(len(plan.actions))
        ui.QueueEvent(items()["fermer"], "Clicked", {})
        return plan
    moteur.analyser = analyser_puis_fermer
    fenetre.ouvrir(resolve)
    print("réouverture, analyses :", journal["analyses"])
    if journal["analyses"] != [0, 0]:
        erreurs.append(f"réouverture : analyses={journal['analyses']} (attendu une analyse, 0 action)")
    print("journal écrit :", os.path.exists(config.JOURNAL))
finally:
    moteur.analyser, moteur.reconnecter = vrai_analyser, vrai_reconnecter
    regles.resume_plan = vrai_resume
    banc_resolve.nettoyer(resolve, base)
print("✓ FENÊTRE OK" if not erreurs else "✗ " + " | ".join(erreurs))
sys.exit(1 if erreurs else 0)
