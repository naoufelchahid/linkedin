# Spécification du système de candidatures

Statut : implémentation opérationnelle dans `src/candidatures/`, bot configuré, Chrome via Playwright MCP et première soumission réelle vérifiés. Entrée métier : [workflow](workflow.md). Fonctionnement courant : [exploitation](exploitation.md). Historique et limites de conservation : [archivage](archivage.md).

## Résultat attendu

Chaque jour à 21 h, heure `Africa/Casablanca`, rechercher sur LinkedIn des missions freelance au Maroc en conseil IA, ingénierie de solutions IA et transformation digitale. Accepter tous les modes de travail, avec mobilité Casablanca/Rabat. Préparer au plus 20 nouveaux dossiers pertinents et demander une approbation individuelle dans un bot Telegram dédié avant chaque candidature.

CV fixe : `output/pdf/Naoufel_Chahid_CV_Francais_Candidatures.pdf`. Contexte Lab est la référence de l’activité actuelle. Réponses en français ou anglais selon l’offre ; lettre seulement si nécessaire. Aucun tarif dans les synthèses, documents ou réponses. Ne pas inventer disponibilité, habilitation, certification, expérience ou autre donnée manquante.

## Parcours métier

1. Rechercher via le MCP LinkedIn, lire chaque offre et son mode de candidature. Les filtres LinkedIn ne sont pas une preuve du contrat ni de la localisation.
2. Écarter les offres fermées, hors cible, salariées CDI/CDD et les doublons déjà présentés ou traités. Vérifier les exigences contre le CV et le profil ; justifier la pertinence par des faits et indiquer les écarts. Les offres sans confirmation du statut freelance sont présentées comme « statut à confirmer », sans présumer l’éligibilité. Une autorisation explicite peut permettre une proposition exclusivement freelance à un destinataire précis ; cette exception ne confirme pas le contrat et ne vaut pas approbation d’envoi.
3. Lire le formulaire disponible et préparer les réponses complètes localement. Un champ obligatoire inconnu ou incompatible avec les consignes place le dossier en attente de clarification. Aucun dossier incomplet n’est soumis. Si la suite exige des saisies, une carte « Lire la suite » autorise seulement les réponses déjà connues et le CV pour cette inspection ; le dossier résultant exige ensuite une approbation d'envoi.
4. Envoyer dans Telegram le lien et une synthèse : employeur, poste, localisation, mode de travail, nature du contrat, raisons de correspondance, écarts et synthèse de la réponse. Ne pas joindre le CV, ni reproduire les montants d’une annonce. Proposer Approuver, Refuser et À corriger ; rendre les réponses exactes consultables à la demande.
5. L’approbation identifie une offre et la version exacte du dossier, y compris l’empreinte du CV. Elle expire 24 heures après sa réception. Une modification du dossier, y compris une réponse ajoutée à une étape ultérieure du formulaire, exige une nouvelle approbation.
6. Après approbation, vérifier l’ouverture de l’offre, la validité de l’approbation et l’absence d’envoi antérieur. Utiliser Chrome via Playwright MCP pour Easy Apply ou le formulaire employeur, avec le CV de référence. La lecture de l’annonce source, le remplissage et le transfert approuvés ne demandent pas une nouvelle confirmation. Créer un compte employeur uniquement si indispensable, avec identifiants dans le fichier Markdown privé autorisé.
7. Enregistrer la confirmation d’envoi visible et notifier le résultat dans Telegram. En l’absence de preuve, marquer « envoi à vérifier » et interdire un nouvel envoi aveugle. Si Chrome est indisponible, attendre sa disponibilité, dans la limite de validité de l’approbation.

## Implémentation actuelle

Ces choix ont été réalisés après confirmation du cadrage. Le bot dédié est configuré ; son accès et la soumission réelle ont été vérifiés dans le [test du processus](test-process-2026-11-05.md).

