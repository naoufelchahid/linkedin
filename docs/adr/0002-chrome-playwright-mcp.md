---
status: accepted
---

# Contrôle de Chrome par Playwright MCP en mode extension

Le 5 novembre 2026, l'utilisateur a explicitement demandé de configurer Playwright MCP avec `--extension`, puis a installé son extension Chrome et fourni son token de connexion. Le connecteur ChatGPT échouait sur la navigation et la lecture avec `timeoutMs`, y compris après redémarrage de Chrome.

Les workers de candidatures utilisent désormais le serveur MCP `playwright` pour le Chrome déjà ouvert. Ils désactivent `node_repl` dans leur propre processus afin de ne pas réutiliser le connecteur défaillant. La configuration des autres usages de Codex reste disponible. Aucun profil autonome, port de débogage distant ou autre navigateur n'est ajouté.

Le lanceur local `scripts/playwright-mcp` lit uniquement le secret dédié dans `.env.playwright` (permissions `600`, ignoré par Git). Le token rejoint l'environnement du serveur MCP, jamais ses arguments ni l'environnement du worker agentique. Les artefacts du navigateur sont placés dans le répertoire temporaire privé du worker et supprimés à sa sortie.

Les approbations Telegram individuelles, leur expiration après 24 heures, les empreintes du dossier et du CV, et l'interdiction de réessayer un envoi incertain sont conservées. Le diagnostic doit réussir une navigation et une lecture réelle de contenu avant activation des envois. Le premier dépôt réel reste à vérifier avec un dossier explicitement approuvé.

Référence : [connexion via l'extension Playwright](https://playwright.dev/mcp/configuration/browser-extension).
