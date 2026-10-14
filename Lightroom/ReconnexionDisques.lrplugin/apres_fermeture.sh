#!/bin/zsh
# Lancé par le plugin à la fermeture de Lightroom : attend que Lightroom soit fermé, puis reconnecte.
SCRIPT="/Volumes/Belvoir_DO–4tb/6. Lightroom/Outils/reconnecter_photos.py"
CATALOGUES="/Volumes/Belvoir_DO–4tb/6. Lightroom/Belvoir_2026"
LOG="$HOME/Library/Logs/lightroom_reconnexion.log"

# Fenêtre de résultat (texte passé en argument pour gérer apostrophes et guillemets)
fenetre() { osascript -e 'on run argv' -e 'display alert (item 1 of argv) message (item 2 of argv)' -e 'end run' "$1" "$2" >/dev/null }

[[ -f "$SCRIPT" ]] || exit 0
# attendre la fin du processus Lightroom (max 5 min)
for i in {1..60}; do
  pgrep -x "Adobe Lightroom Classic" >/dev/null || break
  sleep 5
done
pgrep -x "Adobe Lightroom Classic" >/dev/null && exit 0
# attendre que le catalogue actif (le plus récent) soit déverrouillé (max 2 min)
catalogue=$(ls -t "$CATALOGUES"/*.lrcat(N) | head -1)
for i in {1..24}; do
  [[ -e "$catalogue.lock" ]] || break
  sleep 5
done
sleep 3
sortie=$(/usr/bin/python3 -I "$SCRIPT" --oui 2>&1)
{ echo "=== $(date '+%Y-%m-%d %H:%M:%S') (plugin)"; echo "$sortie"; } >> "$LOG"
resume=$(echo "$sortie" | grep -m1 "dossier(s) reconnecté(s)")
if [[ -n "$resume" ]]; then
  details=$(echo "$sortie" | grep -E " photos  |ignoré" | sed -E 's/^ +//; s#1\.Medias/##')
  fenetre "Lightroom — reconnexion terminée" "$resume

$details

Détails : Journal Lightroom.md"
fi
echo "$sortie" | grep -q "Lightroom Classic est ouvert" && fenetre "Lightroom — reconnexion non faite" "Le catalogue était encore verrouillé. Relance « Reconnecter photos Lightroom.command »."
exit 0
