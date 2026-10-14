local LrTasks = import 'LrTasks'
local LrDialogs = import 'LrDialogs'
local LrFunctionContext = import 'LrFunctionContext'
local Commun = require 'Commun'

LrTasks.startAsyncTask(function()
	LrFunctionContext.callWithContext('verifier', function(context)
		local progression = LrDialogs.showModalProgressDialog {
			title = 'Vérification des dossiers 4tb / 12tb…', functionContext = context }
		local texte = Commun.verifier()
		progression:done()
		LrDialogs.message('Reconnexion 4tb / 12tb', texte, 'info')
	end)
end)
