# Recette Docker de Browsentic

Depuis la racine du dépôt, construire le worker à partir du verrou du graphe 2. La recette utilise Linux, un démon Docker local, les espaces de noms utilisateur et réseau, `ip`, un écran X11 et la commande `browsentic`. Renseigner le chemin de Chrome for Testing ou de Chromium qui accepte le chargement d’une extension locale.

```bash
d=jobs/graphe2/tests/recette_browsentic
docker build -f "$d/Dockerfile" -t linkedin-browsentic-recette jobs
DISPLAY=:0 python3 "$d/run.py" --chrome /chemin/vers/chrome
```

Le worker s’exécute sous UID 1000. Le processus MCP sur l’hôte et le worker échangent les messages JSON-RPC par l’entrée et la sortie standard de Docker. Le portail, le Bridge et le Chrome visible partagent un espace réseau limité au loopback. Le navigateur utilise un nouveau profil et le Bridge une nouvelle configuration à chaque recette. Chrome et le conteneur redémarrent entre les deux phases. Le portail vérifie le cookie persistant délivré lors de la première phase.

Les refus sont affichés sur la sortie d’erreur. Un code de sortie 1 signale une capacité manquante ou un échec technique. Le code 2 indique que seule la relecture visuelle du cadre reste à effectuer. Si le navigateur ne peut pas cibler le cadre, comparer le texte de la capture sous `tmp/browsentic-*/preuve/` à la valeur attendue affichée. Le PDF est une page blanche synthétique. Le portail calcule l’empreinte sur les octets réellement reçus dans son champ de fichier.

## Observation du 22 novembre 2026

Avec Browsentic 0.9.2 et Chrome for Testing 158.0.8127.18, le worker UID 1000 a ouvert deux onglets distincts et vérifié l’URL de l’onglet actif. Le texte propre à l’iframe est lisible dans la capture MCP. La lecture structurée via `page_switchFrame` renvoie `UNSUPPORTED`.

La capture du PDF par `page_captureDownload` renvoie `BLOCKED`. Browsentic réserve l’approbation de cette action au panneau latéral. Le MCP externe n’a donc pas obtenu de référence pour `page_attachFile`. Le contrôle SHA-256 de la pièce jointe reste à valider.

Un arrêt de Chrome immédiatement après la réception du cookie a donné « Session absente ». La recette attend donc que Chrome ait écrit la ligne du cookie persistant dans le profil synthétique. Après fermeture de Chrome et du premier worker, le second worker a relu « Session de recette retrouvee » dans le nouveau Chrome. Le Bridge est resté en marche.

## PDF choisi dans le panneau

Ajouter `--pdf-panneau` à la commande de recette pour ouvrir uniquement l’onglet « Pièce de recette ». Le worker attend dans ce profil jetable. Ouvrir Browsentic depuis le menu Extensions de **cette fenêtre**, puis utiliser **Attach a file** en bas du panneau pour choisir le fichier `recette.pdf` dont le chemin est affiché dans le terminal. Laisser l’onglet de recette actif. Le worker utilise ensuite `page_listFiles` et demande une fois `page_attachFile` avec le `fileId` obtenu. Un succès exige la lecture du SHA-256 dans le champ du portail. Fermer le navigateur ou interrompre le lanceur termine la recette.

Par défaut, Browsentic demande une approbation pour `file-upload`, même lorsque le fichier a été choisi dans le panneau. Pour une action demandée **par l’agent du panneau**, la carte y affiche **Allow** pour une autorisation unique. Pour une action demandée **par le worker MCP externe**, la version 0.9.2 transforme la demande d’approbation en refus. Aucune carte ne reste en attente pour cet appel. Le profil de recette conserve les permissions par défaut. [Fichiers dans Browsentic](https://github.com/imshaikot/browsentic/blob/main/docs/guide/features/files.md) · [Approbations](https://github.com/imshaikot/browsentic/blob/main/docs/guide/approvals.md) · [Clients MCP externes](https://github.com/imshaikot/browsentic/blob/main/docs/guide/mcp-clients.md)
