# Architecture du graphe 1

LangGraph pilote la collecte, les reprises techniques, la conservation et le classement. Codex via l’App Server reçoit une annonce et le CV de référence et retourne un verdict structuré avec ses preuves. Les adaptateurs Apify, Codex et PDF sont séparés du modèle métier et injectables pour les tests.

Le CV et le prompt sont figés par cycle. Les versions d’annonces, qualifications et tentatives sont conservées dans SQLite. Un verdict est réutilisé quand l’annonce, le CV et le prompt sont identiques. Une modification du prompt est explicite et produit une nouvelle qualification.

Le prompt et le schéma SQL sont embarqués dans le package. Aucun document Markdown ni notebook n’est nécessaire au runtime. Le stockage privé persistant est désigné par la configuration ; son emplacement peut être extérieur au code. Dans cette installation, le lien `var` conserve le chemin de la base et des rapports existants.

Le verrou empêche des exécutions simultanées. Les rapports de revue sont immuables, liés aux versions examinées, et les verdicts humains sont conservés séparément des verdicts Codex. Les erreurs techniques restent distinctes des décisions métier.

Avec `DISCOVERY_POSTGRES_DSN`, le graphe lit et écrit ses cycles, collectes, versions, qualifications, tentatives, corrections et rapports dans le schéma PostgreSQL `discovery`. Il conserve le PDF et son Markdown dans `documents`. Le snapshot SQL du rapport fige les numéros et les versions présentés. La commande `validate-report --report ID` consigne l’accord global explicite dans `pilot_validations`. La commande `review` enregistre chaque correction fournie. Le HTML de présentation reste un fichier privé local.

La recette `db/tests/apify_replay.sh` crée une base PostgreSQL éphémère et exerce le rejeu depuis un second répertoire local avec des adaptateurs synthétiques.

En mode PostgreSQL, la CLI et Studio utilisent le même fil LangGraph, identifié par le cycle. Le rôle de migration installe les tables du checkpointer versionné sous `runtime_g1`. Le worker utilise un checkpoint synchrone entre étapes. La reprise d’une tâche interrompue retrouve ses écritures SQL et le numéro du rapport réservé avant l’étape. Une autre instance peut restituer le HTML dans son propre répertoire et vérifier son empreinte. Après la fin du graphe, un cycle partiel peut relire les runs Apify connus pour intégrer les données tardives. Les cycles historiques dépourvus de fil démarrent depuis leurs faits SQL.
