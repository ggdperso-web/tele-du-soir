# Télé du soir

Programme télé des chaînes de la TNT, mis à jour automatiquement deux fois par jour.

- Vues : Ce soir (avec tri par note), Maintenant (avec bouton Direct), Par chaîne, recherche, chaînes favorites.
- Fiches programme : résumé, réalisateur et acteurs, notes et critiques de la presse quand le guide les fournit, lien vers le direct officiel.

Fichiers
- `index.html` : l'appli
- `scripts/convert.py` : télécharge le guide sur xmltvfr.fr et le convertit
- `.github/workflows/mise-a-jour.yml` : lance la mise à jour vers 5 h et 17 h
- `data/programmes.json` : les programmes (créé par la mise à jour)

Données : guide XMLTV de [xmltvfr.fr](https://xmltvfr.fr). Directs : sites officiels des chaînes.
