# Système de candidatures — cadrage historique

Date : 5 novembre 2026.
Statut : cadrage confirmé par l'utilisateur (« oui »). Implémentation locale et cron installés ; Telegram et Chrome via Playwright MCP vérifiés. Traitement des envois activé sous validation individuelle Telegram. Première candidature Keyrus envoyée et confirmée le 5 novembre 2026.

Ce document conserve l’entretien et les constats initiaux. Pour le fonctionnement courant, lire le [workflow](workflow.md) et le [guide d’exploitation](exploitation.md). Les limitations des tableaux historiques ne sont pas des consignes de mise en service actuelles.

## Demande explicite

Créer un système agentique qui trouve des offres adaptées au CV et au profil LinkedIn, prépare les candidatures et les exécute, y compris sur les formulaires employeurs avec Chrome. Priorité au MCP LinkedIn ; recours à un Actor Apify si le MCP ne permet pas la recherche.

L’entretien a procédé par séries de décisions. Les décisions techniques durables sont conservées dans `docs/adr/`.

## Sources et constats initiaux

- CV : `data/candidatures/references/cv/Naoufel_Chahid_CV_Francais.pdf`, deux pages lisibles. Consultant en transformation IA ; activité freelance IA depuis janvier 2025 ; chef de département Solutions et Développement chez Groupe Safari / SMCV de septembre 2012 à septembre 2024.
- Profil actuel lu via `get_my_profile` : https://www.linkedin.com/in/naoufel-chahid/ . Titre orienté transformation IA, LLM, GraphRAG, agents et intégration ERP. Expérience actuelle : consultant en transformation IA et développeur de solutions IA chez Contexte Lab depuis janvier 2025.
- Le CV initial mentionne Upwork pour l’activité récente ; LinkedIn présente Contexte Lab. L’utilisateur a confirmé Contexte Lab comme référence et demandé la correction du CV. Intitulé : « Consultant IA freelance et développeur de solutions IA | Contexte Lab ». La version finale de candidature est `output/pdf/Naoufel_Chahid_CV_Francais_Candidatures.pdf` : adresse précise, date de naissance et situation familiale retirées ; ville, email et téléphone conservés ; mobilité Casablanca/Rabat et modes de travail ajoutés conformément aux réponses utilisateur. Deux pages contrôlées visuellement ; colonne professionnelle et seconde page identiques au rendu précédent pixel par pixel. Sources précédentes conservées.
- Le fichier local `references/publications/profil/profile.json` est orienté fondateur et développement commercial. Il ne remplace pas le profil actuel observé.
- Les douze années d’expérience concernent les solutions d’entreprise, pas douze années d’IA. Les attestations Udemy ne sont pas des certifications professionnelles AWS obtenues.
- Avant cette implémentation, le dépôt contenait un client de publication/statistiques LinkedIn et aucun système de candidature n’avait été repéré.

Rappel MemPalace, cité verbatim pour préserver la portée de la décision passée : « Précision utilisateur : « garder contexte lab uniquement ». Contexte Lab est conservé comme seule activité actuelle ; aucune expérience Upwork n’a été ajoutée. » Cette décision portait sur la mise à jour du profil LinkedIn ; elle ne résout pas à elle seule la formulation des nouveaux dossiers.

## Capacités observées avant l’implémentation

| Capacité | État observé | Limite |
| --- | --- | --- |
| Lecture du profil LinkedIn | Exécutée avec succès | Lecture bornée à deux défilements par section ; compétences potentiellement partielles |
| Recherche d’offres MCP | Test réel réussi : « consultant IA freelance Maroc », dernière période d’un mois, une page | 27 résultats annoncés, 25 identifiants récupérés ; `filters_dropped` pour `f_JT` et `location`. Résultats élargis avec des CDI : statut et géographie à vérifier offre par offre |
| Détail et destination de candidature | `get_job_details`, `get_job_apply_url` exposés | Non encore testés sur une offre |
| Lecture Easy Apply | `get_easy_apply_form` exposé | Lecture seulement ; arrêt au premier écran exigeant une réponse, puis abandon du brouillon |
| Soumission par le MCP LinkedIn | Aucun outil de candidature exposé | À distinguer des outils de messagerie |
| Chrome | Connexion établie | Aucun formulaire employeur ni téléversement testé |
| Apify | Aucun connecteur exposé dans cette session | Disponibilité d’un compte/API/Actor non vérifiée ; aucun lancement effectué |
| Exécution planifiée | Codex CLI 0.166.0 et cron présents ; service cron actif | Aucun lancement réel depuis cron ni accès aux outils dans ce contexte encore testé ; Node est installé via nvm et exige un PATH explicite |
| Telegram | API officielle compatible boutons et callbacks ; aucune intégration locale trouvée | Bot et destinataire à configurer ; aucun message envoyé. Un consommateur distinct doit recevoir les validations entre deux recherches quotidiennes |

