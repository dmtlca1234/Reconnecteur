#!/bin/zsh
# Installe (ou met à jour) le Reconnecteur pour DaVinci Resolve. Double-cliquer.
set -e
ICI="$(cd "$(dirname "$0")" && pwd)"
APP="$HOME/Library/Application Support/Reconnecteur/app"
SCRIPTS="$HOME/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility"
DOCKAPP="$HOME/Applications/Reconnecteur.app"
ICONE="/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Resources/ResolveBin.icns"

echo "1/4  Copie de l'application…"
mkdir -p "$APP"
rsync -a --delete --exclude __pycache__ "$ICI/reconnecteur/" "$APP/reconnecteur/"
cp "$ICI/Reconnecteur.py" "$APP/Reconnecteur.py"

echo "2/4  Menu de Resolve (Workspace → Scripts → Reconnecteur)…"
mkdir -p "$SCRIPTS"
cp "$ICI/Reconnecteur.py" "$SCRIPTS/Reconnecteur.py"

echo "3/4  Icône pour le Dock (~/Applications/Reconnecteur.app)…"
mkdir -p "$HOME/Applications"
rm -rf "$DOCKAPP"
osacompile -o "$DOCKAPP" "$ICI/dock/Reconnecteur.applescript"
[[ -f "$ICONE" ]] && cp "$ICONE" "$DOCKAPP/Contents/Resources/applet.icns"
codesign --force -s - "$DOCKAPP" 2>/dev/null || true
touch "$DOCKAPP"

echo "4/4  Vérification…"
"/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Applications/ResolvePython" -I -c \
  "import sys; sys.path.insert(0, '$APP'); import reconnecteur; print('   Reconnecteur', reconnecteur.VERSION, 'prêt.')"
echo
echo "Installé. Glisse ~/Applications/Reconnecteur.app dans ton Dock si ce n'est pas déjà fait."
echo "Dans Resolve : Préférences → Système → Général → Scripting externe : Local (pour l'icône du Dock)."
[[ -t 0 ]] && read -k1 "?Appuie sur une touche pour fermer…"
exit 0
