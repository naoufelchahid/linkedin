# Tableau de bord des offres retenues

## Offres et indicateurs

Le tableau présente une ligne par offre retenue et donne accès à une fiche avec le descriptif complet et les données Apify. Une offre reste visible après l’envoi de sa candidature.

La vue d’ensemble lit les checkpoints du graphe 2 pour les offres retenues. Une preuve de dépôt en production fait sortir l’offre du pipe et compte une seule fois entre les lots. Une recette ou une erreur laisse l’offre dans le pipe. Les erreurs de traitement, blocages et dépôts à vérifier apparaissent dans les erreurs de soumission. Les indicateurs affichent un tiret si la lecture du graphe 2 échoue.

## Lancement du graphe 1

La page permet de saisir les paramètres de découverte et de lancer le graphe 1 via le SDK LangGraph. Un cycle utilise un seul lieu, commun à toutes ses recherches. Les favoris préremplissent le formulaire. L’utilisateur peut ajuster les paramètres du cycle et enregistrer explicitement ses changements dans un favori.

Le lieu, la période de publication et la limite par recherche sont communs à tous les mots-clés du cycle. Le formulaire affiche le maximum demandé avant dédoublonnage, égal au nombre de recherches multiplié par la limite par recherche.

La V1 est accessible localement sur la machine qui héberge le graphe 1 et sa base privée.
