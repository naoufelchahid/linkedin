# Tableau de bord des offres retenues

## Offres et indicateurs

Le tableau présente une ligne par offre retenue et donne accès à une fiche avec le descriptif complet et les données Apify. Une offre reste visible après l’envoi de sa candidature.

La vue d’ensemble lit les checkpoints du graphe 2 pour les offres retenues. Une preuve de dépôt en production fait sortir l’offre du pipe et compte une seule fois entre les lots. Une recette ou une erreur laisse l’offre dans le pipe. Les erreurs de traitement, blocages et dépôts à vérifier apparaissent dans les erreurs de soumission. Les indicateurs affichent un tiret si la lecture du graphe 2 échoue.

## Lancement du graphe 1

La page permet de saisir les paramètres de découverte et de lancer le graphe 1 via le SDK LangGraph. Un cycle utilise un seul lieu, commun à toutes ses recherches. Les favoris préremplissent le formulaire. L’utilisateur peut ajuster les paramètres du cycle et enregistrer explicitement ses changements dans un favori.

Le lieu, la période de publication et la limite par recherche sont communs à tous les mots-clés du cycle. Le formulaire affiche le maximum demandé avant dédoublonnage, égal au nombre de recherches multiplié par la limite par recherche.

La V1 est accessible localement sur la machine qui héberge le graphe 1 et sa base privée.

## Liste PostgreSQL

Ouvrir `/dashboard/offres` depuis la navigation du tableau de bord. Définir
`DASHBOARD_POSTGRES_DSN` dans l’environnement du serveur avec un compte dédié
membre de `linkedin_web`. Le rôle accède à la vue `api.offres_web_v1` en lecture.
La recherche porte sur le poste ou l’entreprise. Cycle et dates de collecte
(UTC, bornes inclusives) sélectionnent la dernière observation de chaque offre
dans le périmètre. Les autres filtres portent sur cette ligne. La pagination
conserve les paramètres dans l’URL, par pages de 25 offres.

La recette `db/tests/web_offers.sh` utilise PostgreSQL 17 éphémère et Chrome
headless. Elle vérifie la séparation des droits, le tri, les filtres, les pages
et les cartes mobiles sur les mêmes offres synthétiques.
