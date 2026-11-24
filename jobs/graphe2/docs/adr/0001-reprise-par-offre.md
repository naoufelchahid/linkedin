# Un fil LangGraph persistant par offre

Chaque offre possède un identifiant unique et un seul `thread_id` LangGraph stable, conservé entre lots et après redémarrage. Le lot référence les dossiers à traiter. Une réponse Telegram réveille le dossier qui a posé la question, même si plusieurs lots suivent cette offre.

Le dossier peut reprendre avec une conversation Codex neuve. Le checkpoint persistant LangGraph du fil porte l’étape, la question en attente et les références des pièces figées. Les registres SQL des réponses, tentatives, reçus de dépôt, comptes et mails portent leurs propres faits durables; Python les relit avec le checkpoint pour reconstruire le contexte de chaque reprise. Pour une réponse réservée au dossier, le checkpoint conserve le texte afin que le même fil puisse le retrouver après une panne. Le Markdown privé reçoit uniquement les réponses que le candidat choisit de rendre réutilisables, avec leur portée.

Mise à jour du 24 novembre 2026 : le worker PostgreSQL G2 reprend depuis `runtime_g2` et combine le checkpoint aux registres métier. Le chemin SQLite reste disponible pour les anciens appels. L’état courant et les limites de reprise sont décrits dans le [README G2](../../README.md#état-du-code).
