# Graphe 2 — Soumission des candidatures par lot

Status: ready-for-agent

## Problem Statement

Après la qualification, le candidat dispose d’un lot d’offres retenues. Il doit encore remplir des formulaires différents, retrouver les pièces appropriées et suivre les dépôts sur plusieurs sites. Une interruption après le clic final peut conduire à candidater deux fois. Une question sans réponse sur une offre peut retarder toutes les autres.

## Solution

Le candidat choisit un lot de découverte dans le tableau de bord et clique sur « Lancer les candidatures ». Le graphe 2 traite Easy Apply et les portails employeurs, réutilise les réponses confirmées et conserve la progression de chaque dossier. Une confirmation de dépôt fait sortir l’offre du pipe. Lorsqu’une adresse de recrutement figure dans l’annonce, le candidat reçoit sur Telegram un mail d’appui à valider, avec son CV et sa lettre.

## User Stories

1. En tant que candidat, je veux voir combien d’offres sont prioritaires et combien sont retenues avec incertitude afin de choisir le lot à lancer.
2. En tant que candidat, je veux lancer explicitement chaque nouveau lot afin de garder la main sur les offres traitées.
3. En tant que candidat, je veux que mon verdict individuel prime et que les offres retenues avec incertitude passent en dernier afin de traiter d’abord les correspondances établies.
4. En tant que candidat, je veux retrouver un seul dossier par offre, même entre lots simultanés, afin d’éviter les doubles dépôts.
5. En tant que candidat, je veux voir Codex renseigner Easy Apply dans ma session LinkedIn et remplir les formulaires externes afin de pouvoir suivre la saisie.
6. En tant que candidat, je veux réutiliser ma session employeur et décider une seule fois par portail si une inscription indispensable est permise afin de limiter les sollicitations.
7. En tant que candidat, je veux être averti sur Telegram lorsqu’un CAPTCHA ou un code apparaît afin de le traiter moi-même dans le navigateur.
8. En tant que candidat, je veux que l’agent utilise mon CV de référence et mes réponses confirmées afin que mes déclarations soient exactes.
9. En tant que candidat, je veux recevoir sur Telegram les questions indispensables encore sans réponse et conserver mes réponses avec leur contexte afin de pouvoir les réutiliser.
10. En tant que candidat, je veux que les autres offres avancent pendant mon absence et que le dossier reprenne au bon endroit à ma réponse.
11. En tant que candidat, je veux connaître le prérequis qui empêche un dépôt afin de comprendre pourquoi une offre retenue reste dans le pipe.
12. En tant que candidat, je veux une lettre PDF dans la langue de l’offre, adaptée au poste, à l’employeur et au type de contrat, afin de joindre une pièce appropriée.
13. En tant que candidat, je veux que les nouveaux dépôts reprennent le lendemain lorsque 40 dépôts sont confirmés pour la journée afin de répartir le lot dans le temps.
14. En tant que candidat, je veux qu’un envoi incertain reste à vérifier, sans réserver une place dans le seuil, afin de poursuivre les offres restantes.
15. En tant que candidat, je veux que l’agent consulte le suivi du portail après un clic au résultat inconnu et me consulte si le doute persiste afin d’éviter un nouvel envoi accidentel.
16. En tant que candidat, je veux que la base et le tableau reflètent le dépôt confirmé, y compris après une confirmation tardive, afin de connaître le total réel.
17. En tant que candidat, je veux un mail d’appui personnalisé pour le recruteur indiqué dans l’annonce et la mention « non disponible » quand son adresse manque afin de savoir quelles candidatures ont pu être accompagnées.
18. En tant que candidat, je veux vérifier le brouillon sur Telegram avant son envoi afin de maîtriser le message adressé en mon nom.
19. En tant que candidat, je veux que le mail contienne le CV de référence et la bonne lettre de motivation, même si le portail n’a demandé aucune lettre.
20. En tant que candidat, je veux que l’échec éventuel du mail soit suivi séparément afin de conserver la preuve du dépôt et d’éviter une nouvelle candidature.
21. En tant que candidat, je veux essayer les deux parcours dans les conditions réelles de production, jusqu’à la dernière étape du formulaire et à la préparation du mail, afin de juger le fonctionnement avant tout envoi.

## Implementation Decisions

