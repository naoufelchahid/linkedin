# Vérification de la consolidation — 20 novembre 2026

Le graphe 1 validé est regroupé dans `jobs/graphe1/`, sous le package `linkedin_discovery` version `1.0.0`. L’installation de référence utilise Python 3.12.3.

## Contrôles réussis

- **37 tests du package** : métier, déduplication, reprise, preuves, rapports, configuration, verrou, budget de tentatives, planification quotidienne, sauvegardes, erreurs réseau et codes de sortie.
- **206 tests sur le dépôt complet**, incluant les anciens points d’entrée et les processus existants.
- Ruff : lint et formatage conformes.
- Wheel et archive source construites. Prompt et schéma SQL présents dans la wheel ; verrou, guide d’exploitation et unités de déploiement présents dans l’archive source.
- Contrôle des distributions : aucun fichier `.env` privé, CV, base SQLite ou rapport utilisateur.
- Installation de la wheel dans un environnement virtuel neuf, avec dépendances de production verrouillées et empreintes vérifiées. Exécution du vrai graphe avec adaptateurs de test depuis un répertoire extérieur au dépôt, sous Python isolé : rapport généré avec succès.
- Diagnostic local : accès Apify et LangSmith configurés, CV existant, Codex et `pdftotext` disponibles ; même chemin de données qu’avant la consolidation.
- Compatibilité : `jobs/decouverte.py` et `python -m src.candidatures.discovery` délèguent au package canonique.
- Unités systemd : vérification statique réussie ; calendrier `21:00:00 Africa/Casablanca` reconnu.

## Reprise du lot validé

Une copie privée de l’état réel a été rejouée avec les adaptateurs réseau remplacés par des objets qui refusent tout appel. Résultat : **203 annonces, 200 verdicts réutilisés et trois erreurs conservées, zéro appel Apify ou Codex**. Le prompt embarqué a la même empreinte que celui du cycle validé. L’empreinte du rapport humainement validé est inchangée.

La base réelle, le CV, les rapports et le reçu restent à leurs emplacements d’origine. L’ouverture du stockage autonome enregistre le schéma compatible en version 1. Les chemins d’accès via les liens locaux du projet résolvent vers les mêmes fichiers.

## Sauvegardes

La sauvegarde préalable du workspace, `backups/20261120T145427992121Z/`, a été restaurée temporairement et vérifiée.

La commande autonome `backup` a produit `jobs/graphe1/backups/discovery-20261120T150914802192Z.tar.gz` : cinq fichiers d’état, comprenant base cohérente, snapshot du CV, rapports et reçu. Les empreintes et l’intégrité de la base restaurée ont été vérifiées.

## Portée de livraison

La distribution et les fichiers d’exploitation sont prêts. Aucun nouveau run Apify réel ni nouvelle qualification facturée n’a été lancé pour la consolidation. Les services et le cron existants n’ont pas été modifiés ; les nouvelles unités ne sont pas activées. Le comportement métier conserve les décisions validées du graphe 1.

## Vérification après recentrage global du dépôt

Après retrait des anciens processus, la suite active comprend **40 tests réussis** : les 37 tests métier et d’exploitation du package et les trois tests de compatibilité. Les tests propres aux anciens processus sont archivés avec leur code.

Le lot réel est rejoué sur une copie privée de l’état après nettoyage : 203 annonces, 200 verdicts réutilisés et trois erreurs conservées, sans appel externe. Les compteurs des tables actives et les empreintes du CV, de la configuration et des rapports sont inchangés. Les tâches cron retirées sont exactement celles de l’ancien lanceur ; les autres tâches sont conservées. L’unité du listener historique est arrêtée puis archivée.

Les éléments retirés, le crontab précédent, l’unité retirée et les sauvegardes complètes sont conservés sous `/home/naoufel/projects/linkedin-archives/20261120T152627Z-root-cleanup/`.

## Test réel après transfert — 20 novembre 2026

