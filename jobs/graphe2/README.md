# Graphe 2 · Candidatures par lot

Le tableau de bord du graphe 1 affiche le bouton « Lancer les candidatures » dans la vue des offres d’un cycle. En mode **Recette**, coche les offres à essayer. Le bouton démarre un processus local indépendant du serveur du tableau de bord. La recette s’arrête au premier geste de transmission et peut présenter un aperçu du mail sur Telegram.

## Installation

Depuis `jobs/graphe2` :

```sh
uv sync --locked
.venv/bin/python -m pytest tests -q
```

Le tableau de bord appelle par défaut `jobs/graphe2/.venv/bin/linkedin-applications` et utilise `jobs/graphe2/var`. Les variables `APPLICATIONS_CLI` et `APPLICATIONS_STATE` permettent de désigner un autre exécutable et un autre répertoire d’état dans l’environnement du tableau de bord.

Préparer un répertoire privé `var` et copier `.env.example` dans `var/.env`. Utiliser Browsentic dans le profil visible déjà connecté. Le mode MCP de Browsentic s’attache au navigateur existant. Il ne lance aucun navigateur headless. Le rédacteur utilise Codex App Server et requiert LibreOffice et Poppler pour produire et contrôler la lettre. La recette d’un mail requiert le fichier Humanizer. Pour l’envoi, configurer la commande MCP Thunderbird et l’adresse exacte de l’identité déjà connectée dans Thunderbird.

Relancer un worker arrêté avec la même configuration et le même répertoire :

```sh
.venv/bin/linkedin-applications --state "$PWD/var" serve
```

Le worker verrouille son répertoire d’état pour sérialiser la navigation et les transmissions. Ses logs se trouvent dans `var/worker.log`. Le checkpoint LangGraph contient la progression des dossiers; en PostgreSQL, les registres métier conservent les réponses, tentatives et preuves durables. `var/reponses.md` contient les réponses explicitement données pour réutilisation.

## État du code

État recensé le 24 novembre 2026. Le worker utilise un graphe LangGraph persistant, une file PostgreSQL (avec compatibilité SQLite historique), un navigateur, un agent de compte, un rédacteur et un envoi Thunderbird après accord Telegram. Les formulaires et le téléversement passent par Browsentic. Les tests locaux du package donnent **43 réussites et 2 ignorés**. Ce résultat ne vaut pas validation de bout en bout des portails réels ni de la livraison Thunderbird.

Le code courant comprend notamment les nouveaux tours `account_agent`, l’inspection générique des champs de fichier (`upload_fields`), le graphe de consultation Studio et les traces techniques expurgées. Les migrations G2 027 et 028 couvrent l’activation et la réservation de création de compte. Le mandat navigateur actif est `submission-v13`; les versions précédentes restent archivées pour les tentatives historiques.

La [spécification](docs/specification.md) décrit le comportement cible; le code a aussi les limites suivantes à traiter ou valider :

- Une coupure après la réservation d’une inscription mais avant sa soumission peut laisser le compte en lecture seule sans mail d’activation. La réservation est écrite avant le tour de création.
- Après réservation d’un mail, une coupure autour de l’appel Thunderbird peut laisser l’état indéfiniment `uncertain`. La reprise ne renvoie pas le mail, mais `verify()` ne recherche pas dans les messages envoyés.
- Si le brouillon change juste avant l’envoi, `send_mail` peut demander une destination LangGraph qui n’est pas déclarée. Voir `Workflow.send_mail` et la table de transitions dans `graph.py`.
- Le SHA-256 et la référence Browsentic contrôlent les octets joints. Le code ne lie pas encore le sélecteur au rôle CV/lettre inspecté; un formulaire à plusieurs champs peut conduire à sélectionner le mauvais.
- Le contrôle d’un reçu vérifie l’URL HTTPS active, le texte exact et le poste/référence. L’origine n’est pas comparée à une liste de portails ou de redirections autorisés.
- Le rédacteur vérifie que le sujet et le corps du mail ne sont pas vides. La longueur cible de 4 à 8 lignes figure dans la conception, mais n’est plus imposée par le code.