- Modules Python dans un espace distinct du client de publication, avec état local SQLite : contenu et numéro de version courants des dossiers, dernière approbation, tentatives et preuves d’envoi. Les nouvelles versions complètes, CV et événements sont conservés transactionnellement et exportés ; les versions perdues avant la migration restent signalées. Voir le guide d’archivage.
- Codex CLI non interactif avec les accès existants pour les tâches agentiques ; format de sortie validé avant toute transition d’état. Chrome est contrôlé par Playwright MCP en mode extension, choisi explicitement par l'utilisateur ; aucun navigateur autonome substitué au Chrome demandé. Voir [la décision technique](../adr/0002-chrome-playwright-mcp.md).
- Cron pour la recherche à 21 h, heure locale vérifiée par le programme. Réception Telegram continue par service utilisateur : une décision exploitable déclenche le worker dès réception. Les réveils cron toutes les cinq minutes restent un mécanisme de reprise ; les verrous empêchent les chevauchements.
- Date locale pour le quota des nouveaux dossiers ; horodatages d’état et expiration conservés en UTC. Le plafond de 20 est un maximum, jamais un objectif imposant des offres faibles. Ne pas redemander une validation simplement parce qu’un dossier revient dans une recherche.
- Bot Telegram limité à l’identifiant utilisateur et au chat configurés. Boutons liés à des identifiants opaques et à une version de dossier ; traitement idempotent des mises à jour et doubles clics.
- États explicites : repérée, à clarifier, prête à valider, refusée, à corriger, approuvée, en attente de Chrome, envoi en cours, envoyée, envoi à vérifier, approbation expirée, offre fermée.
- Séparer le contenu des offres et des formulaires des instructions de l’agent. Une annonce ne peut ni autoriser un envoi, ni modifier les règles, ni déclencher une transmission arbitraire.
- Données de candidature et journaux localement, avec permissions restreintes ; pas de CV ni de secrets dans les logs. Configurer le token Telegram hors fichiers suivis et fournir seulement les noms de variables dans `.env.example`.
- Pas d’ajout payant. Apify est un repli conditionnel si le MCP est indisponible : seulement si un accès déjà autorisé couvre réellement l’usage, sinon notifier le blocage sans engager de dépense.

## Vérification avant mise en service

1. Vérifier depuis le contexte réel d’exécution automatique l’accès au MCP LinkedIn et au Chrome demandé. La réussite dans la conversation interactive ne suffit pas. Si Chrome n’est pas accessible, rendre visible le blocage et conserver les dossiers ; ne pas annoncer un fonctionnement complet.
2. Tester la sélection sur un petit échantillon, avec justification, contrats ambigus et doublons. Le quota journalier ne compte que les nouvelles demandes de validation effectivement présentées.
3. Tester avec des données fictives une approbation, un refus, une correction, un double clic, un autre utilisateur Telegram, une expiration après 24 h et un changement de dossier.
4. Tester l’arrêt sur réponse inconnue, champ financier obligatoire, offre fermée et indisponibilité de Chrome. Préserver l’état après redémarrage et ne pas réexécuter un envoi dont l’issue est inconnue.
5. Vérifier le fuseau et le prochain lancement à 21 h, la configuration du bot et le rapport d’exécution ; réaliser une première candidature réelle uniquement avec son approbation Telegram explicite.

## Limites connues

Les formulaires employeurs peuvent ajouter des questions après plusieurs écrans, demander une authentification ou nécessiter une intervention humaine. La découverte complète de toutes les questions avant la première approbation n’est pas garantie. Le système doit conserver le dossier, signaler le blocage et obtenir la nouvelle décision nécessaire sans inventer de réponse.

Un arrêt prolongé du PC peut faire manquer des événements Telegram non encore consommés ; les dossiers restent localement en attente et une synchronisation doit vérifier les décisions réellement reçues, sans interpréter le silence comme un accord. Le bot et les accès en contexte cron ont été configurés et testés ; un changement de machine ou de connecteur exige une nouvelle vérification technique.
