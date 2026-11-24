# Conception du graphe 2

Ce document conserve les choix métier cibles. Pour distinguer ces choix du comportement effectivement livré, consulter l’[état de l’implémentation](../README.md#état-du-code) et les écarts listés dans la [spécification](./specification.md).

## Choix du candidat

Les règles de priorité après correction humaine, de dépôt commun à plusieurs annonces, de conservation des pièces, de décompte quotidien et de reprise des envois sont précisées dans la [spécification du graphe 2](./specification.md#règles-de-dépôt-et-de-reprise-validées).

- Suivre chaque offre par sa clé stable `offer_key` à travers tous les lots. Si elle est déjà soumise, passer à la suivante. Si un dossier existe déjà, reprendre son suivi, y compris la question Telegram ou la vérification d’envoi en cours. Deux lots traités en même temps doivent partager ce dossier pour éviter un double dépôt.
- Depuis le tableau de bord du graphe 1, afficher pour le cycle sélectionné le nombre d’offres prioritaires et le nombre d’offres retenues avec incertitude prévues en fin de lot. Le bouton « Lancer les candidatures » démarre ce lot.
- À la fin de la découverte, le candidat choisit le lot et lance son traitement manuellement. Le graphe 2 reprend ensuite ce même lot, y compris le lendemain, sans nouvelle demande de lancement. Chaque nouveau lot attend son propre lancement.
- Traiter les offres par lot de découverte. Le seuil quotidien de 40 s’applique aux dépôts confirmés. Une candidature « envoi à vérifier » ne réserve aucune place. Si sa confirmation ultérieure porte le total du jour au-delà de 40, conserver le total réel.
- Dans chaque lot, traiter d’abord les offres retenues sans incertitude, puis postuler aux offres retenues avec incertitude. Une fois le plafond quotidien atteint, conserver les offres restantes pour la reprise dans le même ordre.
- Sur Easy Apply, Codex doit saisir directement les réponses dans les champs via Browsentic, dans la session LinkedIn visible du candidat. Le candidat souhaite observer la saisie et accepte le risque de restriction de son compte. La compatibilité de bout en bout reste à vérifier.
- Sur les sites employeurs, Codex doit également renseigner le formulaire dans le navigateur.
- Pour le pilote, si un CAPTCHA ou un code de connexion est demandé, mettre le dossier en attente et indiquer au candidat sur Telegram quel portail ouvrir. Le candidat effectue la vérification dans la session visible du navigateur. Reprendre le formulaire après la vérification et poursuivre les autres offres pendant l’attente.
- Réutiliser la session du portail employeur lorsqu’elle est disponible. L’accord permanent du candidat couvre la création du compte nécessaire à la candidature ainsi que l’acceptation de ses conditions obligatoires de service et de confidentialité. Une exclusion explicite enregistrée pour un portail reste prioritaire; les consentements facultatifs restent décochés. Conserver la décision avec le portail concerné et la consulter lors des candidatures suivantes.
- Utiliser le CV et les réponses confirmées. En cas d’information manquante, interroger le candidat sur Telegram. Pour chaque réponse de formulaire, proposer « Envoyer et garder en mémoire » et « Envoyer sans garder en mémoire ». Seul le premier choix autorise la réutilisation sur un autre dossier et l’écriture dans le Markdown privé.
- Lorsqu’une candidature attend une réponse sur Telegram, mettre uniquement cette offre en attente et poursuivre le lot. À réception de la réponse, reprendre la candidature concernée là où elle s’était arrêtée. Si les 40 dépôts du jour sont déjà atteints, conserver la réponse et reporter le dépôt au lendemain.
- Pour un prérequis obligatoire, donner la réponse exacte et poursuivre si le formulaire l’accepte. Si le prérequis empêche le dépôt, enregistrer le motif, garder la candidature non soumise et passer à l’offre suivante. Solliciter le candidat sur Telegram seulement si sa réponse est inconnue.
- Rédiger dans la langue de l’offre, français ou anglais. Lorsque le formulaire demande une lettre, la produire en PDF à partir du canevas et des informations confirmées.
- Après un dépôt confirmé, adresser au recruteur un mail pour appuyer la candidature.
- Si le navigateur s’interrompt après le clic d’envoi et avant la confirmation, enregistrer « envoi à vérifier » et consulter le suivi du portail en lecture seule. Si le dépôt de cette offre y est confirmé, enregistrer « soumise » et passer à l’étape du mail. Si le doute persiste, ne pas relancer automatiquement le dépôt; garder ce dossier à vérifier et poursuivre le reste du lot.
- Utiliser l’adresse de recrutement indiquée dans l’annonce. Si elle manque, marquer l’adresse « non disponible », sans recherche complémentaire. La candidature conserve son statut « soumise » et le lot continue sans envoi de mail pour cette offre.

## Mail au recruteur après dépôt

- Reprendre dans l’objet l’intitulé exact du poste, la référence si l’annonce en fournit une et le nom complet du candidat.
- Rédiger le corps en 4 à 8 lignes dans la langue de l’annonce. Ouvrir sur une mission, un besoin de l’équipe ou un enjeu précis mentionné dans l’offre.
- Choisir une ou deux compétences directement liées à ce besoin. Les illustrer par un outil, une méthode ou un résultat attesté par le CV ou une réponse confirmée du candidat. Éviter de dérouler son parcours.
- Terminer en proposant un échange sur le poste, avec une formule de politesse adaptée au destinataire et la signature du candidat.
- Appliquer le skill Humanizer à chaque brouillon pour obtenir un mail naturel et concis. Après révision, contrôler l’orthographe, l’exactitude des faits, la langue et la longueur. [Consignes du skill](https://github.com/blader/humanizer/blob/main/SKILL.md)
- Joindre à chaque mail le CV de référence et la lettre de motivation en PDF personnalisée pour cette offre. Réutiliser la lettre déposée sur le portail. Si le portail ne demandait aucune lettre, la produire pour le mail dans la langue de l’offre.
- Avant l’envoi, vérifier que les deux fichiers sont joints et lisibles, et que la lettre correspond au poste et à l’employeur.

## Canevas de la lettre de motivation

Le candidat a choisi la [lettre Inwi](../../../lettre-motivation-inwi-transformation-digitale.docx) comme modèle de rédaction et de présentation. Pour chaque offre, le rédacteur Codex travaille sur une copie du DOCX, adapte son contenu et sa mise en page, exporte la lettre en PDF et vérifie le document rendu.

- Conserver le titre, l’objet, la salutation et la signature. Adapter la langue, le destinataire, l’intitulé du poste et la qualité professionnelle indiquée dans la signature à partir d’informations confirmées.
- Adapter l’objet, l’accroche et la conclusion au type de poste annoncé. Pour un emploi salarié, présenter la candidature au poste et expliquer la contribution envisagée au sein de l’équipe. Pour une mission freelance, proposer une intervention sur les objectifs décrits par le client. Si l’annonce ne précise pas le type de contrat, reprendre l’intitulé et les missions avec une formulation neutre.
- Suivre la progression de la lettre : motivation pour le poste, expérience pertinente, manière d’aborder la mission, prise en compte des équipes concernées, contribution envisagée, puis invitation à échanger et formule de politesse.
- Fonder les passages sur le candidat sur le CV de référence et ses réponses confirmées. Adapter les passages sur l’employeur aux missions décrites dans l’annonce. Les mentions d’Inwi, du statut freelance et de la transformation IA sont propres à l’exemple et ne sont reprises que si elles conviennent à l’offre.
