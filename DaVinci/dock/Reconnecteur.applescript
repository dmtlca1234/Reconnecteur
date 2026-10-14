-- Reconnecteur : ouvre la fenêtre du Reconnecteur dans DaVinci Resolve.
-- Construit par Installer.command (osacompile). Le code est dans ~/Library/Application Support/Reconnecteur/app.
property resolvePython : "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Applications/ResolvePython"
property dossierApp : (POSIX path of (path to library folder from user domain)) & "Application Support/Reconnecteur/app/"
property titre : "Reconnecteur"

if application "DaVinci Resolve" is not running then
	tell application "DaVinci Resolve" to activate
	display dialog "DaVinci Resolve démarre. Ouvre ton projet, puis clique à nouveau sur Reconnecteur." with title titre buttons {"OK"} default button 1 with icon note giving up after 20
	return
end if
tell application "DaVinci Resolve" to activate
set journalLancement to dossierApp & "../lancement.log"
-- en arrière-plan : la fenêtre vit dans Resolve, l'app du Dock se ferme tout de suite
do shell script "cd " & quoted form of dossierApp & " && nohup " & quoted form of resolvePython & " -u Reconnecteur.py > " & quoted form of journalLancement & " 2>&1 &"
delay 4
try
	set sortie to do shell script "cat " & quoted form of journalLancement
	if sortie contains "Traceback" or sortie contains "⚠" then
		display alert titre message sortie as warning
	end if
end try
