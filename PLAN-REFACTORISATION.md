# Plan de refactorisation des graphes de découverte et de candidature

**Statut : proposition à challenger avant implémentation.**

Le graphe 1 découvre et qualifie les offres. Le graphe 2 prend en charge les candidatures dont le traitement a été lancé. Chacun doit pouvoir être construit, déployé, arrêté et redémarré dans son propre Docker. PostgreSQL constitue la source de vérité et le contrat entre les deux applications. L’agent du graphe 2 pilote le navigateur à partir du formulaire réellement affiché.

## 1. Architecture et organisation du dépôt

| Composant | Responsabilité | Interface |
|---|---|---|
| Docker du graphe 1 | Collecter les annonces, identifier leurs versions, qualifier les missions, produire les rapports, enregistrer les corrections humaines | Écrit dans le schéma de découverte et enregistre le CV du cycle |
| PostgreSQL | Conserver les faits métier, documents, lots, tentatives, reçus et checkpoints | Vues SQL versionnées, droits attribués par application |
| Docker du graphe 2 | Lancer les lots, réserver les dossiers, fournir le contexte à l’agent, gérer les attentes et les reprises | Lit les offres retenues, écrit les dossiers et les tentatives |
| Browsentic sur le poste hôte | Piloter un profil de navigateur persistant dédié aux candidatures | Extension et Bridge, avec raccordement depuis le worker à valider |
| Thunderbird sur le poste hôte | Accéder aux confirmations des portails dans la boîte configurée | Serveur MCP à sélectionner et tester |
| LangSmith | Rendre les étapes et erreurs observables | Traces corrélées aux identifiants SQL du dossier et de la tentative |

Conserver les packages dans `jobs/graphe1/` et `jobs/graphe2/`, chacun avec ses dépendances verrouillées, ses tests et son image. Prévoir un répertoire racine `db/` pour les migrations, définitions des vues et tests du contrat SQL. Les migrations s’exécutent une fois au déploiement avec un rôle dédié.

Le graphe 2 importe actuellement `retained_rows` et `offer_url` depuis le package du graphe 1. Il ouvre sa base SQLite et reconstitue un chemin de snapshot. Remplacer ces trois dépendances par la lecture SQL. Maintenir la compatibilité des points d’entrée existants pendant la transition. [Configuration du package](jobs/graphe2/pyproject.toml) · [Chargement des dossiers](jobs/graphe2/src/linkedin_applications/storage.py)

**Recette d’indépendance.** Construire chaque image depuis son propre package. Arrêter le graphe 1, démarrer le graphe 2 face à PostgreSQL et ouvrir un dossier sans monter le dépôt ni le stockage local du graphe 1.

## 2. Modèle PostgreSQL et contrats de lecture

| Schéma proposé | Objets principaux | Règles |
|---|---|---|
| discovery | Offres, versions, cycles, occurrences, qualifications, tentatives techniques, rapports, éléments de revue, corrections | Une erreur technique reste sans verdict métier. Une correction humaine individuelle prime sur la version examinée. La validation globale demeure attachée au rapport. |
| documents | Versions de CV et de lettres, PDF, Markdown, empreintes, provenance | Une version immuable reste récupérable sans chemin local. |
| applications | Lots, dossiers, liens lot–dossier, pièces, questions, réponses, comptes de portails, confirmations e-mail, tentatives, reçus | Toute tentative référence l’offre et les pièces exactes utilisées. |
| runtime_g1 et runtime_g2 | Checkpoints et fils LangGraph | Chaque graphe reprend ses propres exécutions. Le tableau de suivi est lisible directement depuis les données métier. |
| api | Vues offres_retenues_v1 et suivi_candidatures_v1 | Documenter la granularité, les colonnes et les règles de sélection de chaque version. |

**Règle d’ingestion Apify.** À chaque collecte, conserver l’objet complet renvoyé par l’acteur pour chaque offre dans une colonne PostgreSQL de type `JSONB` sur l’occurrence collectée. Alimenter en parallèle des colonnes dédiées pour les champs métier utilisés par les graphes, notamment l’intitulé du poste, le type de contrat, l’URL canonique, l’entreprise, le lieu et la description des missions. Tout nouveau champ fourni par un acteur est ainsi conservé dès sa réception et reçoit une colonne dédiée dès qu’un graphe en a besoin.

