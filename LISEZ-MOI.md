# Reconnecteur

Garde tes médias DaVinci Resolve connectés quand tu les déplaces entre des **disques rapides** (SSD,
projets en cours) et des **disques lents** (archives).

**Aucun fichier n'est jamais copié, déplacé ni effacé** : l'app change seulement l'endroit où Resolve va lire le fichier.

**La règle, par paire « dossier rapide ⇄ archive » :** chaque dossier rapide a son archive jumelle, rangée pareil
(comme une paire de dossiers dans FreeFileSync). Un clip ne passe que d'un dossier à son jumeau, au même chemin —
jamais d'une paire à une autre. Un clip déjà sur le rapide dont le fichier existe ne bouge pas.

**Même fichier ?** Avant chaque reconnexion, l'app vérifie en un éclair, sans lire le contenu : même **nom**, même
**date de modification** et même **taille**. Si l'original est hors ligne, elle compare avec la date que Resolve a
gardée en mémoire. Au moindre écart, rien n'est relié et le clip est signalé.

---

## DaVinci Resolve — l'application « Reconnecteur »

### Installer (une seule fois)
1. Double-clique sur **`DaVinci/Installer.command`**.
2. Dans Resolve : **Préférences → Système → Général → Scripting externe : Local**.
3. Glisse **`~/Applications/Reconnecteur.app`** dans ton Dock (c'est déjà fait sur ton Mac).

### Utiliser
- Ouvre ton projet dans Resolve, puis clique sur l'icône **Reconnecteur** du Dock
  (ou dans Resolve : **Workspace → Scripts → Reconnecteur**).
- **Ajoute tes paires** (mémorisées) avec « + Ajouter une paire… » : d'abord le dossier rapide (SSD), puis son
  archive. Exemple : `Belvoir_DO–4tb/1.Medias ⇄ Belvoir_DO_12tb/1.Medias`, et `Backup Mariage ⇄ Belvoir_DO_12tb/1B. Mariage`.
  « ▲ Priorité » change l'ordre ; « Retirer » enlève la paire de la liste, sans rien effacer. Marche pour n'importe
  quel projet et n'importe quels disques.
- L'analyse se lance toute seule. Chaque tournage montre **De** (lien actuel), une flèche et **Vers** (nouveau lien),
  avec la preuve (« nom, date et taille identiques »). ⚡ = rapide, 🐢 = archive.
- La barre de bilan dit exactement les trajets, ex. `⚡ 633 clips : Belvoir_DO_12tb › 1.Medias ⟶ Belvoir_DO–4tb`.
- Clique sur **Reconnecter la sélection**, puis sur **Confirmer : …**.
- C'est fait. Chaque clip est vérifié un par un, et le projet est enregistré.

### Ce qui te protège
- Une **copie de sécurité du projet** (.drp) est faite avant chaque reconnexion
  (bouton **Copies de sécurité** ; elles sont toutes gardées, rien n'est jamais effacé).
  Pour revenir en arrière : Resolve → Project Manager → clic droit → *Import Project*.
- Si le dossier rapide de la 1re paire n'est pas branché, l'outil ne propose **rien**.
- Le bouton **Journal** montre tout ce qui a été fait.

### Ce que l'outil ne peut pas faire
- Les **sous-titres** (.srt) : Resolve ne permet pas de les reconnecter par script. Ils sont listés à part.
- Les clips **en ligne hors des paires** : comptés et signalés, pas touchés. (Hors ligne, l'app les cherche par nom + date.)

---

## Si quelque chose ne va pas
- Bouton *Journal*, ou le fichier `~/Library/Application Support/Reconnecteur/erreurs.log`.
- Demande à une IA en lui donnant le fichier **`POUR-UNE-IA.md`**.
