# Graphe 2 · Candidatures par lot

Le tableau de bord du graphe 1 affiche le bouton « Lancer les candidatures » dans la vue des offres d’un cycle. En mode **Recette**, coche les offres à essayer. Le bouton démarre un processus local indépendant du serveur du tableau de bord. La recette s’arrête au premier geste de transmission et peut présenter un aperçu du mail sur Telegram.

## Installation

Depuis `jobs/graphe2` :

```sh
uv sync --locked
.venv/bin/python -m pytest tests -q
```

Le tableau de bord appelle par défaut `jobs/graphe2/.venv/bin/linkedin-applications` et utilise `jobs/graphe2/var`. Les variables `APPLICATIONS_CLI` et `APPLICATIONS_STATE` permettent de désigner un autre exécutable et un autre répertoire d’état dans l’environnement du tableau de bord.

Préparer un répertoire privé `var` et copier `.env.example` dans `var/.env`. Utiliser Browsentic dans le profil visible déjà connecté. Le mode MCP de Browsentic s’attache au navigateur existant. Il ne lance aucun navigateur headless. Le rédacteur utilise Codex App Server et requiert LibreOffice et Poppler pour produire et contrôler la lettre. La recette d’un mail requiert le fichier Humanizer. La production requiert en plus la configuration SMTP. Pour la vérification IMAP, choisir le dossier dans lequel le fournisseur conserve effectivement les messages envoyés.

Relancer un worker arrêté avec la même configuration et le même répertoire :

```sh
.venv/bin/linkedin-applications --state "$PWD/var" serve
```

Le worker verrouille son répertoire d’état pour sérialiser la navigation et les transmissions. Ses logs se trouvent dans `var/worker.log`. Le checkpoint LangGraph contient les réponses de dossier, les tentatives et les preuves. `var/reponses.md` contient les réponses explicitement données pour réutilisation.

## Navigateur en production

Le processus Codex du graphe 2 préautorise les outils Browsentic exposés pour chaque tour avec `mcp_servers.linkedin_form.default_tools_approval_mode="approve"`. Le tour de vérification dispose uniquement de la liste d’outils de consultation. Le graphe contrôle la configuration effective avant d’ouvrir la session.

App Server charge directement le MCP Browsentic pour le rôle navigateur. Codex identifie les champs et les boutons à l’écran, y compris dans un cadre intégré lorsque le navigateur l’expose. Il choisit les actions de saisie et fait la validation du formulaire. Le graphe vérifie le quota et enregistre la tentative avant ce tour. Un tour interrompu déclenche ensuite une vérification du dépôt en lecture seule. Le fichier de sélecteurs décrit ci-dessous sert à la recette.

## Actions Browsentic en recette

La recette Docker utilise un portail local, un profil Chrome dédié et un PDF synthétique. [Exécution et capacités observées](tests/recette_browsentic/README.md)

Les outils de lecture et les actions de formulaire des tours Codex passent par l’adaptateur Python. Définir dans un JSON privé les cibles vérifiées des formulaires. Les actions `prepare` sont les gestes observés comme sans transmission de candidature, notamment l’ouverture du formulaire. La phase `register` exige l’accord Telegram pour l’origine indiquée. La phase `submit` est réservée au geste de transmission suivant un checkpoint durable. Un geste dont l’effet reste indéterminé interrompt le parcours.

```json
{
  "actions": {
    "nom": {
      "description": "Renseigner le nom",
      "phase": "prepare",
      "origin": "https://recrutement.example",
      "path": "/formulaire",
      "tool": "page_fillInput",
      "selector": "#last-name",
      "value_property": "value"
    },
    "depot": {
      "description": "Transmettre le formulaire",
      "phase": "submit",
      "origin": "https://recrutement.example",
      "path": "/verification",
      "tool": "page_clickElement",
      "selector": "#send"
    }
  },
  "verification": [{
    "origin": "https://recrutement.example",
    "path": "/mes-candidatures",
    "check_url": "https://recrutement.example/mes-candidatures",
    "selector": "article.candidature",
    "marker": "Candidature reçue",
    "offer_fields": ["requisition"]
  }],
  "files": {}
}
```

Le MCP standard vise l’onglet actif. Le worker suspend donc les autres gestes de navigation pendant que le candidat contrôle un onglet. La navigation en arrière-plan sur un autre dossier reste à vérifier avec une interface qui cible explicitement l’onglet. Pour une action `page_attachFile`, ajouter `"piece": "cv"` ou `"piece": "letter"` et renseigner dans `files` l’identifiant Browsentic du document correspondant à son SHA-256. Le registre est relu à chaque pièce. Après redémarrage, associer l’empreinte au nouveau `fileId` obtenu par sélection autorisée dans le panneau (chaîne ou objet `{"fileId":"…"}`), ou à un `downloadId` autorisé. Le worker contrôle la pièce du dossier, l’inventaire actif, la taille, l’onglet et son URL avant l’appel. Une référence absente ou expirée identifie la pièce en attente. Le refus de permission de Browsentic reste applicable.

En PostgreSQL, la première lettre générée est conservée dans `documents.dossier_letters`. Le CV et la lettre peuvent être rematérialisés quand le cache local disparaît. La recette `db/tests/application_lots.sh` compare les octets reçus dans deux champs par un serveur HTTP local après publication du CV B et remplacement de session. Son transport Browsentic est simulé. La preuve de téléversement via le MCP réel reste ouverte au #2.

Les fixtures utilisent des portails et une messagerie simulés. Les sélecteurs, les preuves réelles et les parcours Easy Apply et External restent à valider pendant la [recette](docs/specification.md#testing-decisions).

## Ouvrir un lot depuis PostgreSQL

Construire l’image avec `docker build -t linkedin-applications jobs/graphe2`. Fournir au conteneur un répertoire d’état privé inscriptible par son UID 1000, un DSN `APPLICATIONS_POSTGRES_DSN` pour un login membre de `linkedin_applications`, et un identifiant stable `APPLICATIONS_CANDIDATE`. Appliquer les migrations SQL au préalable.

La commande `linkedin-applications --state /etat launch --cycle UUID --mode recipe --queue-only` ouvre le lot sans lancer la navigation. Le worker peut ensuite reprendre via `serve`. Les anciens appels avec `--discovery` et sans DSN gardent leur lecture SQLite. Chaque dossier SQL garde la version d’annonce et le CV du premier lot correspondant au candidat, à l’identité de l’offre et au mode. Les octets du CV sont matérialisés dans l’état privé du worker lorsqu’il prend le dossier. La recette autonome se lance par `db/tests/application_lots.sh`.