LangSmith reçoit les statuts, transitions, indicateurs de présence et l’identifiant du fil, sans le contenu du CV, des réponses, des coordonnées, du brouillon ou de la preuve. Les agents navigateur et rédacteur reçoivent le contexte utile à leurs tours. L’agent de compte reçoit actuellement aussi l’annonce, le CV texte et les réponses via `dossier_context`; ce contexte doit être réduit. Les logs du worker contiennent l’identifiant du dossier et le type d’exception, sans détail brut.

## Agents et graphe

Le worker appelle le Runner. LangGraph exécute le navigateur dans `submission` en production et dans `fill` en recette. Les autres agents interviennent dans les nœuds `agent_compte` (compte), `letter` et `draft` (rédacteur). Chaque tour dispose d’un prompt système et reçoit la tâche et les données du dossier. Studio expose la topologie du worker en consultation.

Chaque tour App Server reçoit une liste MCP explicite, avec approbation des outils configurée par le worker. Le client relit la configuration effective et refuse les MCP ou outils qui diffèrent de cette liste. Le tour de vérification du dépôt est en lecture seule et ne reçoit que les outils de consultation. Les autres capacités App Server non utilisées sont désactivées.

En production, le graphe ouvre la tentative et écrit son checkpoint avant le tour navigateur. Codex utilise directement Browsentic pour lire le portail et décider de la navigation, de la saisie, des clics et du dépôt. Le connecteur protège le choix des pièces et relit la preuve d’un reçu dans l’onglet observé. Après une interruption autour du clic, le tour de reprise cherche un reçu en lecture seule. Les actions de préparation configurées restent disponibles en recette.

Le nœud de compte reprend l’onglet signalé par le navigateur, puis retourne un résultat au graphe. Si le mail est en retard, le graphe relance le nœud de compte à partir de l’étape de confirmation. Le rédacteur peut rendre une lettre, relire le texte extrait du PDF et demander une nouvelle version pendant son tour. Une coupure avant la soumission du formulaire d’inscription peut toutefois laisser une réservation qui empêche la reprise en écriture.

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

Pour un champ de fichier, l’agent utilise `inspect_attachment_fields` sur le conteneur du formulaire observé. L’outil repère aussi les champs masqués derrière « Browse » et renvoie leurs sélecteurs et formats. L’agent choisit le champ du CV ou de la lettre et appelle `attach_dossier_document`. La méthode repose sur l’autorisation de lecture du HTML du formulaire et sur une référence Browsentic du document. Le contrôle d’empreinte atteste les octets mais ne garantit pas à lui seul le rôle du champ : relire le nom affiché et vérifier la rubrique du formulaire. Si plusieurs champs sont indiscernables, l’agent cible une section plus précise.

