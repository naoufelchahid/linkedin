# Restauration de référence des graphes 1 et 2

Depuis la racine du dépôt, utiliser l’environnement verrouillé du graphe 2 et un nouveau chemin dans un répertoire privé. Les deux répertoires d’état peuvent se trouver sur un autre volume. Le paramètre `--studio` inclut les checkpoints locaux du serveur Studio lorsqu’il est utilisé.

```bash
install -d -m 700 tmp
jobs/graphe2/.venv/bin/python scripts/restore_baseline.py \
  --discovery jobs/graphe1/var --applications jobs/graphe2/var \
  --studio jobs/graphe1/.langgraph_api --destination tmp/reference-migration
jobs/graphe2/.venv/bin/python scripts/restore_baseline.py --verify tmp/reference-migration
```

Le répertoire produit contient la capture privée dans `reference/`, la copie de restauration dans `restored/`, le manifeste privé `sha256.json` et les compteurs `counts.json`. Chaque base provient de l’API SQLite de sauvegarde, qui inclut les transactions validées du journal WAL. Le script contrôle les versions des bases et les empreintes des fichiers pendant la capture. Si le contrôle échoue pendant une écriture concurrente, relancer la commande dans un créneau calme. Le mode de vérification relit les deux arborescences et les compteurs hors ligne. Les chemins absolus historiques restent dans les bases. La vérification retrouve les pièces dans la copie isolée.

Le périmètre couvre les états courants des deux graphes, dont les réponses enregistrées, documents de candidature, données de recette, rapports, validations et snapshots. Les fichiers de configuration, journaux, profils de navigateur et archives de l’ancien moteur Telegram sont extérieurs au périmètre. Les compteurs de tentatives et de reçus de candidature identifient les opérations distinctes dans l’historique des checkpoints du graphe 2. Les réponses de dossier comptent les valeurs historiques par dossier et position. Les dossiers utilisent leur dernier état et sont dédoublonnés entre lots.

## Contrôle du 22 novembre 2026

| Élément contrôlé | Nombre |
|---|---:|
| Fichiers vérifiés par SHA-256 | 25 |
| Offres distinctes / versions | 215 / 224 |
| Rapports / reçus de validation du pilote | 6 / 1 |
| Tentatives de qualification / réponses techniques conservées | 244 / 2 |
| Lots / checkpoints de candidature | 2 / 130 |
| Dossiers en préparation / en attente / bloqués | 3 / 5 / 2 |
| Réponses de dossier / entrées de la mémoire réutilisable | 9 / 1 |
| Tentatives de candidature ou de courriel / reçus correspondants | 24 / 0 |
| PDF restaurés | 4 |

Les empreintes des fichiers restaurés concordent avec le manifeste. Les empreintes enregistrées pour les rapports et les CV des cycles concordent avec les pièces restaurées. Le reçu de validation référence le rapport et son empreinte. Aucun dossier clôturé ni reçu de dépôt ne figure dans les checkpoints de candidature de cette capture.
