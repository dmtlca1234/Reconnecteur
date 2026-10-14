-- Plugin Lightroom Classic : reconnexion automatique des dossiers entre le SSD 4tb et le HDD 12tb.
-- Voir « 6. Lightroom/Journal Lightroom.md ».
return {
	LrSdkVersion = 10.0,
	LrSdkMinimumVersion = 6.0,
	LrToolkitIdentifier = 'ca.manoirs.reconnexion-disques',
	LrPluginName = 'Reconnexion 4tb / 12tb',
	LrPluginInfoUrl = 'file:///Volumes/Belvoir_DO–4tb/6. Lightroom/Journal Lightroom.md',

	-- À la fermeture de Lightroom : lance la reconnexion une fois le catalogue libéré
	LrShutdownApp = 'Fermeture.lua',

	LrLibraryMenuItems = {
		{ title = 'Vérifier les dossiers 4tb / 12tb…', file = 'Verifier.lua' },
	},

	VERSION = { major = 1, minor = 0, revision = 0 },
}