**Entrée du graphe 2.** Une ligne de `api.offres_retenues_v1` correspond à une offre retenue dans un cycle. Elle expose son identité stable, sa version, son URL canonique, son contenu, le verdict applicable, l’incertitude et la version du CV. Calculer l’identité à l’ingestion et la stocker en SQL. L’entrée dans la vue rend l’offre disponible pour un lot dont le lancement reste explicite. [Sélection actuelle](jobs/graphe1/src/linkedin_discovery/retained.py)

**Suivi.** Une ligne de `api.suivi_candidatures_v1` présente le dossier de l’offre, son état, la date du dernier changement, le dernier obstacle et la référence du reçu. Une offre en attente ou bloquée reste dans le pipe. Seul un dépôt de production confirmé l’en fait sortir.

**Recette du contrat.** Comparer l’ancienne sélection à la nouvelle pour chaque cycle, offre par offre. Examiner doublons, corrections humaines, missions incertaines et erreurs techniques. À partir d’un dossier, retrouver par requête son cycle, l’annonce exacte, ses pièces, ses tentatives, son obstacle et sa preuve éventuelle.

## 3. Identité du dossier et documents

Un lot désigne un ensemble à traiter. Un dossier représente une candidature suivie dans le temps. Plusieurs lots peuvent référencer le même dossier. Imposer l’unicité sur le candidat, l’identité stable de l’offre et le mode. Séparer recette et production dans les métriques et dans la déduplication.

Au lancement, figer la version d’annonce, le cycle et la version du CV. Si l’un de ces éléments change pendant le remplissage, conserver ce qui a effectivement servi. Enregistrer explicitement toute adoption d’une nouvelle version.

Pour chaque CV confirmé, stocker en SQL les octets du PDF original, son empreinte SHA-256 et le Markdown dérivé. Générer le Markdown une fois par version. Vérifier les colonnes, les dates et les associations entre postes et employeurs. Comparer à la migration le résultat au texte déjà conservé dans `cv_text`. Donner au LLM accès au Markdown pour la qualification, les réponses et la préparation des lettres. [Contexte actuel du rédacteur](jobs/graphe2/src/linkedin_applications/writer.py)

À la soumission, résoudre le rôle demandé — CV ou lettre — vers le document figé dans le dossier. Vérifier l’empreinte et obtenir une référence de téléversement valable dans la session Browsentic active. Enregistrer un blocage identifiable si la référence manque ou expire. Permettre son renouvellement après redémarrage. [Résolution actuelle des pièces](jobs/graphe2/src/linkedin_applications/browser.py)

**Recette documentaire.** Ouvrir un dossier avec le CV A, publier un CV B, redémarrer le navigateur et vérifier l’empreinte du fichier effectivement reçu par le portail de test. Refaire l’essai avec deux champs distincts pour le CV et la lettre.

## 4. Agent web autonome et recherche sur les blocages

Le parcours de production doit permettre de terminer un formulaire inédit sans ajouter de sélecteur ou de procédure propre à l’employeur. L’agent observe la page, choisit ses gestes, interprète les options, suit les redirections, entre dans les iframes et traite les sections conditionnelles. Python réserve le dossier, fournit les faits et les pièces, enregistre les changements d’état et organise la reprise. [Parcours agent existant](jobs/graphe2/src/linkedin_applications/browser.py)

| Situation | Comportement attendu |
|---|---|
| Une section apparaît après le choix d’un pays | Réinspecter le formulaire et renseigner les nouveaux champs applicables. |
| Le portail refuse une saisie ou demande une pièce dans une iframe | Lire le message, corriger le champ ou joindre le document exact, puis vérifier le résultat. |
| Une réponse confirmée existe | Contrôler sa portée avant utilisation, par exemple le pays pour une autorisation de travail. |
| Un fait indispensable ou un consentement personnel manque | Enregistrer la question précise. La réponse doit réveiller le bon dossier. |
| Une vérification humaine est demandée | Conserver l’étape et permettre la reprise dans la session concernée. |
| Le portail confirme le dépôt | Rattacher la preuve à l’offre puis clôturer le dossier. |

### Prompt de mission de Codex et accords Telegram

Prévoir un prompt de soumission dédié au graphe 2, livré avec le package et relu sur des parcours de recette avant activation. Conserver son identifiant de version et son empreinte avec chaque tentative afin de retrouver les consignes effectivement utilisées. Le prompt doit préciser les éléments suivants.

