# Recette Docker de Browsentic

Depuis la racine du dépôt, construire le worker à partir du verrou du graphe 2. La recette utilise Linux, un démon Docker local, les espaces de noms utilisateur et réseau, `ip`, un écran X11 et la commande `browsentic`. Renseigner le chemin de Chrome for Testing ou de Chromium qui accepte le chargement d’une extension locale.

```bash
d=jobs/graphe2/tests/recette_browsentic
docker build -f "$d/Dockerfile" -t linkedin-browsentic-recette jobs/graphe2
DISPLAY=:0 python3 "$d/run.py" --chrome /chemin/vers/chrome
```

Le worker s’exécute sous UID 1000. Le processus MCP sur l’hôte et le worker échangent les messages JSON-RPC par l’entrée et la sortie standard de Docker. Le portail, le Bridge et le Chrome visible partagent un espace réseau limité au loopback. Le navigateur utilise un nouveau profil et le Bridge une nouvelle configuration à chaque recette. Chrome et le conteneur redémarrent entre les deux phases. Le portail vérifie le cookie persistant délivré lors de la première phase.

Les refus sont affichés sur la sortie d’erreur. Un code de sortie 1 signale une capacité manquante ou un échec technique. Le code 2 indique que seule la relecture visuelle du cadre reste à effectuer. Si le navigateur ne peut pas cibler le cadre, comparer le texte de la capture sous `tmp/browsentic-*/preuve/` à la valeur attendue affichée. Le PDF est une page blanche synthétique. Le portail calcule l’empreinte sur les octets réellement reçus dans son champ de fichier.

## Observation du 22 novembre 2026

Avec Browsentic 0.9.2 et Chrome for Testing 158.0.8127.18, le worker UID 1000 a ouvert deux onglets distincts et vérifié l’URL de l’onglet actif. Le texte propre à l’iframe est lisible dans la capture MCP. La lecture structurée via `page_switchFrame` renvoie `UNSUPPORTED`.

