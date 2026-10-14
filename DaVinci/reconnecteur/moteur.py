"""Orchestration : analyser → (sauvegarder) → reconnecter → vérifier → enregistrer → journaliser.

Utilisé à l'identique par la fenêtre et par la ligne de commande."""
from __future__ import annotations

from typing import Iterable, Optional

from . import config, regles, resolve_io
from .regles import Plan, Racines, Resultat


def etats(racines: Racines):
    return {r: regles.etat_dossier(r) for r in racines.toutes}


def analyser(resolve, projet, racines: Racines, progression=resolve_io._rien) -> Plan:
    e = etats(racines)
    clips = resolve_io.lire_clips(projet, progression)
    progression("Recherche des fichiers sur les disques choisis…")
    return regles.construire_plan(clips, racines, e, regles.Disque(), regles.Index())


def reconnecter(resolve, projet, plan: Plan, selection: Optional[Iterable] = None,
                sauvegarde_avant: bool = True, progression=resolve_io._rien) -> Resultat:
    """Ne fait QUE changer les liens dans Resolve : aucun fichier n'est copié, déplacé ni effacé.
    selection : None (tout), des groupes, ou des couples (groupe, sens)."""
    actions = plan.actions_choisies(selection)
    r = Resultat()
    if not actions:
        r.erreur = "Aucun clip sélectionné."
        return r
    nom = projet.GetName()
    try:
        with config.verrou():
            # garde-fou : le disque principal et les disques cibles doivent toujours être là
            for racine in {plan.racines.principal} | {a.racine_cible for a in actions}:
                if not regles.etat_dossier(racine).disponible:
                    r.erreur = f"{plan.racines.nom(racine)} n'est plus disponible : rien n'a été modifié."
                    return r
            if sauvegarde_avant:
                progression("Copie de sécurité du projet…")
                chemin = config.chemin_sauvegarde(nom)
                if not resolve_io.sauvegarder_drp(resolve, projet, chemin):
                    r.erreur = ("La copie de sécurité du projet a échoué : rien n'a été modifié. "
                                "(Tu peux décocher l'option pour forcer.)")
                    return r
                r.sauvegarde = chemin
            progression("Relecture de l'état avant reconnexion…")
            avant = resolve_io.instantane(projet, progression)
            try:
                ignores = resolve_io.appliquer(projet, actions, progression)
            except Exception:
                r.erreur = "Erreur pendant la reconnexion : " + config.noter_erreur("appliquer")
                ignores = {}
            progression("Vérification clip par clip…")
            apres = resolve_io.instantane(projet, progression)
            v = regles.verifier(actions, avant, apres, ignores)
            v.sauvegarde, v.erreur = r.sauvegarde, r.erreur
            r = v
            if r.reussis:
                progression("Enregistrement du projet…")
                r.enregistre = resolve_io.enregistrer(resolve)
    except config.Occupe as e:
        r.erreur = str(e)
    return r


def journaliser(projet_nom: str, plan: Plan, resultat: Resultat):
    titre = (f"{projet_nom} — {regles.pluriel(len(resultat.reussis), 'reconnexion')}"
             + (f", {regles.pluriel(len(resultat.echecs), 'échec')}" if resultat.echecs else ""))
    return config.journaliser(titre, regles.lignes_rapport(plan, resultat))