- Le tableau de bord reprend la sélection du cycle de découverte et le verdict applicable à la version examinée. Le lancement autorise le traitement et les reprises de ce lot. Chaque nouveau lot requiert son propre lancement.
- LangGraph orchestre les dossiers. Codex App Server utilise Browsentic pour la saisie directe. La session LinkedIn reste dans le profil visible du navigateur. Les annonces et les documents fournissent des données. Les instructions d’action proviennent du graphe et du candidat.
- SQLite conserve l’appartenance aux lots, le dossier partagé par clé stable d’offre, la version examinée, les tentatives, les attentes en cours, les confirmations et le suivi du mail. Une reprise, un double clic ou deux lots concurrents doivent retrouver le même dossier. Une seule tentative de dépôt peut être active pour cette offre.
- Un besoin d’intervention suspend le dossier concerné. Lier chaque réponse Telegram à sa question, à son dossier et, pour une inscription, au portail concerné. Conserver les réponses réutilisables dans un fichier Markdown privé avec leur portée. Les secrets de connexion et les codes à usage unique restent hors de cette mémoire.
- Fournir la réponse exacte à un prérequis et poursuivre si le site l’accepte. Si le formulaire empêche le dépôt, garder le motif et le statut non soumis. Enregistrer séparément les problèmes techniques et le verdict de qualification d’origine.
- Avant un dépôt, consulter le total quotidien de candidatures confirmées, tous lots confondus. À 40 ou plus, reporter les prochains dépôts au lendemain en conservant leur ordre. Un envoi à vérifier ne réserve aucune place. Enregistrer intégralement une confirmation tardive, même si le total passe à 41.
- Après une interruption susceptible de suivre le clic final, consulter d’abord le suivi du portail. Une réception attestée marque l’offre « soumise » une seule fois. En cas de doute persistant, attendre la décision sur Telegram avant toute nouvelle tentative. La reprise du mail ne relance jamais le formulaire.
- Rédiger en français ou en anglais selon l’annonce. Personnaliser une copie du canevas Inwi et produire un PDF. Adapter l’objet, l’accroche, les expériences attestées, la contribution et la conclusion. Distinguer emploi salarié et mission freelance. Quand l’offre ne précise aucun contrat, employer une formulation neutre.
- Utiliser exclusivement l’adresse de recrutement indiquée dans l’annonce. Si elle manque, enregistrer « non disponible » et poursuivre. Sinon, l’objet du mail indique l’intitulé exact du poste, la référence éventuelle et le nom complet du candidat. Le corps de 4 à 8 lignes relie un besoin de l’offre à une ou deux compétences attestées et propose un échange.
- Appliquer Humanizer à chaque brouillon, contrôler l’orthographe et l’exactitude, puis vérifier les deux pièces jointes, leur lisibilité et leur correspondance avec le dossier. Réutiliser la lettre déposée ou la produire pour le mail. Après validation du brouillon par le candidat sur Telegram, envoyer le mail au recruteur et enregistrer le résultat.

## Testing Decisions

**Recette validée par le candidat.** Utiliser un seul point d’entrée, le lancement puis la reprise d’un lot depuis le tableau de bord. Exécuter le graphe avec Codex App Server, Browsentic, la session LinkedIn, les formulaires employeurs, le CV et le canevas de référence, la mémoire privée, Telegram et la préparation du mail dans les conditions réelles de production. Choisir des offres réelles couvrant Easy Apply et un portail externe. Observer les effets depuis le navigateur, Telegram, les pièces produites et le tableau de suivi.

**Arrêt de l’essai.** Sur chaque formulaire, atteindre la dernière étape sûre et relever les pièces et réponses préparées. Si une action intermédiaire peut également transmettre la candidature, s’arrêter avant cette action. Pour tester le mail, ouvrir un aperçu ou un brouillon d’essai à partir du dossier préparé. Même une validation du brouillon pendant la recette ne déclenche aucun envoi. Les reprises, y compris le lendemain, conservent cette limite. Distinguer le suivi d’essai du suivi des dépôts réels. Un dossier arrêté avant envoi reste dans le pipe, ne compte pas dans le seuil et reste disponible pour un dépôt ultérieur.

| Parcours réel | Observation attendue |
| --- | --- |
| Lancer un lot et reprendre une offre présente dans deux lots | Les compteurs correspondent à la sélection du cycle. Les offres prioritaires précèdent les incertaines. Un seul dossier est préparé par offre. |
| Renseigner Easy Apply puis un portail externe | La saisie est visible, les réponses sont exactes et les pièces correspondent au poste. L’essai s’arrête avant la transmission finale sur les deux parcours. |
| Répondre à une question sur Telegram puis reprendre le lot | Les autres offres disponibles avancent. La réponse réactive le bon dossier, survit au redémarrage et reste réutilisable dans son contexte. |
| Rencontrer un prérequis bloquant, une inscription obligatoire ou une vérification humaine | Observer la branche effectivement rencontrée. L’agent respecte le fait déclaré, la décision propre au portail et l’intervention du candidat dans le navigateur. |
| Préparer les documents et le mail d’essai | Vérifier la langue, la personnalisation et le PDF rendu. Si l’annonce fournit une adresse, examiner le brouillon avec le CV et la lettre joints. Sinon, vérifier la mention « non disponible ». |
| Terminer ou reprendre une recette | Aucun formulaire déposé, aucun mail expédié, aucune candidature marquée soumise et aucun dépôt ajouté au décompte quotidien du fait de l’essai. |

Les tests existants du graphe 1 fournissent des précédents pour vérifier la sélection humaine, la déduplication, une reprise après panne et une opération externe à l’issue inconnue. La recette du graphe 2 repose sur les parcours réels. Consigner comme non observées les branches absentes des offres essayées. La réception par le portail, une interruption après dépôt, la confirmation tardive et la livraison effective du mail restent des critères du fonctionnement en production. Un essai arrêté avant envoi ne peut pas les attester.

## Out of Scope

Le pilote ne modifie pas les règles de qualification du graphe 1. La recherche d’adresses de recruteurs, les séquences de relance, la résolution automatisée des CAPTCHA et l’activation de services système sont hors périmètre.

## Further Notes

Le candidat a validé le graphe Mermaid présenté en HTML. Ses trois vues couvrent le lancement du lot, le remplissage et les reprises, puis le dépôt et le mail au recruteur. La compatibilité de Browsentic avec les formulaires réels sera vérifiée pendant la recette. Les pièces personnelles, cookies et réponses du candidat restent dans le stockage privé.
