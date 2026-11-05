# Deux domaines : publications et candidatures

Ce projet comporte deux processus distincts : [publication LinkedIn](docs/publications/workflow.md) et [candidature aux offres](docs/candidatures/workflow.md). Les sources, validations et historiques de l'un ne s'appliquent pas automatiquement à l'autre.

## Publications

**Brouillon de post** : texte éditorial en préparation. Il n'est ni une publication confirmée ni une réponse de candidature. Un fichier de profil ou des notes de recherche ne sont pas des posts à envoyer.

**Publication LinkedIn** : contenu dont la publication est confirmée, associé à un compte, à une date effective et à un URN LinkedIn.

**Validation éditoriale** : accord explicite sur le texte final, les assets et le destinataire. Elle n'autorise aucune candidature et n'est pas remplacée par un simple drapeau technique.

**Mémoire éditoriale** : `memoire-linkedin.md`, source canonique des faits publiables, de la voix et des règles des posts. Elle ne remplace pas les sources factuelles du dossier candidat.

**Travail sur le profil** : préparation ou modification des rubriques du profil LinkedIn ; activité de support du processus publication, avec validation propre avant modification publique.

## Candidatures

**Offre d’emploi** :
Annonce décrivant un poste ou une mission et les conditions proposées par un recruteur ou un employeur.
_Éviter_ : candidature, dossier.

**Profil candidat** :
Ensemble des faits professionnels du candidat issus de son CV, de son profil LinkedIn et de ses précisions explicites.
_Éviter_ : profil LinkedIn lorsque l’ensemble des sources est visé.

**Dossier de candidature** :
Documents et réponses préparés pour une offre précise, avant leur transmission à son destinataire.
_Éviter_ : candidature envoyée lorsque le dossier est seulement préparé.

**Formulaire employeur** :
Formulaire de candidature accessible sur le site de l’employeur ou sur son service de recrutement.
_Éviter_ : Easy Apply lorsque la candidature se déroule hors LinkedIn.

**Candidature Easy Apply** :
Candidature dont le formulaire est hébergé directement dans LinkedIn.
_Éviter_ : toute candidature issue d’une annonce LinkedIn.

**Mission freelance** :
Prestation professionnelle indépendante recherchée par le candidat, dans les domaines du conseil IA, de l’ingénierie de solutions IA ou de la transformation digitale.
_Éviter_ : emploi salarié lorsque le contrat visé est une prestation indépendante.

**Approbation de candidature** :
Décision explicite du candidat, donnée dans Telegram pour autoriser une candidature individuelle.
_Éviter_ : approbation globale de toutes les offres, absence de refus.

**CV de référence** :
Version fixe du CV utilisée pour les candidatures, présentant Contexte Lab comme activité actuelle et conservant les coordonnées de contact sans adresse précise, date de naissance ni situation familiale.
_Éviter_ : CV personnalisé par offre.

**Synthèse de candidature** :
Présentation du poste et de la réponse préparée, transmise dans Telegram pour permettre au candidat de décider de l’envoi.
_Éviter_ : dossier complet joint, CV joint.

**Approbation expirée** :
Approbation donnée depuis au moins 24 heures sans envoi de la candidature ; une nouvelle décision du candidat est nécessaire.
_Éviter_ : autorisation permanente.

## Conservation des preuves

**Archive de publication** : texte exact, métadonnées de publication et assets conservés après confirmation. Emplacement : `posts/published/AAAA/MM/identifiant/` ; export automatique par la CLI pour les nouvelles publications.

**Archive de candidature** : histoire privée des offres, versions, décisions, pièces et tentatives d'un dossier. La base conserve les nouvelles versions, CV, événements et reçus ; l'export privé est sous `data/candidatures/archives/`. Les anciennes versions perdues avant la migration ne sont pas reconstituées.

**État opérationnel** : données nécessaires à la reprise et à la déduplication. Archiver un résultat ne justifie pas de supprimer cet état.

**Sauvegarde** : copie cohérente permettant une restauration. Elle ne remplace ni les archives métier ni les preuves d'approbation.
