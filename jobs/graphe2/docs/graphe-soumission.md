# Graphe 2 — Soumission des candidatures

## Lancement du lot

```mermaid
flowchart TD
    A["Tableau de bord du graphe 1<br/>Choisir un lot et lancer les candidatures"] --> B["Offres retenues en priorité<br/>Offres retenues avec incertitude en dernier"]
    B --> C{"État du dossier partagé entre lots<br/>pour cette offre ?"}
    C -->|Déjà soumise| D["Passer à la suivante"]
    C -->|En attente| E["Conserver la question ou la vérification en cours<br/>Poursuivre les autres offres"]
    C -->|Nouvelle ou prête à reprendre| F["Ouvrir ou reprendre le dossier unique"]
    F --> G{"Parcours indiqué par l’annonce ?"}
    G -->|Easy Apply| H["Session LinkedIn visible"]
    G -->|Site employeur| I["Portail de recrutement"]
    H --> J["Codex App Server avec Browsentic<br/>Remplir le formulaire dans la langue de l’offre"]
    I --> J
```

## Formulaire et reprises

```mermaid
flowchart TD
    A{"Que demande le formulaire ?"}
    A -->|Champ connu| B["Utiliser le CV et les réponses confirmées"]
    A -->|Information manquante| C["Poser la question sur Telegram"]
    C --> D["Envoyer la réponse<br/>avec ou sans mémorisation"]
    A -->|Compte employeur obligatoire| E["Réutiliser la session si possible<br/>Sinon lancer l’agent de compte"]
    E -->|Inscription autorisée| F["Créer le compte et accepter les conditions obligatoires"]
    E -->|Activation reçue| V["Rapprocher le mail avec Thunderbird<br/>confirmer puis se connecter si nécessaire"]
    E -->|Session vérifiée| G{"Accès possible ?"}
    F --> V
    F -->|Aucune activation requise| G
    V --> G
    G -->|Oui| R["Reprendre le formulaire du dossier"]
    G -->|Non| X["Consigner le motif du blocage<br/>Continuer le lot"]
    A -->|CAPTCHA ou code| H["Prévenir sur Telegram<br/>Le candidat intervient dans le navigateur"]
    A -->|Lettre demandée| I["Adapter le canevas Inwi au poste et à la langue<br/>Joindre le PDF"]
    A -->|Prérequis bloquant malgré la réponse exacte| X
    B --> R
    D --> R
    H --> R
    I --> R
    R --> A
    A -->|Formulaire prêt| S["Passer au dépôt"]
```

## Dépôt et mail au recruteur

```mermaid
flowchart TD
    A{"40 dépôts déjà confirmés aujourd’hui ?"}
    A -->|Oui| B["Reporter le dépôt au lendemain"]
    B --> A
    A -->|Non| C["Envoyer le formulaire"]
    C -->|Confirmation reçue| D["Enregistrer la candidature comme soumise en base"]
    C -->|Interruption après le clic| E["Enregistrer « envoi à vérifier »<br/>Consulter le suivi du portail"]
    E -->|Dépôt confirmé| D
    E -->|Doute persistant| F["Consulter le candidat sur Telegram<br/>Continuer les autres offres"]
    F -->|Dépôt confirmé| D
    F -->|Nouvelle tentative autorisée| A
    D --> G{"Adresse de recrutement dans l’annonce ?"}
    G -->|Non| H["Marquer l’adresse « non disponible »"]
    G -->|Oui| I["Rédiger le mail avec Humanizer<br/>Joindre le CV et la lettre PDF de cette offre"]
    I --> J["Vérifier les pièces et présenter le brouillon sur Telegram"]
    J -->|Mail validé| K["Envoyer le mail et enregistrer son statut"]
```

Une attente Telegram suspend uniquement le dossier concerné. Un envoi à vérifier ne réserve aucune place dans le seuil quotidien. Une confirmation tardive peut porter le total au-delà de 40. Le mail de suivi est réservé avant l’appel Thunderbird et n’est pas renvoyé automatiquement s’il reste incertain. Le code actuel ne réconcilie pas cette issue par une recherche dans les messages envoyés. Une interruption avant la soumission de l’inscription peut aussi laisser sa réservation sans reprise en écriture. Pour les autres écarts entre cette vue cible et le code, consulter l’[état de l’implémentation](../README.md#état-du-code).
