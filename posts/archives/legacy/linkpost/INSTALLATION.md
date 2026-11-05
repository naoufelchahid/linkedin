# Méthode LinkedIn quatre formats — sans abonnement LinkPost

Ce projet utilise le skill `linkpost-quatre-formats` avec la mémoire `memoire-linkedin.md`. Le choix de travailler sans abonnement ni connexion LinkPost est déjà confirmé. La méthode conserve trois couches de contexte (auteur, marché, moment) et quatre formats (polarisant, célébration, actualité, lead magnet). Les idées et brouillons viennent de l’assistant et de sources accessibles ; il n’y a pas de données, de validation ou de score issus du moteur LinkPost.

## Dans ce dépôt avec Codex

1. Le skill actif se trouve dans `.agents/skills/linkpost-quatre-formats/`. Les anciens liens de skills ont été retirés du catalogue `.agents/skills/`.
2. La mémoire réutilisable se trouve à la racine : `memoire-linkedin.md`. Ses éléments marqués « à confirmer » ne doivent pas devenir des faits publiés.
3. Pour démarrer, copie le texte de `message-demarrage (1).txt` dans une conversation. L’assistant proposera les formats demandés et conservera les nouveaux textes dans `posts/drafts/`.
4. Corrige ou complète la mémoire à chaque nouveau fait validé. La publication exige ton accord explicite.

## Dans ChatGPT

1. Si les projets sont disponibles dans ton compte, crée un projet pour tes posts LinkedIn.
2. Ajoute `LINKPOST-CHATGPT.md` **et** `../memoire-linkedin.md` aux fichiers du projet.
3. Colle `INSTRUCTIONS-CHATGPT.txt` dans les instructions du projet.
4. Commence avec le texte de `DEMARRAGE.txt`.

Ces fichiers appliquent directement le parcours sans LinkPost. Aucun connecteur LinkPost n’est nécessaire.

## Dans Claude

1. Importe `linkpost-quatre-formats-claude.zip` comme skill personnalisé si ton espace permet les skills.
2. Joins aussi `../memoire-linkedin.md` à la conversation ou au projet : l’archive contient la méthode, pas tes faits personnels.
3. Commence avec le texte de `DEMARRAGE.txt`.

## Sources et limites

Les sources locales de la mémoire permettent un premier travail. Pour étudier le marché, ajoute des posts réels de ta niche avec auteur, date, lien et métriques si disponibles. Pour un post d’actualité, vérifie une source primaire récente. Une célébration demande une étape réellement atteinte ; un lead magnet demande une ressource effectivement disponible et un mode de remise réel. L’assistant signale les manques et ne fabrique ni résultat ni score de viralité.
