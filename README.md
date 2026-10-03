# Assistant IA génératif Edge pour un campus intelligent

Prototype d'assistant IA pour étudiants, avec une architecture **Edge / Cloud** : les traitements sensibles et rapides se font en local, et seules les demandes qui nécessitent un modèle de langage partent vers le cloud. Projet du module **Technologies émergentes et quantum** (ENSA Béni Mellal, filière Intelligence Artificielle et Cybersécurité).

## Fonctionnalités

- **Chat avec un LLM** (`llama-3.3-70b-versatile` via l'API Groq) : questions, résumés de cours
- **Couche Edge locale** : détection du stress ou de la frustration (mots-clés), cache des réponses fréquentes et planning de révision, tous stockés dans SQLite
- **Mode dégradé** : si le cloud est indisponible, l'assistant répond quand même avec des réponses locales
- **Filtre RGPD** : blocage des messages contenant des données personnelles (CIN, mot de passe, e-mail, téléphone, RIB, etc.)
- **Mesure de la latence** pour chaque réponse, avec une cible locale inférieure à 200 ms
- **Synchronisation simulée** avec le cloud (agrégats anonymisés uniquement)
- Comptes utilisateurs (inscription, connexion, page de profil) et historique des conversations
- Statistiques d'usage (`/stats`) et script de test du flux (`test_workflow.py`)

## Architecture

```
Utilisateur → [Edge] détection du stress, filtre RGPD, cache, planning, SQLite local
                  ↓ (si nécessaire)
              [Cloud] API LLM (Groq)
                  ↓ (si indisponible)
              [Edge dégradé] réponses locales de secours
```

## Technologies

Python, Flask, SQLite, HTML/CSS/JavaScript, API Groq.

## Structure

```
├── edge_assistant.py    # application Flask (routes, logique Edge, appel au LLM)
├── test_workflow.py     # test du flux de traitement
├── templates/           # pages HTML (connexion, chat, historique, profil, admin)
├── requirements.txt
└── .env.example         # modèle du fichier de configuration
```

## Installation

```bash
git clone https://github.com/sabrine-ouarchane/NOM-DU-DEPOT.git
cd NOM-DU-DEPOT
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

Copie `.env.example` en `.env` et renseigne `GROQ_API_KEY` (clé gratuite sur [console.groq.com](https://console.groq.com)).

## Lancer

```bash
python edge_assistant.py
```

Ouvre ensuite `http://localhost:5000`. La base `campus_edge.db` est créée automatiquement au premier lancement. Pour tester le flux, lance l'application puis, dans un autre terminal, `python test_workflow.py`.

## Limites

Prototype pédagogique : la partie « Edge » est **simulée** sur la même machine que le serveur, et la synchronisation avec le cloud est simulée. Il n'est pas destiné à la production.



## Auteure

**Sabrine Ouarchane**, élève ingénieure en IA et cybersécurité, ENSA Béni Mellal.