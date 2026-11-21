# Construire le graphe 2

Le candidat a validé ce guide de construction le 21 novembre 2026. La recette décrite dans la [spécification](./specification.md#testing-decisions) permettra de vérifier l’implémentation.

Le point d’entrée est le bouton « Lancer les candidatures ». Le tableau enregistre le lot explicitement autorisé et réveille un processus Python local. Ce processus continue lorsque le candidat ferme la page. Sa relance retrouve les lots déjà démarrés et reprend chaque dossier à partir de son checkpoint. Le mode recette ou production accompagne toute reprise.

## De la collecte au fil LangGraph

Le graphe 1 compare le champ `url` de la page LinkedIn pour Easy Apply et External. Deux lots qui contiennent la même page référencent le même dossier et le même `thread_id` LangGraph. En parcours externe, le navigateur part de cette page puis suit « Postuler ». La conversation d’un agent Codex peut prendre fin et être recréée pendant la vie du fil. [Règle de déduplication](../../graphe1/docs/conception.md#phase-anti-doublon-demandée-pour-les-collectes)

## Exécution du dossier

Construire un `StateGraph` Python avec un checkpointer persistant sur disque. Garder un état typé contenant l’identité de l’offre, le mode d’exécution, les références des pièces figées, l’étape, l’attente éventuelle, l’état des tentatives et les preuves. Fournir aux nœuds les adaptateurs navigateur, documents, Telegram et messagerie comme dépendances. Le tableau peut indexer les données nécessaires à l’affichage. Le checkpoint du fil fait autorité pour reprendre. [Persistance LangGraph](https://docs.langchain.com/oss/python/langgraph/persistence)

| Étape | Travail du nœud et condition de sortie |
| --- | --- |
| Ouvrir le dossier | Retrouver le fil stable, figer l’annonce et le CV à la première préparation, ou relire le checkpoint existant. Sérialiser les réveils du même dossier. |
| Remplir le formulaire | En production, Codex utilise directement Browsentic pour comprendre et remplir le formulaire, puis valider le dépôt. Une question, un CAPTCHA ou une lettre demandée peut suspendre le tour avant la transmission. |
| Attendre le candidat | Identifier la question et le dossier, envoyer la notification une seule fois puis suspendre avec `interrupt()`. Sur un choix Telegram valide pour cette attente, reprendre le même fil avec `Command(resume=...)`. Isoler la notification du nœud rejoué à la reprise. |
| Préparer les pièces | Le rédacteur personnalise une copie du canevas Inwi, exporte le PDF, en vérifie le rendu et retourne la référence de cette version. Le navigateur peut ensuite joindre la pièce demandée. |
| Déposer ou vérifier | En recette, arrêter avant le premier geste susceptible de transmettre. En production, sérialiser le dernier geste entre lots, vérifier le quota et persister la tentative avant d’autoriser l’action. Après redémarrage avec une tentative ouverte, consulter le suivi du portail. |
| Préparer et envoyer le mail | Après dépôt confirmé, le rédacteur prépare le brouillon si l’annonce fournit une adresse. Python fait valider sur Telegram la version exacte avec ses deux PDF. La reprise d’un envoi incertain vérifie son acceptation auprès de la messagerie. |

Séparer le nœud qui prépare la tentative du nœud qui agit. Le tour navigateur de production peut transmettre dès qu’il atteint la validation. Le checkpoint durable précède donc le tour entier. Au redémarrage, router toute tentative ouverte vers la vérification en lecture seule avant de rendre les outils de saisie et de dépôt disponibles.

## Lancement des agents et contexte de travail

Pour chaque rôle actif, Python lance `codex app-server --stdio` avec la configuration d’outils définie par le projet. Le client initialise la connexion (`initialize`, puis `initialized`), ouvre la conversation avec `thread/start` et lance un tour avec `turn/start`. Fournir le schéma du résultat attendu via `outputSchema` et vérifier le résultat avant de choisir la branche suivante. Le graphe 1 fournit un exemple local du dialogue. Son adaptateur de qualification rejette tous les outils. Le client du graphe 2 doit prendre en charge ceux autorisés pour chaque rôle. [Adaptateur du graphe 1](../../graphe1/src/linkedin_discovery/adapters/codex.py)

| Rôle | Contexte et outils |
| --- | --- |
| Navigateur | Browsentic, profil visible (`headless=false`), onglet du dossier, étape courante, faits applicables et pièces à joindre. Un seul agent navigateur actif entre tous les lots. Un onglet confié au candidat pour une vérification reste sous son contrôle. |
| Rédacteur | Annonce et CV figés, faits confirmés applicables, copie du DOCX Inwi, répertoire privé du dossier et outils locaux de modification, export et inspection du rendu. Le rédacteur peut travailler pendant la navigation d’un autre dossier. |
| Processus Python | Routage LangGraph, checkpointer, accès Telegram et messagerie, contrôle de version du brouillon et comptage des dépôts confirmés. Les MCP personnels de l’utilisateur ne sont pas hérités par les rôles. |

Le processus reconstruit le contexte de chaque appel à partir du dossier et des réponses dont la portée convient à la question. « Envoyer sans garder en mémoire » permet de retrouver le texte dans le checkpoint privé du dossier après une panne. « Envoyer et garder en mémoire » autorise aussi son ajout au Markdown privé pour les offres suivantes. Les codes à usage unique sont saisis par le candidat dans le navigateur.

## Vérification avant les parcours réels

Commencer par les trois fixtures prioritaires de la spécification. Tester également qu’une fermeture du tableau laisse le traitement avancer et qu’un MCP ajouté à la configuration personnelle reste inaccessible aux deux rôles. Vérifier avec Browsentic le mode visible, l’isolation des onglets et la possibilité de bloquer un geste susceptible de transmettre **avant** son exécution. Une notification d’outil reçue après le clic ne suffit pas. Si le premier geste ambigu peut déjà envoyer le dossier, la recette s’arrête avant ce geste. [Fixtures et recette](./specification.md#testing-decisions)
