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

Le MCP standard vise l’onglet actif. Le worker suspend donc les autres gestes de navigation pendant que le candidat contrôle un onglet. La navigation en arrière-plan sur un autre dossier reste à vérifier avec une interface qui cible explicitement l’onglet. Pour une action `page_attachFile`, ajouter `"piece": "cv"` ou `"piece": "letter"` et renseigner dans `files` l’identifiant Browsentic du document correspondant à son SHA-256. En l’absence d’identifiant, le candidat peut joindre le PDF dans l’onglet visible.

Les fixtures utilisent des portails et une messagerie simulés. Les sélecteurs, les preuves réelles et les parcours Easy Apply et External restent à valider pendant la [recette](docs/specification.md#testing-decisions).
