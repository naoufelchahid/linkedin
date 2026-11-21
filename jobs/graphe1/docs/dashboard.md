# Tableau de bord des offres retenues

## Offres et indicateurs

Le tableau présente une ligne par offre retenue et donne accès à une fiche avec le descriptif complet et les données Apify. Une offre reste visible après l’envoi de sa candidature.

La vue d’ensemble compte les offres retenues, celles dans le pipe et celles dont la candidature a été envoyée. Le futur graphe 2 renseignera en base les états de soumission, dont les envois confirmés, les soumissions en cours et les erreurs. Une offre en erreur reste à traiter. En attendant cette source, les indicateurs qui en dépendent sont indisponibles.

## Lancement du graphe 1

La page permet de saisir les paramètres de découverte et de lancer le graphe 1 via le SDK LangGraph. Un cycle utilise un seul lieu, commun à toutes ses recherches. Les favoris préremplissent le formulaire. L’utilisateur peut ajuster les paramètres du cycle et enregistrer explicitement ses changements dans un favori.

Le lieu, la période de publication et la limite par recherche sont communs à tous les mots-clés du cycle. Le formulaire affiche le maximum demandé avant dédoublonnage, égal au nombre de recherches multiplié par la limite par recherche.

La V1 est accessible localement sur la machine qui héberge le graphe 1 et sa base privée.
