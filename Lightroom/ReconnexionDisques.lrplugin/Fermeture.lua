local LrTasks = import 'LrTasks'
local LrDialogs = import 'LrDialogs'
local Commun = require 'Commun'

local function guillemets(s) return '"' .. s:gsub('"', '\\"') .. '"' end

return {
	LrShutdownFunction = function(doneFunction, progressFunction)
		LrTasks.startAsyncTask(function()
			-- 1. Avant de quitter : montrer ce qui va être reconnecté (seulement s'il y a quelque chose)
			LrTasks.pcall(function()
				pcall(progressFunction, 0, 'Vérification des dossiers 4tb / 12tb…')
				local texte, aFaire = Commun.verifier()
				if aFaire then
					texte = texte:gsub('%(Aperçu seulement.-%)', '')
					LrDialogs.message('Reconnexion 4tb / 12tb',
						texte .. '\nCes dossiers seront reconnectés dès que Lightroom sera fermé.', 'info')
				end
			end)
			-- 2. Après : le script attend la fermeture complète de Lightroom, reconnecte et affiche le résultat
			LrTasks.execute('nohup /bin/zsh ' .. guillemets(_PLUGIN.path .. '/apres_fermeture.sh')
				.. ' >/dev/null 2>&1 &')
			doneFunction()
		end)
	end,
}
