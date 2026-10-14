#!/bin/zsh
# Double-cliquer pour reconnecter les dossiers déplacés entre le 4tb et le 12tb.
/usr/bin/python3 -I "$(dirname "$0")/reconnecter_photos.py"
echo
read -k1 "?Appuie sur une touche pour fermer…"