- Diagnostic local réussi et **40 tests actifs réussis** (`python -m pytest -q tests jobs/graphe1/tests` depuis la racine, avec le Python du package).
- Un seul nouveau run Apify : `EQQ0ATwTXsGiIgYeY`, recherche `architecte solutions IA`, Maroc, sept jours, limite 10. Collecte réussie en 6,30 secondes, 10 offres ; cycle `b366b978acfb41c2b456836272bbc555`.
- Le passage sur l’état actif réutilise neuf verdicts et une erreur historique au budget épuisé ; il retourne donc le code 3 avec `--fail-on-errors`. Aucun appel Codex neuf sur ce premier passage.
- Les dix annonces collectées sont ensuite injectées dans un stockage privé neuf sous `data/candidatures/smoke-tests/post-transfer-10-q_37fwj4/`, avec le CV et le prompt configurés. L’adaptateur Apify est remplacé par un garde qui interdit tout appel supplémentaire.
- Ce rejeu sans cache produit **10 qualifications réussies, 10 tentatives Codex réelles, aucune erreur de qualification**, en 78,13 secondes. Cycle isolé : `5a6a92480bf34ff880e1a2a805a6bd0a`.
- Le montage de test référençait initialement le cycle source absent de la base isolée, ce qui a empêché la première génération du rapport. Après correction de cette référence dans l’état de test uniquement, le rapport est généré avec les adaptateurs Apify et Codex interdits, sans nouvel appel fournisseur.
- Rapport privé : `data/candidatures/smoke-tests/post-transfer-10-q_37fwj4/reports/9f2e1236b85e44a1a1b147b3c8bf4c63.html`. Compteurs et durées : `smoke-result.json` dans le même stockage de test.

Ce test vérifie l’exécution locale après transfert. Aucune image Docker n’a été construite ni exécutée ; aucun service n’a été activé. Le code runtime, le prompt et la configuration persistante n’ont pas été modifiés.

## Entrées/sorties LangSmith et Studio — 20 novembre 2026

La demande suivante de visibilité dans LangSmith entraîne une modification de l’instrumentation : `DISCOVERY_TRACE_CONTENT=true` active les traces natives du graphe et les entrées annonce/CV/prompt et sorties des qualifications. Le mode technique historique reste le défaut ; la configuration privée de cette installation active explicitement le mode détaillé. Le prompt et les règles de qualification restent identiques.

- **42 tests réussis**, dont deux nouveaux contrôles de l’arbre de traces avec entrées/sorties et du cycle de vie Studio ; Ruff conforme et verrou de dépendances vérifié.
- Reprise locale des dix offres du stockage de test, sans nouvel appel Apify ou Codex : dix verdicts réutilisés, rapport généré. Lecture distante de la trace `01a1f9ac-7b33-7477-a0d6-5793b42cc618` dans `linkedin-discovery-pilot` : racine `graphe1.discovery`, enfants `collect`, `qualify`, `report`, dix enfants `qualification.cache` avec annonce/CV/prompt en entrée et verdict en sortie. Les anciennes traces techniques ne sont pas modifiées.
- `langgraph.json` expose la factory `linkedin_discovery.studio:make_graph`. Le groupe optionnel `studio` verrouille les dépendances du serveur de développement ; aucune nouvelle dépendance de production n’est requise.
- Démarrage réel du serveur local sur `127.0.0.1:2024`, inspection de la topologie via l’API : `START → collect → qualify → report → END`.
- Serveur temporaire distinct sur le port 2025, dirigé vers le stockage de test : appel réel `/runs/wait` avec le cycle isolé, dix qualifications réutilisées et nouveau rapport généré. Cela vérifie aussi les accès SQLite depuis les threads du serveur et la fermeture des ressources. Aucun nouvel appel fournisseur pendant cette reprise.

Documentation officielle consultée : [tracing sans variables globales](https://docs.langchain.com/langsmith/trace-with-langchain#trace-without-setting-environment-variables), [factory avec cycle de vie](https://docs.langchain.com/langsmith/graph-rebuild#context-manager-factory), [configuration Studio](https://docs.langchain.com/oss/python/langchain/studio#4-create-a-langgraph-config-file).
