# Vérification du 5 novembre 2026

**État actuel :** Chrome fonctionne via Playwright MCP en mode extension. Telegram, LinkedIn et la navigation réelle sont vérifiés. Les envois approuvés sont activés ; la première candidature Keyrus a été envoyée et confirmée. Voir [le test réel](test-process-2026-11-05.md). Les sections ci-dessous conservent les essais et blocages antérieurs ; la résolution figure en fin de rapport.

## Réalisé

- Modules Python, base SQLite, assistant de configuration du bot, cartes Telegram, reprise et planification installés.
- 53 tests automatiques réussis, y compris les tests existants du client LinkedIn : validation individuelle, expiration exacte, double clic, version périmée, CV modifié, identité Telegram, répétition d'un événement, quota, déduplication, interruption, issue incertaine, correction, inspection sans soumission et parcours complet simulé.
- Crontab relu après installation ; autres tâches conservées. Deux réveils toutes les cinq minutes, heure de recherche contrôlée par `ZoneInfo('Africa/Casablanca')` à 21 h.
- Permissions vérifiées : configuration et base `600`, répertoire de données et lanceur `700`.
- CV fixe présent, aucun token dans le code ou les arguments du programme.

## Essais réels et limites observées

Un premier diagnostic non interactif a lu le MCP LinkedIn et listé les onglets Chrome. Ce test était insuffisant pour prouver que les actions navigateur fonctionnent. Le lanceur a été corrigé pour inclure `~/.local/bin` (uvx) dans son PATH, puis le délai de démarrage MCP LinkedIn a été porté à 90 secondes.

Un essai borné de recherche réelle a lu le CV et le profil, parcouru deux pages de résultats et examiné trois offres. Aucun dossier n'a été présenté comme prêt : liens employeurs non établis pour certaines offres, statut freelance non confirmé pour une autre, navigation Chrome en échec. La préparation reste donc partiellement non vérifiée en conditions réelles.

Le diagnostic Chrome renforcé exige maintenant une navigation et la lecture effective d'une offre. La connexion et la création d'onglets fonctionnent, mais la navigation et les commandes clavier documentées échouent avec :

```text
Cannot read properties of undefined (reading 'timeoutMs')
```

L'erreur a également été reproduite dans la session interactive principale, hors cron. La documentation de dépannage du navigateur a été consultée ; aucun correctif spécifique n'y est fourni. Aucun mécanisme de navigateur alternatif n'a été substitué au Chrome demandé, et aucune protection du navigateur n'a été modifiée.

L'accès au MCP LinkedIn a aussi été intermittent entre processus de test. Une sortie `unknown` de `get_job_apply_url` n'est pas traitée comme un lien valide. La lecture DOM peut compléter ce résultat lorsque Chrome fonctionne. Une source partiellement exploitable peut maintenant conserver ses dossiers valides sans être déclarée entièrement indisponible.

Le dernier essai LinkedIn seul, après augmentation du délai de démarrage, a réussi : `get_job_details` a lu l'offre 4484363233. Il a toutefois signalé `description_missing` (en-tête non reconnu), ce qui exige de vérifier le contenu extrait avant qualification. Le blocage restant reproduit concerne les actions Chrome.

## État initial de mise en service, avant Playwright MCP

- Le planning est installé et le bot dédié est désormais associé au compte utilisateur. Le diagnostic confirme `telegram_configured=true`, `telegram_api_ok=true` et `telegram_polling_available=true`.
- `CANDIDATURES_SUBMIT_ENABLED=false` tant que la navigation Chrome n'est pas rétablie et que le diagnostic complet n'a pas réussi.
- Sans configuration Telegram complète, les réveils cron se terminent sans recherche agentique ni candidature.
- Aucun message Telegram de candidature, téléversement de CV ou envoi de candidature réelle n'a été effectué.

Après rétablissement du connecteur : exécuter `python3 -m src.candidatures doctor --probe`, puis `python3 -m src.candidatures enable-submission` seulement si le diagnostic est concluant. Effectuer ensuite une première candidature réelle approuvée dans Telegram pour vérifier le parcours complet.

## Diagnostic complémentaire Chrome

Le bot Telegram a été configuré par l'utilisateur et son accès API a été vérifié sans exposer son token.

