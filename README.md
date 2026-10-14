# Reconnecteur

Garde les médias de **DaVinci Resolve** connectés quand ils passent d'un disque rapide (SSD) à un disque
lent (archives) — sans jamais copier, déplacer ni effacer un seul fichier :
seul le lien dans le logiciel change.

- **DaVinci/** — l'application « Reconnecteur » (fenêtre dans Resolve, inspirée de FreeFileSync) :
  plusieurs disques rapides par ordre de priorité + disques d'archives, recherche des fichiers par chemin ou par
  nom et dossier de tournage (taille vérifiée), copie de sécurité du projet, vérification clip par clip.
  Installation : double-cliquer `DaVinci/Installer.command`.

📖 Mode d'emploi : [LISEZ-MOI.md](LISEZ-MOI.md) · 🤖 Fiche technique pour une IA : [POUR-UNE-IA.md](POUR-UNE-IA.md)

Tests : `cd DaVinci && python3 -m unittest discover -s tests` (et `tests/banc_resolve.py` avec Resolve ouvert).
