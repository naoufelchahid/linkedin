# Rejouer un dossier sur le profil Chrome habituel

Lancer depuis la racine du worktree. Le test nécessite Docker, `psql`, l’environnement verrouillé du graphe 1, une session Codex autorisée pour la recette et le profil Chrome habituel relié à Browsentic. Si plusieurs copies de l’extension sont connectées, conserver uniquement la copie corrigée pour le rejeu. Le worker exige `expectedSha256` et `expectedUrl` sur la connexion qui effectue le transfert.

```sh
git archive d2b9f88:jobs/graphe2 | docker build -q -t linkedin-applications:recette-d2b9f88 -
jobs/graphe1/.venv/bin/python jobs/graphe2/tests/recette_dossier/run.py \
  --image linkedin-applications:recette-d2b9f88 \
  --auth /chemin/prive/auth.json \
  --proof /chemin/prive/preuves-recette
```

Le lanceur migre un PostgreSQL jetable, vérifie le zéro initial et ouvre le lot par la route du tableau de bord. L’option interne `--queue-only` permet au test de contrôler le démarrage du seul worker Docker. Le worker utilise le mode `production` de la file jetable pour atteindre les écritures de reçu et l’attente d’accord sur le suivi. Le formulaire, ses pièces et la fiche web sont servis sur loopback.

Le pilote navigateur déterministe passe par le vrai MCP Browsentic et par `attach_dossier_document`. Il alimente le registre de la recette à partir des PDF effectivement relus dans le dossier, puis vérifie le refus d’un mauvais PDF de même taille. Le formulaire vérifie les deux empreintes dans ses champs et le serveur compare les octets du POST. Le reçu HTTP de loopback est relu avec le vérificateur par politique. Le tour natif exige une URL HTTPS pour son propre reçu. Le rédacteur utilise App Server et LibreOffice. Le client Telegram construit les deux pièces, le texte et les boutons, puis un transport synthétique les capture. Le test laisse l’accord en attente et interdit l’appel de messagerie.

Les preuves sauvegardées contiennent le résultat synthétique et la fiche de l’offre. La fiche est aussi relue dans Chrome et son empreinte du reçu est comparée à l’empreinte SQL. Le fichier d’authentification de travail et l’état de recette sont temporaires.

L’option `--cv /chemin/prive/CV.pdf` teste le PDF fourni. Le SHA-256 de la source est comparé à celui du CV reçu par le portail. Les données textuelles fournies au rédacteur restent celles de l’offre et du profil fictifs. Le PDF est servi sur loopback via une URL temporaire et les copies de téléchargement créées par la recette sont supprimées à la fin.

Ajouter `--local-writing` pour produire la lettre et le brouillon à partir de textes déterministes sans authentification Codex. Le transfert Chrome, le reçu et la présentation du suivi suivent le même chemin en recette.
