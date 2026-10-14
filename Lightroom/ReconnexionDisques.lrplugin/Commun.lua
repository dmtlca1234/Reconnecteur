-- Fonctions partagées : lance le script en mode aperçu et retourne son texte.
local LrTasks = import 'LrTasks'
local LrPathUtils = import 'LrPathUtils'
local LrFileUtils = import 'LrFileUtils'

local Commun = {}

Commun.SCRIPT = '/Volumes/Belvoir_DO–4tb/6. Lightroom/Outils/reconnecter_photos.py'

-- Retourne (texte, aFaire) : aFaire est vrai s'il y a des dossiers à reconnecter.
function Commun.verifier()
	local sortie = LrPathUtils.child(LrPathUtils.getStandardFilePath('temp'), 'reconnexion_verif.txt')
	LrTasks.execute('/usr/bin/python3 -I "' .. Commun.SCRIPT .. '" --verifier > "' .. sortie .. '" 2>&1')
	local texte = LrFileUtils.readFile(sortie) or ''
	LrFileUtils.delete(sortie)
	if texte == '' then
		return 'Impossible de lancer la vérification (le 4tb est-il branché ?)', false
	end
	if #texte > 3000 then texte = texte:sub(1, 3000) .. '\n…' end
	return texte, texte:find('Dossiers à reconnecter', 1, true) ~= nil
end

return Commun
