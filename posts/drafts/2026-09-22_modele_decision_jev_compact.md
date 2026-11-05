Avis aux concepteurs d'agents IA : une 3e famille de modèles vient de naître, et elle ne sert pas à discuter mais à décider.

Elle s'appelle les « System One Models », et son premier représentant public, Jev, vient d'être dévoilé par TypeSafe AI.

Pourquoi c'est une rupture ?

Jusqu'ici, dès qu'un agent devait choisir un outil, router une tâche ou évaluer un risque, on appelait un LLM géant de 100 milliards de paramètres.

Résultat : coûts d'API démesurés, latence et sorties de format imprévues.

Le changement de paradigme :
Les modèles de langage génèrent. Les modèles de décision choisissent.

Au lieu de rédiger des phrases, ce modèle renvoie directement :
• Un choix strict (routage, score de risque, validation oui/non).
• Une probabilité calibrée pour le code.
• Un indice de confiance exploitable.

La nouvelle architecture d'agents en 3 couches :
1. Modèle rapide ➔ « Que doit-il se passer ? » (décision)
2. Grand LLM ➔ « Comment procéder ? » (raisonnement complexe)
3. Code logiciel ➔ « Fais-le sous contrôle » (exécution)

Plus la confiance est haute, plus l'action est directe. Si le doute persiste, l'humain reprend la main.

Quel pourcentage de vos appels LLM actuels sert uniquement à router ou classifier ?

(Lien de l'analyse détaillée en premier commentaire)
