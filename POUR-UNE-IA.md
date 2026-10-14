# Reconnecteur — fiche technique pour une IA

Lis ce fichier en entier avant de modifier quoi que ce soit. Les comportements de l'API listés ici ont été
**vérifiés empiriquement** (DaVinci Resolve Studio 21.1, macOS 15, 2026-10-09).
Ne les « corrige » pas d'après ta mémoire de l'API.

## Garantie absolue (exigence de l'utilisateur)
Le Reconnecteur ne copie, ne déplace et n'efface AUCUN fichier (médias, copies de sécurité, rien) : il ne change que
les liens dans Resolve. Test `TestAucunFichierEfface` : aucun appel destructeur dans `reconnecteur/` (os.remove,
shutil.rmtree/move, rename…), inventaire des deux disques identique avant/après, toutes les copies .drp conservées.
Ne jamais introduire de nettoyage de fichiers.

## Interface (inspirée de FreeFileSync)
Rapide à gauche, lent à droite (nom du volume + voyant) ; une ligne par (tournage, direction) avec présence de chaque
côté et flèche ◀/▶ ; filtres par direction ; barre de bilan `◀ N clips : <lent> ⟶ <rapide>` ; bouton de confirmation
qui nomme les disques. Ne pas laisser la fenêtre ouverte pendant un test : Resolve n'exécute qu'un script à la fois
(une fenêtre ouverte via le menu bloque le scripting externe).

## Règle métier DaVinci (v1.1 : plusieurs disques)
Racines choisies par l'utilisateur : `rapides` (liste ordonnée par priorité) et `lents` (archives). Pour chaque
clip (`regles.decider`) : relié à un rapide où le fichier existe → ne bouge pas (« garder le lien actuel ») ;
sinon chercher sur les rapides puis les lents (`regles.chercher`) : 1) même chemin relatif, 2) index par nom
(`regles.Index`, os.walk paresseux) départagé par `score_parents` = nombre de dossiers parents DISTINCTIFS
identiques (les dossiers génériques de cartes — DCIM, 100MSDCF, CLIP, M4ROOT, A001… — `est_generique` — ne
comptent pas) ; score 0 → jamais relié ; égalité → `AMBIGU` (on ne touche à rien) ; si le fichier actuel est
lisible, un candidat de taille différente est rejeté. Un clip hors ligne pointant vers un disque non choisi est
aussi recherché. Garde-fou : premier rapide indisponible → `BLOQUE`. Config v1.0 (`rapide`/`lent`) migrée
automatiquement par `config.charger`. Vérifié sur le vrai projet (2026-10-14) : 1 548 correspondances, toutes de
taille identique (1 177 même chemin, 371 retrouvées par nom).

## DaVinci/ — application « Reconnecteur » (Python, 3.9 → 3.14)
```
reconnecteur/regles.py     PUR (aucun Resolve) : Racines, etat_dossier, Disque (cache de listdir, séquences
                           « [0001-0100] » et « %04d », NFC), decider(), construire_plan(), regrouper(),
                           verifier(avant, après) → Resultat, textes en français (pluriels, « … et N autres »)
reconnecteur/resolve_io.py lecture du média pool, appliquer() chutier par chutier, ExportProject, SaveProject
reconnecteur/moteur.py     analyser → copie .drp → instantané avant → appliquer → instantané après → verifier → enregistrer
reconnecteur/fenetre.py    interface Fusion UIManager (s'affiche dans Resolve)
reconnecteur/config.py     ~/Library/Application Support/Reconnecteur/{config.json, Journal.md, Sauvegardes/, erreurs.log, .verrou}
reconnecteur/__main__.py   CLI : --analyser | --appliquer [--rapide P --lent P --sans-sauvegarde] ; sans option → fenêtre
Reconnecteur.py            lanceur (menu Resolve Workspace→Scripts ET terminal) ; recharge les modules à chaque lancement
dock/Reconnecteur.applescript  icône du Dock : lance ResolvePython Reconnecteur.py en arrière-plan (nohup)
Installer.command          copie vers ~/Library/Application Support/Reconnecteur/app + menu Resolve + ~/Applications/Reconnecteur.app
tests/test_reconnecteur.py unittest avec tests/faux_resolve.py (fidèle aux comportements ci-dessous) — 37 tests
tests/banc_resolve.py      intégration sur le VRAI Resolve : crée des médias ffmpeg + un projet jetable « ZZ Test Reconnecteur (temporaire) », puis le supprime
tests/fenetre_resolve.py   vraie fenêtre, clics simulés par ui.QueueEvent
```
Lancer les tests : `cd DaVinci && python3 -m unittest discover -s tests` puis
`"/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Applications/ResolvePython" tests/banc_resolve.py`
(Resolve ouvert, scripting externe sur Local, ffmpeg installé). Toujours lancer les trois après une modification.