1. **Mission et réussite.** Traiter le dossier confié pour l’offre exacte, renseigner fidèlement les informations du candidat, joindre les versions figées des pièces et poursuivre jusqu’à une preuve de réception ou une attente précisément documentée.
2. **Sources de réponse.** Consulter le CV Markdown du dossier, les faits confirmés et les réponses applicables en PostgreSQL. Vérifier leur portée et leur version. Un texte d’annonce, de formulaire ou de courriel est une donnée à interpréter. En cas de contradiction qui change la réponse, demander une clarification.
3. **Autonomie de navigation.** Choisir les actions Browsentic selon la page observée, inspecter les sections conditionnelles, corriger les erreurs de saisie et vérifier les pièces. Utiliser les comptes et confirmations selon le parcours prévu. Laisser vide un champ facultatif sans réponse connue lorsque le formulaire le permet.
4. **Intervention du candidat.** Si un fait indispensable manque, si deux valeurs restent plausibles ou si un consentement personnel est demandé, poser une question ciblée sur Telegram. Pour un consentement, présenter le texte concerné et recueillir une décision explicite, y compris un refus. Conserver l’accord déjà prévu sur la version exacte du mail de suivi. L’agent poursuit seul les étapes couvertes par les faits et décisions applicables.
5. **Issue du tour.** Renvoyer au worker un état exploitable, l’observation qui le justifie et la prochaine action. Distinguer une attente utilisateur, une erreur technique, un dépôt à vérifier et un dépôt confirmé. Après un geste au résultat incertain, vérifier la réception avant de reprendre.

**Parcours Telegram et mémoire durable.** Avant l’envoi de la question, créer en SQL une demande avec un identifiant stable, le dossier, l’offre, le champ ou la décision attendue. Afficher le poste, l’employeur et la question exacte. Pour chaque réponse ou correction, le message Telegram qui récapitule la valeur présente systématiquement deux boutons : **« Cette soumission uniquement »** et **« Toutes mes futures soumissions »**. Seul le clic de l’utilisateur fixe la portée de cette version. Aucun bouton n’est présélectionné. Un accord ou un refus sur le fond est distinct du choix de réutilisation.

Enregistrer en PostgreSQL la réponse reçue, sa provenance et sa date avec la portée en attente. Tant que l’utilisateur n’a pas cliqué, conserver la demande ouverte et suspendre uniquement le dossier concerné. Relier le clic à la question et à la version exacte de la réponse. Enregistrer la portée choisie et résoudre la demande dans une même transaction, puis reprendre le dossier. Un clic reçu deux fois reste sans effet supplémentaire et un bouton d’une ancienne version ne valide pas une correction. Préserver les valeurs effectivement utilisées pour les dépôts antérieurs.

**Recette du prompt et du dialogue.** Tester les deux boutons, l’absence de clic et un clic tardif sur une version corrigée. Tester une information déjà connue, un fait obligatoire inconnu, un consentement refusé et deux dossiers en attente simultanée. Faire répondre puis corriger une valeur sur Telegram, rejouer le même événement, puis redémarrer le worker. Vérifier qu’une seule correction est enregistrée, que le bon dossier reprend avec la valeur corrigée, que sa portée est respectée lors du dossier suivant et qu’un ancien reçu reste rattaché aux informations utilisées à l’époque.

### Profil persistant et recette avec les permissions réelles

