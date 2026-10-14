# Reconnecteur

Garde tes médias DaVinci Resolve connectés quand tu les déplaces entre des **disques rapides** (SSD,
projets en cours) et des **disques lents** (archives).

**Aucun fichier n'est jamais copié, déplacé ni effacé** : l'app change seulement l'endroit où Resolve va lire le fichier.

**La règle :** si un fichier est sur un disque rapide, Resolve le lit là. S'il n'y est plus (tu l'as
archivé puis effacé du SSD), il le lit sur un disque lent. Un clip déjà relié à un disque
rapide où son fichier existe ne bouge jamais.

---

## DaVinci Resolve — l'application « Reconnecteur »

### Installer (une seule fois)
1. Double-clique sur **`DaVinci/Installer.command`**.
2. Dans Resolve : **Préférences → Système → Général → Scripting externe : Local**.
3. Glisse **`~/Applications/Reconnecteur.app`** dans ton Dock (c'est déjà fait sur ton Mac).

### Utiliser
- Ouvre ton projet dans Resolve, puis clique sur l'icône **Reconnecteur** du Dock
  (ou dans Resolve : **Workspace → Scripts → Reconnecteur**).
- **Choisis tes disques** (mémorisés) : à gauche les **disques rapides** avec « + Ajouter… », dans l'ordre de
  priorité (« ▲ Priorité » pour changer l'ordre) ; à droite les **disques lents**. Tu peux ajouter un disque
  entier ou seulement un dossier (ex. `1.Medias`). « Retirer » enlève le disque de la liste, sans rien effacer.
- L'analyse se lance toute seule. Comme dans FreeFileSync, chaque tournage montre **De** (disque actuel),
  une flèche, et **Vers** (nouveau disque). ⚡ = rapide, 🐢 = lent.
- Si un disque est rangé autrement (ex. « 1. MEDIAS » au lieu de « 1.Medias »), l'app retrouve les fichiers par
  leur nom **et** leur dossier de tournage, et vérifie que la taille est identique. Dans le doute, elle ne touche
  à rien et te le signale (« Plusieurs fichiers possibles »).
- La barre de bilan dit exactement les trajets, ex. `⚡ 633 clips : Belvoir_DO_12tb › 1.Medias ⟶ Belvoir_DO–4tb`.
- Clique sur **Reconnecter la sélection**, puis sur **Confirmer : …**.
- C'est fait. Chaque clip est vérifié un par un, et le projet est enregistré.

### Ce qui te protège
- Une **copie de sécurité du projet** (.drp) est faite avant chaque reconnexion
  (bouton **Copies de sécurité** ; elles sont toutes gardées, rien n'est jamais effacé).
  Pour revenir en arrière : Resolve → Project Manager → clic droit → *Import Project*.
- Si le disque rapide n'est pas branché, l'outil ne propose **rien** : sans ce garde-fou, il voudrait
  tout basculer vers le lent.
- Le bouton **Journal** montre tout ce qui a été fait.

### Ce que l'outil ne peut pas faire
- Les **sous-titres** (.srt) : Resolve ne permet pas de les reconnecter par script. Ils sont listés à part.
- Les clips sur **un autre disque** (ni le rapide, ni le lent) : ils sont comptés et signalés, mais pas touchés.

---

## Si quelque chose ne va pas
- Bouton *Journal*, ou le fichier `~/Library/Application Support/Reconnecteur/erreurs.log`.
- Demande à une IA en lui donnant le fichier **`POUR-UNE-IA.md`**.