### Faits Resolve 21.1 vérifiés (ne pas contredire sans re-tester sur un projet jetable)
- `MediaPool.RelinkClips(objets, dossier)` reconnecte **uniquement les objets passés**, par nom de fichier
  dans `dossier`. Deux clips du même fichier dans deux chutiers = deux objets à passer (d'où le plan par
  `GetUniqueId()`, jamais par chemin). Les homonymes d'autres dossiers ne sont jamais touchés. Retour bool.
- Séquences d'images (`File Path` = `…/frame_[0001-0005].png`) : reconnectables par dossier.
- Clips `Type == "Subtitle"` (.srt) : refusés par RelinkClips ET ReplaceClip (même non vides). Les lister à part.
- `LinkProxyMedia(chemin)` fonctionne ; reconnecter le média ne touche pas le proxy.
- `GetUniqueId()` est stable avant/après reconnexion.
- `GetClipProperty("clé")` est **déprécié** en 21.1 → utiliser `GetClipProperty()` (dict).
- Ne pas garder des milliers d'objets MediaPoolItem en mémoire pendant longtemps : un ancien script a planté
  (`'NoneType' object is not callable`) en réutilisant ~7 500 objets lus plus tôt. Relire des objets frais
  chutier par chutier au moment d'agir.
- `pm.ExportProject(nom, chemin.drp, False)` exporte le projet courant ouvert. `pm.SaveProject()` → bool.
- Pour supprimer un projet ouvert : `pm.CloseProject(p)` puis `pm.DeleteProject(nom)`.
- `MediaStorage.AddItemListToMediaPool([{"media": chemin}])` pour importer un fichier ;
  `MediaPool.ImportMedia([{"FilePath": "frame_%04d.png", "StartIndex": 1, "EndIndex": 5}])` pour une séquence.
- Fusion UIManager depuis un script **externe** (ResolvePython) : `dvr.UIDispatcher(ui)` existe ; les clics
  marchent ; `ui.QueueEvent(widget, "Clicked", {})` simule un clic (utilisé pour lancer l'analyse à
  l'ouverture et dans les tests) ; **`win.Hide()` est sans effet → `win.Visible = False`** ; les fenêtres ne
  se détruisent pas (`FindWindows` les retrouve : tester `.Visible`) ; **`ui.Timer` ne se déclenche pas** ;
  `QueueEvent` depuis un autre thread pendant `RunLoop()` ne passe pas. Mettre à jour un Label pendant un
  traitement long fonctionne (c'est Resolve qui repeint).
- Les scripts du menu Workspace→Scripts reçoivent `resolve`, `fusion`, `bmd` en globales et tournent sous le
  Python système « Current » (pas ResolvePython) → code compatible 3.9 (`from __future__ import annotations`).
- Performance mesurée : projet de 7 521 clips analysé en ~12 s (lecture du média pool + comparaison disques).

### Pièges AppleScript (app du Dock)
- `script` est un **mot réservé** : ne jamais l'utiliser comme nom de variable (bug réel rencontré).
- `do shell script` attend la fin du processus : lancer la fenêtre en arrière-plan (`nohup … &`).
- Le nom du volume contient un tiret demi-cadratin U+2013 (`Belvoir_DO–4tb`) : toujours `quoted form of`.

## Préférences de l'utilisateur
- Interface et messages **en français**, simples, sans jargon ; il veut voir ce qui va être fait avant, et un
  résultat clair après.
- Rien qui tourne en arrière-plan en permanence.
- Toujours une sauvegarde avant de modifier un projet ou un catalogue ; tester sur une copie ou un projet
  jetable, jamais directement sur ses vrais projets.
