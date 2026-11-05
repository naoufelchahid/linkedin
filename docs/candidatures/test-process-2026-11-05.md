# Essai réel du processus de candidature

**Résultat final :** candidature Keyrus envoyée et confirmée, notification Telegram livrée. Les étapes ci-dessous sont chronologiques ; les états bloqués et en attente décrivent des étapes intermédiaires.

Essai demandé le 5 novembre 2026, limité initialement à un dossier. La recherche quotidienne de 21 h n'a pas été marquée comme exécutée par ce test.

## Parcours observé

1. Notification de démarrage envoyée dans le bot Telegram configuré.
2. Lecture du CV fixe et du profil LinkedIn, puis recherche réelle via les connecteurs.
3. Sélection de [AI Architect freelance, Infomineo, Casablanca](https://www.linkedin.com/jobs/view/4484363233/).
4. Lecture du [formulaire employeur Workable](https://apply.workable.com/infomineo/j/241D504E12/apply/) dans Chrome via Playwright MCP, sans saisie ni téléversement.
5. Préparation des réponses sourcées et présentation de la carte Telegram du dossier `2d53644dd0f1`, version 1. Livraison confirmée par l'API et enregistrée localement.
6. Dossier conservé en état `blocked` : le formulaire comporte des champs obligatoires non résolus, dont un incompatible avec les consignes. Aucune approbation ni tentative de soumission créée.

## Précision apportée pendant le test

L'utilisateur a confirmé : « Disponible immédiatement, sans préavis ».

Cette précision est enregistrée dans le fichier local privé `data/candidatures/candidate_facts.json`. Les nouveaux workers la reçoivent comme fait sourcé ; elle ne modifie ni le CV fixe ni les réponses d'une candidature déjà approuvée. Les tests du worker et du domaine passent : 48 tests ciblés après cette modification.

## État intermédiaire après le premier dossier

À cette étape, le parcours jusqu'à la présentation Telegram et l'arrêt avant envoi étaient observés en conditions réelles. La transmission du CV et la soumission finale ont été vérifiées ensuite, avec le dossier Keyrus décrit ci-dessous.

## Deuxième dossier : Keyrus

La recherche complémentaire a examiné six offres détaillées et préparé [Business Value Advisor à Casablanca, Keyrus](https://www.linkedin.com/jobs/view/4482999509/), dossier `3bd0535ec6af`. Le formulaire employeur est entièrement observable. Son contrat n'est pas précisé : le système conserve `contract=uncertain`.

Pour cette offre seulement, l'utilisateur a répondu « Oui, proposer uniquement du freelance ». Une exception locale lie cette autorisation au dossier, à l'employeur et à la destination observée. Elle exige une lettre mentionnant le freelance et ne vaut pas approbation d'envoi. Les autres dossiers au contrat incertain restent bloqués. Le contrôle est renouvelé avant la soumission ; un autre destinataire, une autorisation révoquée ou d'autres champs non résolus empêchent l'envoi.

L'utilisateur a également répondu « Oui, j’ai lu et j’autorise » pour la case obligatoire de prise de connaissance de la politique de données Keyrus. L'entrée consultable est `https://jobs.keyrus.tn/data-privacy` ; le lien observé dans la case du formulaire est `https://jobs.keyrus.fr/privacy-policy`. Le libellé exact de cette case et la source de l'accord sont conservés dans le dossier privé.

La version 3 a été présentée dans Telegram : proposition exclusivement freelance, disponibilité immédiate sans préavis, CV fixe, coordonnées, lettre et case obligatoire. À cette étape, aucun blocage ne restait ; le dossier était `pending`, en attente du clic Telegram sur « Approuver ». Les anciennes cartes ne peuvent approuver cette version.

Les 59 tests passent après ajout du contrôle de cette exception et de son périmètre.

## Soumission réelle réussie

L'approbation Telegram de la version 3 a été reçue à `2026-11-05T14:01:10.942465+00:00`. Une première tentative s'est arrêtée avant toute saisie en demandant inutilement la permission de lire l'annonce LinkedIn déjà incluse dans le dossier. La consigne du worker a été corrigée pour autoriser explicitement le recoupement de l'annonce source et du formulaire employeur sans nouvelle demande.

À la demande du candidat de poursuivre directement, la même version inchangée a repris sur son approbation Telegram encore valide, après contrôle du CV, de l'empreinte et du compte rendu attestant l'absence de saisie ou soumission précédente. Cette reprise ciblée est enregistrée dans l'audit local ; aucun résultat incertain n'a été réessayé.

La seconde tentative est terminée en état `sent`. Le CV et la lettre approuvés ont été transmis et la soumission effectuée une seule fois. Confirmation observée sur le site Keyrus :

> Thanks for applying
> We have received your application and we will be reviewing it shortly.

L'URL privée de confirmation est conservée dans la base locale, sans être recopiée dans cette documentation. Le résultat est transmis au bot Telegram.

Le candidat a également autorisé la création des comptes employeurs nécessaires et demandé la conservation de leurs identifiants dans un fichier Markdown. Le fichier privé `data/candidatures/accounts.md` a été préparé à cet effet. Le service utilisateur de réception Telegram continue est installé et actif pour déclencher immédiatement les prochains dossiers approuvés ; le cron quotidien est conservé. Les 60 tests passent, dont le contrôle du déclenchement uniquement après approbation et sans second worker concurrent.