Le MCP standard vise l’onglet actif. Le worker suspend donc les autres gestes de navigation pendant que le candidat contrôle un onglet. La navigation en arrière-plan sur un autre dossier reste à vérifier avec une interface qui cible explicitement l’onglet. Pour une action `page_attachFile`, ajouter `"piece": "cv"` ou `"piece": "letter"` et renseigner dans `files` l’identifiant Browsentic du document correspondant à son SHA-256. Le registre est relu à chaque pièce. Après redémarrage, associer l’empreinte au nouveau `fileId` obtenu par sélection autorisée dans le panneau (chaîne ou objet `{"fileId":"…"}`), ou à un `downloadId` autorisé. Le worker exige un contrôle des octets exacts de la référence active. Avec l’extension Chromium construite à partir de v0.9.2 et du correctif local, Browsentic vérifie le SHA-256 et l’URL du formulaire avant de toucher au champ. Le worker vérifie les capacités annoncées avant le transfert et l’empreinte retournée après. Avec l’extension standard, le worker suspend la pièce même si son identifiant et sa taille concordent. Voir le [test isolé et le correctif](tests/recette_browsentic/README.md#contrôle-du-fichier-avant-transfert). Le code de blocage mentionne son rôle (`cv` ou `letter`). Une référence absente ou expirée identifie la pièce en attente. Le refus de permission de Browsentic reste applicable.

Le DOCX configuré fournit le format de page, les marges et les styles par défaut. Codex retourne l’objet et les paragraphes adaptés aux missions et aux expériences attestées dans le CV. Le worker reconstruit le corps du DOCX, exporte le PDF avec LibreOffice et vérifie le nom de l’entreprise et l’intitulé de l’offre avec Poppler. En PostgreSQL, la première lettre validée est conservée dans `documents.dossier_letters` pour ce dossier. Le CV et la lettre peuvent être rematérialisés quand le cache local disparaît. La recette `db/tests/application_lots.sh` compare les octets reçus dans deux champs par un serveur HTTP local après publication du CV B et remplacement de session. Le transport de cette recette est simulé. Un essai séparé avec le vrai MCP a vérifié, dans deux champs d’un formulaire local, les empreintes de deux PDF factices joints par `downloadId`. Le chemin normal de sélection et de contrôle de la pièce a également été testé avec l’extension corrigée et deux documents factices. Le profil de production doit charger cette version vérifiée de l’extension.

Les fixtures utilisent des portails et une messagerie simulés. Les sélecteurs, les preuves réelles et les parcours Easy Apply et External restent à valider pendant la [recette](docs/specification.md#testing-decisions).

## Ouvrir un lot depuis PostgreSQL

Construire l’image avec `docker build -t linkedin-applications jobs/graphe2`. Fournir au conteneur un répertoire d’état privé inscriptible par son UID 1000, un DSN `APPLICATIONS_POSTGRES_DSN` pour un login membre de `linkedin_applications`, et un identifiant stable `APPLICATIONS_CANDIDATE`. Appliquer les migrations SQL au préalable.

La commande `linkedin-applications --state /etat launch --cycle UUID --mode recipe --queue-only` ouvre le lot sans lancer la navigation. Le worker peut ensuite reprendre via `serve`. Les anciens appels avec `--discovery` et sans DSN gardent leur lecture SQLite. Chaque dossier SQL garde la version d’annonce et le CV du premier lot correspondant au candidat, à l’identité de l’offre et au mode. Les octets du CV sont matérialisés dans l’état privé du worker lorsqu’il prend le dossier. La recette autonome se lance par `db/tests/application_lots.sh`.

### Observer les nœuds dans LangSmith

Configurer `LANGSMITH_TRACING=true`, `LANGSMITH_API_KEY` et `LANGSMITH_PROJECT` dans le fichier privé `--state/.env` du worker. Renseigner aussi `LANGSMITH_ENDPOINT` ou `LANGSMITH_WORKSPACE_ID` selon le compte. Relancer le worker pour charger ces valeurs. Les nouvelles exécutions et reprises produisent une trace `graphe2.applications` avec un run enfant par nœud exécuté. Ouvrir ce run pour voir les onglets **Inputs** et **Outputs**.

Les champs exportés sont les statuts, les transitions, le type de question et les indicateurs de présence des pièces; l’identifiant du fil est aussi une métadonnée. Le contenu du CV, les réponses, les coordonnées, les brouillons et les preuves ne sont pas inclus dans ces entrées/sorties. Les tours Codex reçoivent néanmoins le contexte nécessaire à leur tâche; actuellement l’agent de compte reçoit aussi CV et réponses sans en avoir besoin. Les anciennes traces conservent leurs données d’origine.

### Observer une tentative en recette

Le worker conserve le traçage automatique de l’état LangGraph désactivé. `APPLICATIONS_TRACE_LOCAL_PORT` permet d’observer la tentative de dépôt sur un collecteur local au format [REST de LangSmith](https://docs.langchain.com/langsmith/trace-with-api). La destination est le loopback du worker, sans proxy, redirection ou clé. Le projet de recette est `graphe2-recette`. L’identifiant du run parent correspond à `applications.submission_attempts.id`. Les sous-étapes portent les UUID de tentative et de dossier. Les entrées et les sorties sont vides. Les interruptions portent un libellé fixe.

`db/tests/application_lots.sh` exerce deux processus du worker Docker, un portail synthétique et un collecteur HTTP de recette. La vérification inspecte les POST et PATCH, leur hiérarchie après reprise et le reçu SQL quand le collecteur est arrêté. La réception et la recherche dans une instance LangSmith hébergée restent à vérifier.

### Mandat du formulaire

Le worker embarque les versions du mandat dans `resources/submission-v*.txt`. La constante `linkedin_applications.mandate.VERSION` sélectionne la version active. Avant le premier geste du tour natif, PostgreSQL enregistre le texte statique, son identifiant et son SHA-256 dans la tentative du dossier. La contrainte de la migration 012 vérifie l’empreinte. Le rôle du worker peut mettre à jour le bail et l’issue de la tentative. Ses privilèges préservent le mandat archivé. Les anciennes tentatives conservent une provenance inconnue. Les faits personnels sont fournis séparément au modèle.

La recette suivante utilise l’environnement G2, Codex App Server authentifié, Node, un module Playwright installé et un exécutable Chrome. Dans chaque tour, le double MCP ouvre un navigateur jetable et fournit deux pages synthétiques en mémoire. Le modèle reçoit les libellés et les cibles visibles après chaque action. Les identifiants des champs changent à chaque lancement.

```bash
jobs/graphe2/.venv/bin/python jobs/graphe2/tests/recette_mandat/run.py \
  --playwright /chemin/vers/node_modules/playwright --chrome /chemin/vers/chrome
```

La recette vérifie le fait obligatoire manquant sans réception, puis le reçu d’un dossier complet et l’issue incertaine d’un autre dépôt après validation. Chaque formulaire comporte un cadre, des champs obligatoires et un choix révélant un champ supplémentaire. Le transport de recette remplace Browsentic pendant ces trois tours. Les permissions de l’extension restent couvertes séparément par la recette du worker.

### Réponses Telegram en PostgreSQL

Avant de notifier le candidat, le worker rattache la question et son contexte à la version d’offre du dossier dans `applications.candidate_questions`. Chaque valeur ou correction devient une version de `applications.candidate_answers` avec le message source et sa date. Les boutons « Cette soumission uniquement » et « Toutes mes futures soumissions » désignent la version précise affichée. Le clic confirme uniquement la dernière version et fixe sa portée en transaction. Le worker retrouve une réponse confirmée après interruption, même si le checkpoint attend encore.

Les réponses globales sont lues dans le même mode pour le même candidat, avec leur contexte de question. Les réponses limitées au dossier ont priorité pour ce dossier. `applications.attempt_answers` conserve les versions de réponse présentées au tour natif. Un reçu permet de les retrouver via son `attempt_id`. La recette `db/tests/application_lots.sh` injecte des messages synthétiques dans un adaptateur Telegram en mémoire.

### Comptes du candidat

En mode PostgreSQL, la commande interactive `linkedin-applications --state <état> confirm-address --mode recipe` demande deux saisies de l’adresse principale. La confirmation est propre au candidat et au mode. Un changement d’adresse suspend la réutilisation des comptes associés à l’ancienne adresse.

`APPLICATIONS_ACCOUNT_KEY_FILE` désigne le fichier privé contenant les 32 octets aléatoires de la clé AES-GCM encodés en base64. Le monter en lecture seule et le sauvegarder séparément de PostgreSQL. La politique navigateur associe chaque URL HTTPS de connexion ou d’inscription à l’employeur de l’offre et à son espace. Exemple pour deux pages synthétiques du même fournisseur :

```json
{"account_pages":[
  {"url":"https://portail.invalid/a","employer":"A","space":"employeur-a"},
  {"url":"https://portail.invalid/b","employer":"B","space":"employeur-b"}
]}
```

`APPLICATIONS_ACCOUNT_KEY_FILE` active le stockage des mots de passe chiffrés dans PostgreSQL. L’agent de compte appelle `PortalAccounts` pour retrouver ou créer les identifiants associés au candidat, au mode, au portail et à l’espace employeur. Le secret est persisté avant sa saisie dans les champs observés de l’onglet. Le flux courant est le nœud `agent_compte`; les anciens mandats restent archivés uniquement pour les tentatives historiques.

Pour #15, `applications.dossier_portal_accounts(dossier_id, account_id)` rattache le dossier à la ligne de `applications.portal_accounts`. Cette ligne conserve le fournisseur, l’espace employeur, l’adresse de connexion et l’état initial `creation_en_cours`. Les états suivants sont `confirmation_en_attente` et `actif`. Un changement d’état de compte laisse le reçu de dépôt indépendant.

La recette `db/tests/portal_accounts.sh` utilise PostgreSQL 17 jetable, Chrome et deux espaces synthétiques en mémoire. Définir `CHROME` et `PLAYWRIGHT` avec l’exécutable Chrome et le module Node Playwright. Le test crée deux comptes, restaure le dump dans une deuxième base et vérifie la connexion aux deux espaces après redémarrage du gestionnaire. Une adresse manquante, un accord manquant, un espace différent et une mauvaise clé sont contrôlés. Le transport de saisie vers Chrome est un double de recette ; la preuve de saisie par le vrai MCP Browsentic figure dans la recette #3.

**Accord permanent du candidat.** En production, l’agent crée le compte nécessaire à une candidature lorsqu’aucun compte utilisable n’existe sur le portail. Il coche la case obligatoire « I agree » ou son équivalent pour les conditions d’utilisation et la confidentialité de ce compte, puis valide sans redemander l’accord. Les choix facultatifs de prospection restent décochés. Une exclusion explicite enregistrée pour un portail reste applicable.

L’agent de compte utilise Browsentic directement pour décider des clics et de la navigation. Il reçoit l’onglet et l’origine attestés par l’agent navigateur. Le code vérifie l’accord de création et réserve l’inscription avant le tour. Les entrées `account_pages` restent utiles pour réutiliser les espaces employeurs déjà enregistrés. Pour une page nouvelle, l’espace est résolu à partir du portail et de l’employeur du dossier. Appliquer `028_portal_registration_dispatch.sql` avant de déployer le tour autonome. Cette réservation préalable n’a pas encore de reprise récupérable si le processus s’arrête avant la soumission du formulaire.

Le tour reçoit son prompt système et une tâche par dossier. Il appelle les outils de saisie, de validation et de vérification, puis retourne `status` et `cause`. Le formulaire de candidature reprend après un succès vérifié. En cas d’échec du compte, le dossier indique la cause.

### Confirmation du compte par Thunderbird

Dans le flux courant, l’agent de compte réserve l’attente dans `applications.email_challenges` avant de rapprocher le message Thunderbird. Si le mail tarde, le dossier passe à `waiting_account_agent` et le worker relance ce nœud après 30 secondes. Après confirmation, l’agent vérifie la session et le graphe reprend le formulaire du dossier; une redirection vers la connexion peut déclencher une connexion distincte avant la reprise. Les anciens checkpoints peuvent encore contenir le résultat `account_confirmation`. Un compte actif et un reçu de dépôt sont deux événements distincts.

Configurer `APPLICATIONS_THUNDERBIRD_READ_COMMAND` avec la commande stdio du bridge MCP réservé à la lecture. À défaut, la lecture utilise `APPLICATIONS_THUNDERBIRD_COMMAND`. La politique navigateur accepte une entrée `email_confirmations` par espace employeur. Ses champs sont `provider`, `space`, `folder` (URI exacte Thunderbird), `sender`, `subject`, `confirmed_url` et `confirmed_text`. L’objet doit distinguer l’espace employeur dans ce dossier de messagerie. Le worker vérifie le destinataire et la date, puis l’URL, le marqueur et l’adresse connectée dans l’onglet enregistré. Une recherche ambiguë, une panne ou une confirmation encore à effectuer laisse l’attente ouverte. Le rapprochement SQL conserve l’empreinte de l’identifiant du message et la revendication d’activation.

Pour les portails à code ou lien, le worker observe l’état du compte après le geste de confirmation. Dans la recette hors ligne, `APPLICATIONS_OFFLINE_RECIPE_MARKERS=1` autorise le worker à lire le marqueur synthétique de la notification appariée et à le saisir dans le formulaire de son espace. Cette opération contrôle le réseau limité au loopback, les adresses synthétiques, la valeur attendue, l’onglet et l’URL exacte de l’espace A ou B de `portail.invalid`. Le portail de recette vérifie dans Chrome le condensat du marqueur reçu. Le pilote prépare les messages et les empreintes de référence. La livraison IMAP et la confirmation automatique d’un compte réel restent à qualifier.

Une règle de confirmation peut aussi déclarer une action `activation`. Pour un code, renseigner `kind=code`, `page_url`, `pattern` avec un groupe capturant le code numérique, `code_selector`, `confirm_selector` et `confirm_text`. Pour un lien, renseigner `kind=link`, `page_url`, `link_path` et `token_parameter`. La page d’attente et la destination doivent appartenir au portail reconnu. Appliquer la migration `027_email_activation_claim.sql` avant de configurer cette action. Thunderbird transmet le code ou le lien au worker. Le modèle reçoit uniquement l’état du dossier. Le worker réserve le message avant d’insérer le code ou d’ouvrir le lien. L’agent choisit le champ du code et le bouton de confirmation sur la page observée. Les sélecteurs de politique antérieurs permettent encore la reprise des dossiers déjà en attente.

Si un portail propose Google, le navigateur réutilise la session déjà autorisée. Le candidat reprend la main pour choisir le compte ou autoriser l’accès quand Google le demande. Thunderbird peut lire les mails de confirmation du portail depuis la boîte Gmail configurée.

`db/tests/email_confirmations.sh` démarre PostgreSQL éphémère et Thunderbird hors ligne avec deux messages synthétiques. Fournir `THUNDERBIRD`, `THUNDERBIRD_MCP_REPO` (extension et bridge construits), `PLAYWRIGHT` (module Node) et `CHROME`. Le test vérifie l’ordre inversé, la panne Thunderbird pendant qu’un troisième dossier avance, le retour sur chacun des deux formulaires après redémarrage et l’absence de reçu de candidature. L’espace réseau du test contient uniquement le loopback.

### Diagnostic des obstacles du portail

Le mandat archive un signal structuré par tour. La matrice `applications.portal_obstacles` relie la tentative au domaine du portail, à l’étape, à une observation de vocabulaire fermé, à la cause et à la présence d’un geste de transmission. Les contrôles de reprise enregistrent la date et le résultat du correctif. Les observations normalisées évitent de copier un champ, une URL avec paramètres ou le détail libre du portail.

Pour un obstacle avant transmission, « Vérifier le correctif » déclenche une lecture du même onglet. Une condition positive liée à l’offre doit être observée avant toute reprise. Un contrôle humain conserve l’attente de l’opérateur. Un HTTP 403 après validation laisse la cause inconnue et le dépôt à vérifier jusqu’à observation du reçu. La recette PostgreSQL `db/tests/application_lots.sh` couvre ces parcours avec un double du portail.

### Accord et rapprochement du mail de suivi

Après le reçu SQL du dépôt, `applications.followup_reviews` conserve le destinataire, l’objet, le corps, les noms et les empreintes des pièces présentés. Le clic Telegram valide cette version. Le worker vérifie les pièces avant de réserver l’unique tentative dans `applications.followup_sends`. Un tour du rédacteur appelle un outil à usage unique qui transmet le brouillon approuvé à `sendMail` via le MCP Thunderbird. Le modèle ne peut modifier aucun champ ni accéder aux pièces. Le mode de test habituel affiche l’aperçu. Une tentative réservée n’est jamais renvoyée automatiquement; faute de recherche dans les messages envoyés, une interruption peut rester à l’état incertain.

Renseigner `APPLICATIONS_THUNDERBIRD_COMMAND` et `APPLICATIONS_THUNDERBIRD_FROM`. Le mode demandé est l’envoi direct, après validation Telegram. Thunderbird MCP le refuse tant que son option **Block skipReview** est active. Le worker ne change pas cette option. Thunderbird MCP 0.9.2 ne fournit pas le Message-ID de l’envoi direct. Une réponse perdue ou un envoi non confirmé laisse le suivi à vérifier sans renvoyer le message.

Sur l’hôte, le bridge stdio du dépôt `TKasperczyk/thunderbird-mcp` peut être enregistré par `codex mcp add thunderbird -- /chemin/vers/node /chemin/vers/thunderbird-mcp/mcp-bridge.cjs`. Pour Docker, exposer cette même commande via un socket Unix privé comme pour Browsentic, puis indiquer la commande `socat` vers ce socket dans `APPLICATIONS_THUNDERBIRD_COMMAND`. Les pièces voyagent dans la requête MCP locale, sans montage de leurs chemins dans Thunderbird.

### Checkpoints du worker PostgreSQL

Chaque processus G2 reprend le fil du dossier depuis `runtime_g2`, avec le saver LangGraph PostgreSQL verrouillé par le package. Le rôle de migration crée les tables. Le rôle applicatif lit et écrit les checkpoints, les données des canaux et les interruptions. Un verrou de session PostgreSQL sérialise les écritures d’un fil et se libère à la déconnexion. La protection durable du tour de dépôt s’applique aussi après perte du verrou. Le worker peut reconstituer les pièces figées dans son propre répertoire privé.

Les appels historiques avec file SQLite continuent d’utiliser leur fichier `checkpoints.sqlite3`. La répétition #21 conserve le fichier historique et ses identifiants de fils dans la copie de retour arrière. Les dossiers de cette copie dont les anciens fils mélangent les modes restent en rapprochement dans `applications.legacy_holds`.

## Exécutables du worker et connexion au poste

L’image principale (`jobs/graphe2/Dockerfile`) fournit Codex CLI 0.171.0, LibreOffice Writer, Poppler et le client de socket Unix `socat`. Le rédacteur utilise son répertoire privé par dossier pour personnaliser la copie du DOCX, exporter la lettre et vérifier son PDF. Le compte du conteneur utilise l’UID 1000.

Sur l’hôte, ouvrir un socket Unix dédié à la recette, dans un répertoire privé de l’utilisateur du profil Browsentic de test. Par exemple, au premier plan, avec le bridge déjà associé au profil autorisé :

```sh
umask 077
bridge_dir=$(mktemp -d)
printf 'Répertoire du socket de recette : %s\n' "$bridge_dir"
socat "UNIX-LISTEN:$bridge_dir/browsentic.sock,mode=0600,fork" EXEC:"browsentic mcp"
```

Monter ce seul répertoire en lecture seule dans le conteneur sous `/run/linkedin-mcp`. Configurer `APPLICATIONS_BROWSER_COMMAND=["socat","STDIO","UNIX-CONNECT:/run/linkedin-mcp/browsentic.sock"]`. Chaque nouvelle connexion ouvre une session stdio du MCP hôte, y compris lorsqu’App Server lance la commande configurée. L’UID du worker doit avoir accès au socket. Les permissions et approbations du profil Browsentic s’appliquent. Fermer le relais après la recette.

Pour un tour authentifié, fournir un répertoire Codex dédié au worker et autorisé pour la recette, privé et inscriptible par son UID, via le chemin `CODEX_HOME` du conteneur. Monter le fichier modèle DOCX et, pour les brouillons d’e-mail, le texte Humanizer en lecture seule à leurs chemins `APPLICATIONS_LETTER_TEMPLATE` et `APPLICATIONS_HUMANIZER`. Le volume du dossier de travail reste inscriptible. Ces entrées se fournissent au démarrage et restent hors image. L’accès réseau au fournisseur de modèle et une session valide sont nécessaires pour vérifier la qualité d’une rédaction effective.

Depuis la racine, la recette hors ligne s’exécute avec :

```sh
docker build -t linkedin-applications:recette-image jobs/graphe2
python3 jobs/graphe2/tests/recette_image/check.py linkedin-applications:recette-image
```

Elle ouvre un thread du véritable App Server, vérifie le chemin MCP jusqu’à un serveur synthétique sur l’hôte et rend une lettre synthétique dans le workflow du rédacteur. LibreOffice et Poppler produisent puis contrôlent le PDF et sa première page. Un double local remplace le tour de rédaction du modèle. Le conteneur s’exécute sans réseau.
