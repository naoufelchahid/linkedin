# Vérification du pilote — 20 novembre 2026

Le cadrage fonctionnel du graphe 1 est confirmé. L’implémentation est sous `src/candidatures/discovery/`, avec le lanceur `jobs/decouverte.py`, ses dépendances isolées et le [guide d’exécution](../README.md).

## Contrôles effectués

- Suite complète du dépôt avec `jobs/.venv/bin/python -m pytest -q` : **188 tests réussis**, dont **21 tests du pilote**.
- Exécution du vrai StateGraph dans les tests avec connecteurs substitués : regroupement inter-recherches, échec partiel Apify visible, résultat tardif, réutilisation des verdicts et requalification après changement de version.
- Reprise : aucun nouveau lancement Apify pour un profil déjà enregistré, lancement incertain conservé pour rapprochement, au plus trois tentatives Codex même après interruption, verrou d’exécution.
- Revue : échantillon équilibré selon disponibilité, rapport figé, échappement HTML, permissions privées, correction humaine séparée et prioritaire pour la version examinée, rejeu sur les mêmes annonces et le CV sauvegardé, contrôle d’intégrité du CV.
- Qualification : schéma structuré, correspondance de l’identifiant, contrôle des citations contre l’annonce et le CV, problème de données sans troisième verdict métier.
- Confidentialité : traces automatiques désactivées, test du contenu technique autorisé des traces explicites ; les métadonnées restent aussi enregistrées localement.
- Compilation Python, aide de la CLI et `git diff --check` vérifiés.

Trois appels réels au Codex App Server installé ont été exécutés sur des **cas synthétiques**, avec le CV explicitement confirmé pour le pilote :

| Cas synthétique | Résultat observé |
| --- | --- |
| Missions vagues : participer à la transformation IA | Retenir, avec incertitude |
| Développement généraliste avec assistant de code IA | Écarter |
| Mission GraphRAG minoritaire, avec prérequis obligatoires sans incidence | Retenir |

Ces contrôles valident le raccord App Server et ces cas de politique de qualification. Ils ne constituent pas la revue de 15 annonces réelles.

## Situation avant configuration des accès

Au dernier diagnostic, le CV confirmé est lisible, Codex et `pdftotext` sont disponibles. `APIFY_TOKEN` n’est pas encore présent dans `jobs/.env` ni dans l’environnement du pilote. Aucun run Apify réel n’a été lancé et aucun rapport de revue d’annonces réelles n’a été présenté.

Après configuration de cet accès privé, lancer le cycle de découverte, examiner son bilan et présenter le rapport HTML au candidat. La sélection vise cinq offres retenues sans incertitude, cinq avec incertitude et cinq écartées, selon disponibilité. Enregistrer ses verdicts, corriger le prompt si nécessaire, rejouer et comparer avant sa décision de validation du pilote.

L’accès LangSmith n’est pas configuré lors de ce contrôle : l’envoi réel des métadonnées n’a donc pas été vérifié. Les événements techniques locaux et leur filtrage sont disponibles.

Le moteur courant, son CV configuré, ses bases, son cron et ses services n’ont pas été modifiés par cette implémentation. Le second graphe reste hors de cette livraison.

## Exécution réelle après configuration des accès

Les accès Apify et LangSmith sont configurés. Les trois recherches Apify sont terminées avec succès : 300 occurrences brutes et 203 annonces distinctes après regroupement. La collecte est conservée sous le cycle `5383ec21f2ea4829b24b5cd3af3392bf`.

La première qualification a révélé un défaut d’extraction : `pdftotext -layout` entrelaçait le bandeau latéral et l’expérience dans le CV à deux colonnes. Les citations reconstituées par Codex échouaient au contrôle contre ce texte. Le traitement a été interrompu ; les échecs restent conservés.

L’extraction utilise maintenant l’ordre de lecture du PDF. Un nouveau cycle `e795e3319d534acc821a8fd8a23b718c` reprend exactement les annonces sauvegardées, avec le même PDF et une nouvelle version explicite du contrat de citation. Aucun nouveau run Apify n’a été lancé pour cette reprise. Ce cycle est terminé : 200 annonces qualifiées et trois erreurs techniques, sans nouveau lancement Apify.

La suite après correction passe à **191 tests**, dont **24 tests du pilote**. Les régressions couvrent un vrai PDF synthétique à deux colonnes, les réponses rejetées conservées uniquement en privé, la provenance Apify des rapports rejoués et la conservation de toutes les lignes du prompt.

Trois traces effectivement reçues dans LangSmith ont été inspectées : entrées et sorties vides, métadonnées techniques uniquement.

## Résultat du premier lot réel

- Collecte : trois runs Apify réussis, 100 résultats bruts chacun, soit 300 occurrences regroupées en 203 annonces distinctes.
- Qualification : 200 annonces avec verdict Codex, dont **93 retenues** (25 avec incertitude) et **107 écartées**. Trois annonces restent en erreur technique après trois tentatives ; aucun verdict métier n’a été inventé pour ces cas.
- Rapport final : `0f8bdde61b814e9ba87d15d646f8eb79`, avec cinq offres retenues sans incertitude, cinq retenues avec incertitude et cinq écartées.
- Fichier privé : `data/candidatures/discovery/reports/0f8bdde61b814e9ba87d15d646f8eb79.html`. L’échantillon conserve les verdicts Codex ; leur exactitude métier reste à juger par le candidat.
- Contrôles du rapport : 15 articles, 15 liens, aucune balise script, empreinte conforme à SQLite, permissions `600`, références aux trois runs sources et citations validées contre l’annonce sauvegardée et le texte du CV du cycle.
- Intégrité SQLite vérifiée ; même empreinte du PDF dans les deux cycles.

Après présentation du rapport et de son accès web local, le candidat a déclaré « je valide » le 20 novembre 2026. La validation globale du pilote est acquise et satisfait la condition préalable aux travaux sur le graphe 2. Aucun verdict individuel par annonce n’a été fourni ; les verdicts Codex restent conservés tels quels.

## Reçu de validation du candidat

La validation globale porte sur le rapport `0f8bdde61b814e9ba87d15d646f8eb79` et le cycle `e795e3319d534acc821a8fd8a23b718c`. Le reçu privé conserve le texte exact « je valide », la date, l’empreinte du rapport et les versions du CV et du prompt. Un événement `pilot_validation` de statut `accepted` est enregistré dans SQLite.