Les contrôles officiels trouvent Chrome démarré, l'extension activée et le manifeste de connexion présent. La création et la liste d'onglets réussissent. La navigation de lecture seule vers l'offre LinkedIn 4484363233 reproduit immédiatement l'erreur `timeoutMs`.

Le cache du plugin utilise la version 26.818.31338 ; l'application installée fournit la version 26.1007.71326. Un essai isolé a aligné service et client sur cette dernière version : la même erreur de navigation subsiste. Cette différence de version n'est donc pas une cause suffisante démontrée. Les surcharges expérimentales ont été retirées ; la configuration globale n'a pas été modifiée. Aucun correctif navigateur n'est déclaré réussi.

La prochaine intervention demandée à l'utilisateur est la réinstallation du plugin Chrome depuis l'interface ChatGPT, conformément au sujet officiel `chrome-troubleshooting`. Aucun hôte natif n'a été réparé manuellement. Après cette intervention, relancer le diagnostic de navigation avant toute activation des envois.

## Contrôle après redémarrage de Chrome

Contrôle du 2026-11-05T13:02:45.212391+00:00 : la nouvelle instance de Chrome est détectée. Le test interactif puis `python3 -m src.candidatures doctor --probe`, lancé dans un processus neuf, reproduisent tous deux `Cannot read properties of undefined (reading 'timeoutMs')`. Le diagnostic confirme `linkedin_ok=true`, `chrome_ok=false`, `telegram_api_ok=true`. Le redémarrage de Chrome seul ne résout donc pas le défaut. Les envois restent désactivés.

## Résolution avec Playwright MCP

À la demande explicite de l'utilisateur, `playwright` a été ajouté à Codex en mode `--extension`. L'extension officielle a ensuite été installée par l'utilisateur. Le serveur MCP s'initialise ; son premier diagnostic signalait précisément l'absence de cette extension. Après installation, le worker a réussi la navigation vers l'offre 4484363233 et la lecture de son contenu Infomineo.

Le token de connexion dédié a été enregistré puis remplacé à la demande de l'utilisateur dans `.env.playwright` avec permissions `600`. Le lanceur `scripts/playwright-mcp` le transmet uniquement au serveur MCP, hors des arguments et de l'environnement du worker. Aucun token n'est copié dans cette documentation. Les autres configurations MCP sont inchangées ; une sauvegarde privée du fichier Codex précède l'ajout.

Le contrôle final, terminé à `2026-11-05T13:22:25.781752+00:00`, a utilisé le lanceur réel depuis un environnement minimal équivalent à cron, avec le dernier token. Résultats : `linkedin_ok=true`, `chrome_ok=true`, `connectors_verified=true`. La navigation et la lecture DOM de l'offre ont réussi. Aucun clic de candidature, remplissage ni téléversement ; seul l'onglet de test a été fermé. Le MCP LinkedIn renvoie encore `apply.type=unknown` pour cet exemple, mais le DOM fournit l'action « Postuler sur le site de l’entreprise ».

`enable-submission` a ensuite activé le traitement des seuls dossiers approuvés. Le diagnostic final confirme Telegram joignable, `submission_enabled=true`, 21 h en `Africa/Casablanca`, maximum 20 dossiers et approbations de 24 heures. La base ne contient encore aucun dossier. Les deux tâches cron sont présentes. Le premier envoi réel et les formulaires employeurs ne sont donc pas encore validés en conditions réelles.

Les 53 tests passent, dont les nouveaux contrôles de sélection du MCP Playwright, désactivation du runtime précédent dans les workers, isolation des tokens, suppression des artefacts temporaires et cohérence du résultat du diagnostic. La réussite du connecteur ne dispense jamais de la validation individuelle Telegram.

## Mise à jour après le test réel

La candidature Keyrus 3bd0535ec6af, version 3, est passée à `sent` le 5 novembre 2026 à 14:11:12 UTC, avec confirmation visible du site et notification Telegram livrée. Le détail et la correction du blocage de lecture préalable figurent dans [le rapport du test](test-process-2026-11-05.md). Le service de réception Telegram continue est actif ; les 60 tests passent. Les identifiants des comptes employeurs nécessaires seront conservés dans le fichier privé ignoré par Git `data/candidatures/accounts.md` ; aucune entrée de compte n’existe à la fin de ce test.
