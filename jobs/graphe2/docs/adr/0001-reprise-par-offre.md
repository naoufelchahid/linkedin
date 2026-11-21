# Un fil LangGraph persistant par offre

Chaque offre possède un identifiant unique et un seul `thread_id` LangGraph stable, conservé entre lots et après redémarrage. Le lot référence les dossiers à traiter. Une réponse Telegram réveille le dossier qui a posé la question, même si plusieurs lots suivent cette offre.

Le dossier peut reprendre avec une conversation Codex neuve. Le checkpoint persistant LangGraph du fil est l’unique source de reprise. Il porte l’étape, la question en attente, les références des pièces figées, l’état des tentatives et leurs preuves. Pour une réponse réservée au dossier, le checkpoint conserve le texte afin que le même fil puisse le retrouver après une panne. Le Markdown privé reçoit uniquement les réponses que le candidat choisit de rendre réutilisables, avec leur portée. Python reconstitue pour chaque appel le contexte nécessaire à l’étape.