L’API Telegram conserve les événements non consommés au maximum 24 heures : une réception une fois par jour est fragile. La spécification propose une réception toutes les cinq minutes, distincte du lancement quotidien à 21 h. Sources : https://core.telegram.org/bots/api ; https://learn.chatgpt.com/docs/non-interactive-mode .

La connexion Chrome de la conversation interactive ne prouve pas l’accès depuis un futur processus cron. Le test de ce parcours est un préalable à la mise en service de l’envoi automatique après approbation.

## Arbre de décisions

Première série, décisions utilisateur :

1. Marché : Maroc ; ouverture à une relocalisation à Casablanca ou Rabat ; télétravail, hybride et présentiel acceptés.
2. Autonomie : validation de chaque candidature dans Telegram.
3. Déclenchement : exécution quotidienne par cron.
4. Cibles : conseil IA, ingénierie de solutions IA et transformation digitale, en freelance.
5. Profil : Contexte Lab comme référence, avec correction du CV explicitement demandée et réalisée.

Deuxième série, décisions utilisateur :

6. Tous les modes de travail sont acceptés. Aucun tarif n’est évoqué, affiché ou proposé par le système ; aucune sélection selon un tarif minimum. Une question financière obligatoire bloque le formulaire sans valeur inventée ni réponse de contournement. Au moment du cadrage, date de démarrage et capacité hebdomadaire étaient inconnues. La disponibilité a ensuite été confirmée dans le test : « Disponible immédiatement, sans préavis ». La capacité hebdomadaire n’est pas à inventer.
7. Recherche quotidienne à 21 h, fuseau `Africa/Casablanca` (heure locale, pas décalage UTC figé).
8. Bot Telegram dédié ; synthèse du poste et de la réponse, sans joindre le CV.
9. Au plus 20 nouveaux dossiers pertinents par jour ; aucun remplissage artificiel du quota.
10. Recommandations acceptées : exclure CDI/CDD, présenter les statuts incertains, bloquer les réponses inconnues ; nouvelle validation si le dossier change ; vérifier un envoi incertain avant toute tentative supplémentaire.
11. Recommandations acceptées pour les réponses et lettres : langue de l’offre, lettre seulement si nécessaire, aucun fait inventé ; retrait des informations personnelles non professionnelles du CV. La consigne spécifique Q8 « il sera toujours le meme » prévaut sur la proposition antérieure d’adapter le CV par offre : un seul CV français de référence, réponses personnalisées FR/EN.

Troisième série, décisions utilisateur :

12. Utiliser ce PC ; l’utilisateur confirme sa disponibilité à partir de 21 h avec sa session et Chrome ouverts. Attente si Chrome est indisponible.
13. Accès existants uniquement, aucun nouveau service payant. Aucun budget API/Apify supplémentaire autorisé. Ne pas supposer qu’un Actor est gratuit : un repli consommant des crédits non déjà autorisés reste bloqué jusqu’à clarification.
14. Approbation valable 24 heures, puis nouvelle validation ; offre ouverte et dossier inchangé vérifiés avant envoi.

## Résultat et références actuelles

Le code, le cron et la réception Telegram continue sont installés. Le défaut initial du connecteur Chrome a été résolu pour le workflow par le passage à Playwright MCP, à la demande de l’utilisateur. La première candidature réelle Keyrus a été envoyée et confirmée après approbation Telegram.

- [Workflow courant](workflow.md)
- [Spécification](specification.md)
- [Exploitation](exploitation.md)
- [Historique du diagnostic](validation-2026-11-05.md)
- [Test réel et confirmation d’envoi](test-process-2026-11-05.md)
- [Archivage et limites historiques](archivage.md)