Utiliser un profil Chrome persistant dédié aux candidatures, géré par l’extension et le Bridge Browsentic sur le poste hôte. Tester depuis le Docker avec l’identité effective du worker la lecture et l’activation d’un onglet, les changements d’onglet, les iframes, les pièces et la reprise de session. Chrome DevTools MCP propose aussi l’option `--autoConnect` à partir de Chrome 144, avec autorisation à la connexion. La réserver au diagnostic si le raccordement Browsentic échoue. [Architecture Browsentic](https://github.com/imshaikot/browsentic) · [Configuration officielle de Chrome](https://developer.chrome.com/docs/devtools/agents/get-started/configuration/)

### Recherche par portail

Constituer une matrice indiquant le portail, l’étape, le message exact expurgé, la présence éventuelle d’un geste de transmission, la cause confirmée ou inconnue et le résultat du correctif. Séparer les refus de permission locaux, sessions expirées, champs indisponibles, téléversements incomplets, limitations de débit et vérifications affichées par le portail. Le HTTP 403 déjà observé demeure de cause indéterminée.

Tester les interactions sur des critères observables : champ visible et éditable, bouton activé, fin du téléversement, valeur acceptée ou message de validation. Faire défiler jusqu’à rendre le contrôle accessible et réinspecter la page. Respecter les délais annoncés par le service. La recherche vise la continuité de session, la fiabilité et la reprise. Le contournement des protections anti-bot sort du périmètre. [Critères d’interaction](https://playwright.dev/docs/actionability)

**Recette web.** Présenter deux formulaires inédits avec des libellés et un ordre différents, une iframe et une section conditionnelle. Vérifier leur traitement par le même agent sans modification du code. Mesurer les interruptions par cause et les doubles tentatives, puis comparer après correction.

## 5. Mémoire SQL, comptes et confirmation par Thunderbird

**Réponses du candidat.** Conserver dans `candidate_answers` la question, la réponse confirmée, la provenance, la portée et l’accord de réutilisation. Pour toute nouvelle réponse ou correction, appliquer le choix binaire effectué par l’utilisateur via les boutons Telegram. Le pays ou l’employeur mentionné dans une question reste un élément de son sens. Lors de la migration, préserver les restrictions existantes. Aucun élargissement aux futures soumissions sans clic explicite.

**Comptes.** Conserver dans `portal_accounts` le candidat, le fournisseur de recrutement, l’espace employeur, l’adresse de connexion, l’identifiant, le mot de passe chiffré et l’état du compte. Vérifier avant déploiement l’orthographe de l’adresse Gmail principale dictée. Rechercher un compte existant avant inscription. Pour une création, générer un secret unique et le persister chiffré avec l’état `creation_en_cours` avant de valider sur le portail.

**Secrets et restauration.** Gérer la clé de chiffrement hors de la base et tester sa récupération avec une sauvegarde. Prototyper une opération qui renseigne le mot de passe dans la session active sans le faire transiter par le prompt. Inspecter les checkpoints, captures, journaux et traces de recette. La faisabilité de cette saisie via le connecteur reste à démontrer.

**Confirmation de compte.**

1. Enregistrer dans `email_challenges` le compte, le dossier, le portail et le début de l’opération avant de se mettre en attente.
2. Rechercher via le MCP Thunderbird le message correspondant dans la boîte configurée. IMAP assure la réception et SMTP l’envoi. Valider les capacités et le raccordement du serveur MCP retenu depuis le conteneur.
3. Faire correspondre le destinataire, le portail, l’heure et le contexte du message. Conserver l’attente en cas d’ambiguïté.
4. Utiliser le code ou le lien dans la session concernée. Conserver l’issue de la confirmation et reprendre le formulaire.
5. Si Thunderbird devient indisponible, suspendre les dossiers qui attendent un message et laisser les autres avancer.

Une confirmation de compte fait passer le compte à l’état actif. Le dossier reste ouvert jusqu’à la preuve du dépôt de l’offre. Préserver la validation existante du brouillon exact pour le mail de suivi envoyé au recruteur.

**Recette de corrélation.** Créer deux comptes de test auprès du même fournisseur pour deux employeurs, interrompre le worker et recevoir les messages dans l’ordre inverse. Vérifier le rattachement au bon compte et au bon dossier, l’absence de faux reçu et l’absence de secrets dans les traces.

## 6. Concurrence, états métier et reprise après panne

| État proposé | Signification et reprise |
|---|---|
| a_preparer / en_cours | Un worker réserve le dossier dans une transaction courte avec un bail renouvelable et un numéro de génération. |
| attente_candidat / attente_email | L’événement attendu et sa portée sont enregistrés. Sa réception réveille uniquement le dossier concerné. |
| blocage_technique | Conserver la cause, la dernière étape connue et les conditions d’une reprise. |
| depot_a_verifier | Une transmission a pu avoir lieu. Consulter en lecture seule l’historique, le portail ou un accusé attribuable à l’offre. |
| depot_confirme | Une preuve rattachée à l’offre a été persistée. Les lots ultérieurs retrouvent le dossier clôturé. |

Ouvrir une tentative durable avant tout tour d’agent susceptible de transmettre. Un bouton « Continuer » peut déclencher un dépôt. Si le tour s’interrompt sans issue vérifiable, réconcilier le dossier avant d’autoriser un nouvel envoi. Un reçu déjà écrit en SQL fait foi même si le checkpoint n’a pas été sauvegardé.

Tester le cas où le bail expire alors que l’ancien navigateur est encore actif. Le numéro de génération empêche les écritures SQL obsolètes. Avant de confier le droit de transmettre à un autre worker, démontrer l’arrêt de l’ancien tour ou la révocation effective de sa capacité d’envoi. Si cette propriété ne peut pas être établie, maintenir le dossier en vérification. Prototyper ce cas avant le passage à plusieurs workers.

**Recette de panne.** Interrompre le worker avant le clic, après acceptation par le portail mais avant réception de la réponse, puis après écriture du reçu et avant sauvegarde du checkpoint. Vérifier l’absence de renvoi aveugle et reprendre les tests existants de recoupement des lots et de perte de réponse. [Tests de workflow](jobs/graphe2/tests/test_workflow.py)

## 7. Traçage LangSmith du graphe 2

Le runner désactive le traçage sur certains chemins. Rendre ce choix configurable par environnement et définir une destination identifiable pour chaque graphe. Exécuter un dossier fictif via le véritable worker Docker et vérifier la réception de la trace parent et des sous-étapes dans la destination attendue. Vérifier aussi la reprise après interruption. [Runner du graphe 2](jobs/graphe2/src/linkedin_applications/runner.py)

Utiliser des identifiants opaques de dossier et de tentative, le mode et l’étape. Relier une erreur du tableau de suivi à sa trace. Inspecter le contenu effectivement exporté pour exclure CV, réponses privées, mots de passe, cookies, codes et liens de confirmation. Une panne de télémétrie doit laisser intacts les reçus SQL.

## 8. Refonte complète de l’interface web

Organiser l’interface autour de trois écrans reliés entre eux : une vue d’ensemble, une liste filtrable et une fiche par offre. Le serveur web interroge directement les vues PostgreSQL avec un rôle de lecture dédié. Les identifiants SQL restent côté serveur. Les KPI, les graphiques, les listes et les fiches partagent les mêmes définitions SQL des offres et des états. Les états de candidature, preuves et réponses utiles proviennent des tables métier.

### Dashboard et définition des indicateurs

Afficher en tête les offres collectées distinctes, les offres retenues, les dépôts confirmés et les dossiers à vérifier. Proposer des filtres par cycle, période de collecte, entreprise, lieu et contrat. Afficher le périmètre actif et la date d’actualisation. Par défaut, compter les offres distinctes par identité stable en production. Une offre présente dans plusieurs lots ne compte qu’une fois. La période sélectionne les offres collectées sur l’intervalle ; leur état affiché est le dernier connu.

- **Camembert de qualification.** Sur les offres collectées du périmètre, afficher la part retenue, écartée, en attente de qualification et en erreur technique. Utiliser le verdict applicable à la version sélectionnée avec priorité à la correction humaine.
- **Camembert de candidature.** Sur les offres retenues du même périmètre, afficher quatre parts exclusives : dépôt confirmé avec preuve, dépôt à vérifier, bloquée après échec technique avant dépôt, et autres offres non postulées. Cette dernière part regroupe notamment les offres à préparer, en cours ou en attente d’une réponse. Une tentative échouée suivie d’un succès appartient uniquement aux dépôts confirmés. Un dépôt incertain conserve sa catégorie jusqu’à réconciliation.
- **Lecture des chiffres.** Indiquer le nombre, le pourcentage et le dénominateur dans chaque légende. Pour « non postulées », totaliser les échecs avant dépôt et les autres offres non postulées ; présenter ces deux composantes dans le détail. Pour zéro offre, afficher un état vide. Un clic sur un chiffre ou un secteur ouvre la liste correspondante en conservant les filtres.
- **Suivi opérationnel.** Ajouter une courbe hebdomadaire des dépôts confirmés, calculée sur leur date de confirmation, et une courte liste « À traiter » triée par ancienneté de l’attente : question au candidat, blocage technique, dépôt à vérifier. Distinguer visuellement les dates de collecte et de dépôt.

### Liste concise des offres

Afficher une ligne par offre avec l’intitulé et l’entreprise, le lieu et le contrat, le verdict, l’état de candidature en toutes lettres et la dernière activité. Permettre la recherche par poste ou entreprise, le tri et la pagination côté serveur. Rendre le titre cliquable et restaurer filtres, tri et page au retour de la fiche. Sur mobile, convertir chaque ligne en carte compacte. Employer des libellés et des icônes lisibles sans dépendre uniquement de la couleur.

### Fiche d’offre et avancement

Prévoir une adresse stable par identité d’offre. En tête, présenter l’intitulé, l’entreprise, le lieu, le type de contrat, la date de publication si fournie et le lien vers l’annonce. Regrouper ensuite les attributs Apify normalisés en rubriques courtes : missions, conditions et modalités de travail. Reformuler fidèlement, signaler les informations manquantes et permettre de consulter le texte source conservé. Si la version examinée pour le dossier diffère de la dernière annonce collectée, identifier clairement les deux versions.

Réserver un volet à l’avancement : état courant, date du dernier changement, obstacle éventuel et prochaine action attendue. Une chronologie SQL relie collecte, qualification, entrée dans un lot, tentatives et confirmation. Présenter le reçu lorsqu’il existe. Sur mobile, placer le résumé d’état juste sous le titre. Limiter les données exposées aux informations nécessaires au suivi ; exclure mots de passe, codes de confirmation et contenu privé de la boîte mail.

**Recette de cohérence et d’ergonomie.** Avec des données de test couvrant une offre dans deux lots, un échec suivi d’un succès, un dépôt incertain et une période vide, comparer chaque compteur à une requête SQL et au nombre de lignes de sa liste filtrée. Vérifier que les secteurs couvrent tout leur dénominateur, que la fiche restitue le même état et qu’un nouveau reçu en base actualise les trois écrans. Tester le parcours graphique → liste → fiche → retour, au clavier et sur mobile.

## 9. Ordre de livraison et de migration

| Lot | Travail | Condition de passage |
|---|---|---|
| 1. Inventaire | Recenser et sauvegarder SQLite, checkpoints, PDF, rapports, réponses, dossiers ouverts, tentatives et reçus. | Réussir une restauration isolée et retrouver des dossiers ouverts, bloqués et clôturés. |
| 2. Prototypes | Tester Docker vers Browsentic, la saisie protégée d’un secret et la lecture Thunderbird via MCP. | Identifier les permissions réellement requises, les limites et les conditions de reprise. |
| 3. PostgreSQL et découverte | Introduire les migrations, les documents et les vues. Rejouer la découverte sur une copie. | Réconcilier les sélections par cycle et les empreintes des documents et des rapports. |
| 4. Découplage | Migrer le graphe 1, retirer les imports intergraphes et les chemins partagés, construire chaque image indépendamment. | Ouvrir un dossier avec le graphe 1 arrêté. |
| 5. Migration des dossiers | Importer lots, pièces, réponses, reçus et états de reprise. Reconstruire explicitement les états historiques incompatibles. | Justifier l’état de chaque dossier et réconcilier les quantités, les preuves et les questions en attente. |
| 6. Parcours complet | Brancher Browsentic, les comptes, Thunderbird et LangSmith. | Réussir les recettes de formulaire inédit, pièces exactes, confirmations inversées, interruption et perte de réponse. |
| 7. Interface web | Refaire le dashboard, les tableaux et les fiches sur les vues PostgreSQL. | Réconcilier graphiques, listes et dossiers sur le même périmètre et valider le parcours mobile. |
| 8. Bascule | Répéter sur copie, arrêter la prise de nouveaux dossiers par l’ancien worker, réconcilier les tentatives en vol, sauvegarder et importer le delta. | Démarrer un seul worker de production après réconciliation. |
| 9. Contrôle et retour arrière | Vérifier tableau, traces et premières reprises. Répéter le retour arrière. | Reporter tout nouveau dépôt et son reçu dans le système repris avant d’autoriser celui-ci à soumettre. |

## 10. Décisions à challenger

1. **Identité d’une candidature.** Comment rapprocher deux URL ou une republication pointant vers la même réquisition employeur ? Quelle information justifie l’ouverture d’un nouveau dossier ?
2. **Preuve de dépôt.** Dans quels cas un reçu, une entrée d’historique, un e-mail ou un simple « Merci » peut-il être attribué avec certitude à l’offre ? Qui résout une ambiguïté durable ?
3. **Droit de reprise.** Comment démontrer que l’ancien tour navigateur ne peut plus envoyer avant d’autoriser son successeur ? Quel contrôle est possible dans le connecteur réel ?
4. **Portée d’un compte et d’une réponse.** Quels fournisseurs partagent une identité entre employeurs ? Quelles réponses exigent une confirmation spécifique au pays, à l’entreprise ou au dossier ?
5. **Dépendances du poste hôte.** Quelles candidatures peuvent progresser si Chrome ou Thunderbird est indisponible ? Comment retrouver la bonne session après son retour ?
6. **Exploitation des documents.** Quels volumes de PDF anticiper et combien de temps prend une restauration complète avec récupération de la clé ?
7. **Feu vert pour la production.** Exiger un parcours depuis le Docker isolé avec offre lue en SQL, formulaire inédit, compte créé ou retrouvé, confirmation e-mail, pièce exacte, interruption, reprise, reçu unique et trace expurgée. Rejouer le cas où le portail accepte le clic puis perd sa réponse.