À cette observation du 22 novembre, la capture du PDF par `page_captureDownload` renvoyait `BLOCKED` et le contrôle SHA-256 de la pièce jointe restait à valider. Les recettes décrites dans [Contrôle du fichier avant transfert](#contrôle-du-fichier-avant-transfert) consignent ensuite le transfert vérifié avec l’extension corrigée; elles ne valident pas encore que le rôle CV/lettre est lié automatiquement au bon champ du formulaire.

Un arrêt de Chrome immédiatement après la réception du cookie a donné « Session absente ». La recette attend donc que Chrome ait écrit la ligne du cookie persistant dans le profil synthétique. Après fermeture de Chrome et du premier worker, le second worker a relu « Session de recette retrouvee » dans le nouveau Chrome. Le Bridge est resté en marche.

## PDF choisi dans le panneau

Ajouter `--pdf-panneau` à la commande de recette pour ouvrir uniquement l’onglet « Pièce de recette ». Le worker attend dans ce profil jetable. Ouvrir Browsentic depuis le menu Extensions de **cette fenêtre**, puis utiliser **Attach a file** en bas du panneau pour choisir le fichier `recette.pdf` dont le chemin est affiché dans le terminal. Laisser l’onglet de recette actif. Le worker utilise ensuite `page_listFiles` et demande une fois `page_attachFile` avec le `fileId` obtenu. Un succès exige la lecture du SHA-256 dans le champ du portail. Fermer le navigateur ou interrompre le lanceur termine la recette.

Par défaut, Browsentic demande une approbation pour `file-upload`, même lorsque le fichier a été choisi dans le panneau. Pour une action demandée **par l’agent du panneau**, la carte y affiche **Allow** pour une autorisation unique. Pour une action demandée **par le worker MCP externe**, la version 0.9.2 transforme la demande d’approbation en refus. Aucune carte ne reste en attente pour cet appel. Le profil de recette conserve les permissions par défaut. [Fichiers dans Browsentic](https://github.com/imshaikot/browsentic/blob/main/docs/guide/features/files.md) · [Approbations](https://github.com/imshaikot/browsentic/blob/main/docs/guide/approvals.md) · [Clients MCP externes](https://github.com/imshaikot/browsentic/blob/main/docs/guide/mcp-clients.md)

## Connecteurs d’inscription

Ces deux recettes utilisent le worker Docker ci-dessus. Le script monte le répertoire des scripts de recette en lecture seule. Pour Thunderbird, fournir le binaire Linux, Node.js et une copie de `tkasperczyk/thunderbird-mcp` contenant son extension construite et son bridge.

```bash
d=jobs/graphe2/tests/recette_browsentic
unshare --user --map-current-user --net --keep-caps \
  python3 "$d/thunderbird.py" --thunderbird /chemin/vers/thunderbird \
  --mcp-repo /chemin/vers/thunderbird-mcp
DISPLAY=:0 python3 "$d/run.py" --chrome /chemin/vers/chrome --secret
```

Le 22 novembre 2026, le worker UID 1000 a retrouvé un message unique avec `searchMessages`, puis vérifié le texte de son corps avec `getMessage`. Thunderbird 160.0 tournait hors ligne, avec Thunderbird MCP 0.9.2 (révision `1ab10183`) et Node.js 24.14.0. Une extension de recette importe un fichier EML dans les dossiers locaux d’un profil temporaire. Le bridge sur l’hôte utilise le fichier de connexion de ce profil et communique avec le worker sur les flux standard de Docker. Cette expérience couvre la lecture d’un message déjà disponible dans Thunderbird. La réception IMAP, l’authentification au fournisseur et les délais de synchronisation restent à tester avec une boîte de recette.

Avec Browsentic 0.9.2 et Chrome for Testing 158.0.8127.18, un nœud LangGraph a lu une valeur aléatoire depuis un fichier local privé, a ciblé le champ de mot de passe et a appelé `page_fillInput`. Le serveur de recette sert un formulaire local dont le JavaScript calcule l’empreinte SHA-256 dans le navigateur. Le worker compare cette empreinte à celle du témoin. Deux contextes de prompt locaux encadrent l’opération. Le checkpoint SQLite final enregistre sa réussite.

Le contrôle recherche la valeur entière en ASCII et UTF-16LE dans les prompts, la base de checkpoints, les journaux (worker, MCP, Chrome et Bridge) et les fichiers ordinaires du profil Chrome. Le 22 novembre 2026, aucune occurrence du témoin n’a été trouvée dans ces fichiers. Le fichier témoin est supprimé en fin de recette. Le transport RPC contient la valeur en clair et passe par stdout du conteneur. Pour ce test, `--log-driver=none` empêche Docker d’archiver le transport et les diagnostics stderr sont collectés à part. La recette fonctionne hors ligne, sans appel à un modèle ni export LangSmith. Les captures d’écran, les représentations compressées, les fragments en mémoire et les journaux d’un déploiement avec d’autres paramètres restent hors de la mesure.

## Contrôle du fichier avant transfert

Le correctif local d'extension se construit à partir du tag `v0.9.2` de Browsentic. Il compare l'empreinte aux octets exacts du PDF et vérifie l'URL active avant de remplir le champ. Les permissions Browsentic continuent de s'appliquer. Depuis la racine du projet, après avoir récupéré le tag dans un répertoire de travail séparé, appliquer le correctif et construire l'extension.

```bash
git -C /chemin/vers/browsentic apply "$PWD/jobs/graphe2/connectors/browsentic/verify-attachment.patch"
(cd /chemin/vers/browsentic && yarn install --immutable && yarn compile && yarn build)
d=jobs/graphe2/tests/recette_browsentic
docker build -f "$d/Dockerfile" -t linkedin-browsentic-verification jobs/graphe2
DISPLAY=:0 python3 "$d/run.py" --chrome /chemin/vers/chrome \
  --image linkedin-browsentic-verification \
  --verified-documents /chemin/vers/browsentic/dist/chrome-mv3
```

Le test crée une configuration temporaire réservée au localhost. Il télécharge deux PDF factices de même taille. Le chemin normal `attach_document` essaie d'abord la mauvaise référence pour le CV et vérifie que le champ reste vide. Il joint ensuite les deux bonnes références et compare les empreintes dans les champs indépendants.
