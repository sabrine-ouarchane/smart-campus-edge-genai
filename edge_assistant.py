# edge_assistant.py — Assistant IA Génératif Edge | ENSA Beni Mellal
# Module : Technologies Émergentes & Quantum

from flask import Flask, request, jsonify, render_template, session, redirect
from groq import Groq
import sqlite3, time, json, os, hashlib
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.urandom(24)

# ─────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
client = Groq(api_key=GROQ_API_KEY)
MODEL = "llama-3.3-70b-versatile"
CACHE_TTL = 300        # 5 minutes (Edge cache)
LATENCY_TARGET = 200   # ms
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "campus_edge.db")

def get_db_connection():
    return sqlite3.connect(DB_PATH)

# ─────────────────────────────────────────
# BASE DE DONNÉES LOCALE (Edge Layer)
# ─────────────────────────────────────────
def init_db():
    conn = get_db_connection()
    c = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS conversations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT,
        username TEXT,
        role TEXT,
        message TEXT,
        timestamp TEXT,
        latency_ms REAL,
        source TEXT,
        stress_level TEXT
    )""")
    c.execute("PRAGMA table_info(conversations)")
    existing_columns = [row[1] for row in c.fetchall()]
    if "username" not in existing_columns:
        c.execute("ALTER TABLE conversations ADD COLUMN username TEXT")

    c.execute("""CREATE TABLE IF NOT EXISTS edge_cache (
        cache_key TEXT PRIMARY KEY,
        response TEXT,
        created_at TEXT,
        hit_count INTEGER DEFAULT 0
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS planning (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT,
        module TEXT,
        jour TEXT,
        heure TEXT,
        duree_min INTEGER,
        priorite INTEGER
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS sync_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sync_time TEXT,
        records_synced INTEGER,
        status TEXT
    )""")

    # ✅ TABLE USERS — ajoutée AVANT conn.commit() et conn.close()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        created_at TEXT
    )""")

    conn.commit()   # ✅ commit AVANT close
    conn.close()    # ✅ close EN DERNIER

init_db()

# ─────────────────────────────────────────
# DÉTECTION STRESS / FRUSTRATION (Edge local)
# ─────────────────────────────────────────
STRESS_KEYWORDS = {
    "high": ["je comprends rien", "impossible", "nul", "débile", "j'abandonne",
             "trop difficile", "je suis perdu", "aidez-moi", "j'en peux plus",
             "c'est nul", "je suis bloqué", "je n'y arrive pas"],
    "medium": ["difficile", "compliqué", "dur", "pas sûr", "j'essaie",
               "je ne sais pas", "confus", "perdu", "stressé", "pression",
               "examen", "deadline", "urgent"],
    "low": ["question", "pouvez-vous", "expliquer", "aide", "clarifier"]
}

def detect_stress(text: str) -> str:
    text_lower = text.lower()
    for level in ["high", "medium", "low"]:
        if any(kw in text_lower for kw in STRESS_KEYWORDS[level]):
            return level
    return "none"

def stress_prefix(level: str) -> str:
    prefixes = {
        "high": "⚠️ Je sens que tu traverses une période difficile. Respirons ensemble — je suis là pour t'aider pas à pas.\n\n",
        "medium": "😊 Pas de souci, c'est normal d'avoir des questions. Voici une explication claire :\n\n",
        "low": "",
        "none": ""
    }
    return prefixes.get(level, "")

# ─────────────────────────────────────────
# VÉRIFICATION RGPD (Edge local)
# ─────────────────────────────────────────
MOTS_INTERDITS = ["cin", "carte nationale", "mot de passe",
                  "password", "email", "telephone", "date de naissance",
                  "salaire", "rib", "cne", "apogee"]

def check_rgpd(message: str) -> bool:
    """Retourne True si des données personnelles sont détectées."""
    return any(mot in message.lower() for mot in MOTS_INTERDITS)

# ─────────────────────────────────────────
# CACHE EDGE
# ─────────────────────────────────────────
def get_cache_key(message: str) -> str:
    return hashlib.md5(message.strip().lower().encode()).hexdigest()

def get_from_cache(key: str):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT response, created_at FROM edge_cache WHERE cache_key=?", (key,))
    row = c.fetchone()
    if row:
        created = datetime.fromisoformat(row[1])
        age = (datetime.now() - created).seconds
        if age < CACHE_TTL:
            c.execute("UPDATE edge_cache SET hit_count = hit_count + 1 WHERE cache_key=?", (key,))
            conn.commit()
            conn.close()
            return row[0]
    conn.close()
    return None

def set_cache(key: str, response: str):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("""INSERT OR REPLACE INTO edge_cache (cache_key, response, created_at, hit_count)
                 VALUES (?, ?, ?, 0)""", (key, response, datetime.now().isoformat()))
    conn.commit()
    conn.close()

# ─────────────────────────────────────────
# SYSTÈME DE PROMPT — CAMPUS INTELLIGENT
# ─────────────────────────────────────────
SYSTEM_PROMPT = """Tu es un assistant IA pédagogique pour l'ENSA Beni Mellal (École Nationale des Sciences Appliquées).
Tu aides les étudiants en ingénierie, particulièrement dans les modules : IA, cybersécurité, réseaux, mathématiques, programmation, technologies émergentes.

Tes capacités :
1. RÉSUMÉS DE COURS : Génère des résumés clairs et structurés avec points clés, définitions et exemples.
2. QUESTIONS/RÉPONSES : Réponds aux questions techniques de manière pédagogique et progressive.
3. PLANNING : Aide à créer des plannings d'étude personnalisés selon les modules et examens.
4. SOUTIEN : Détecte le stress et adapte ton ton pour encourager l'étudiant.

Règles :
- Réponds en français sauf si l'étudiant écrit en anglais ou arabe.
- Sois concis mais complet. Utilise des listes à puces et titres quand utile.
- Pour les résumés : structure = Introduction → Points clés → Exemple → Conclusion.
- Pour un planning : demande les modules, les dates d'exam, et les disponibilités.
- Respecte la confidentialité : ne demande jamais de données personnelles sensibles.
- Contexte Edge : tu es déployé localement sur un serveur Edge campus pour réduire la latence."""

# ─────────────────────────────────────────
# MODE DÉGRADÉ (fallback sans Cloud)
# ─────────────────────────────────────────
DEGRADED_RESPONSES = {
    "résumé": "📚 Mode hors-ligne : Je peux vous donner la structure d'un résumé. Indiquez le sujet et je vous fournirai un plan détaillé basé sur mes connaissances locales.",
    "planning": "📅 Mode hors-ligne : Pour créer votre planning, listez vos modules et dates d'examens. Je générerai un planning optimisé localement.",
    "stress": "💙 Mode hors-ligne : Je suis là pour vous soutenir. Respirez — la connexion cloud est temporairement indisponible, mais je reste disponible localement.",
    "default": "⚡ Mode hors-ligne local : pas de connexion Internet, mais je réponds avec ce que je sais déjà.",
}

LOCAL_KNOWLEDGE = {
    "réseau": "Un réseau informatique relie des équipements pour échanger des données. Les éléments essentiels sont les routeurs, commutateurs, câbles et protocoles. Exercice : dessine un schéma simple d'un LAN et identifie chaque composant.",
    "cybersécurité": "La cybersécurité protège les systèmes et les données. Pense aux notions de confidentialité, intégrité et disponibilité, ainsi qu'aux outils comme les pare-feu, le chiffrement et l'authentification.",
    "intelligence artificielle": "L'IA permet à une machine d'apprendre et de prendre des décisions. Les modèles peuvent être supervisés, non supervisés ou par renforcement. Exemple : un classifieur de spam utilise des données d'entraînement pour reconnaître des e-mails indésirables.",
    "edge computing": "L'Edge Computing traite les données près de leur source pour réduire la latence et la consommation réseau. C'est utile pour les capteurs IoT, la vidéo en direct et les systèmes embarqués.",
    "machine learning": "Le Machine Learning est une branche de l'IA qui apprend à partir de données. Tu peux le voir comme une méthode pour créer des modèles capables de prédire et de classer.",
    "rgpd": "Le RGPD est le Règlement Général sur la Protection des Données. Il protège les données personnelles en imposant des règles de collecte, de stockage et d'utilisation. En résumé : on doit traiter les données légalement, limiter leur usage, et informer clairement les personnes.",
    "protection des données": "Le RGPD impose de protéger les données personnelles. Cela signifie limiter l'accès, chiffrer si nécessaire, supprimer quand ce n'est plus utile et respecter la confidentialité des utilisateurs.",
}

def local_assistant_response(message: str) -> str:
    text = message.lower()
    if "rgpd" in text or "protection des données" in text or "données personnelles" in text:
        return "📘 RGPD : le Règlement Général sur la Protection des Données protège les informations personnelles. Il impose de collecter les données avec un but précis, de limiter leur conservation, et de garantir leur sécurité et leur confidentialité."
    if "résumé" in text or "cours" in text:
        return "📚 Mode hors-ligne : donne-moi un sujet précis et je te prépare un plan de résumé structuré avec introduction, points clés et exemples."
    if "planning" in text or "agenda" in text or "révision" in text:
        return "📅 Mode hors-ligne : indique-moi tes modules et dates d'examens, je te propose un planning de révision simple et efficace."
    if detect_stress(message) in ["high", "medium"]:
        return "💙 Je suis en local, mais je peux toujours t'aider. Respire, décris ton blocage et je te donne une approche pas à pas pour avancer."
    for topic, answer in LOCAL_KNOWLEDGE.items():
        if topic in text:
            return answer
    if "bonjour" in text or "salut" in text:
        return "👋 Salut ! Je suis en mode hors-ligne local. Pose ta question ou demande un résumé, et je te répondrai avec mes connaissances embarquées."
    if "aide" in text or "expliquer" in text or "comment" in text or "quoi" in text or "qu'est" in text:
        return "⚡ Mode hors-ligne : je suis localement disponible. Pose une question claire sur un concept de cours ou un cas pratique et je te donnerai une explication utile."
    return "⚡ Mode hors-ligne local : je n'ai pas de connexion Internet, mais je peux toujours t'aider avec des conseils théoriques, des plans de révision et des explications de base."

def degraded_response(message: str) -> str:
    msg_lower = message.lower()
    if "résumé" in msg_lower or "cours" in msg_lower:
        return DEGRADED_RESPONSES["résumé"]
    elif "planning" in msg_lower or "agenda" in msg_lower:
        return DEGRADED_RESPONSES["planning"]
    elif detect_stress(message) in ["high", "medium"]:
        return DEGRADED_RESPONSES["stress"]
    return DEGRADED_RESPONSES["default"]

# ─────────────────────────────────────────
# SAUVEGARDE LOCALE (RGPD — anonymisée)
# ─────────────────────────────────────────
def save_conversation(session_id, username, role, message, latency=0, source="cloud", stress="none"):
    anon_id = hashlib.sha256(session_id.encode()).hexdigest()[:16]
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("""INSERT INTO conversations (session_id, username, role, message, timestamp, latency_ms, source, stress_level)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
              (anon_id, username, role, message, datetime.now().isoformat(), latency, source, stress))
    conn.commit()
    conn.close()

# ─────────────────────────────────────────
# SYNCHRONISATION CLOUD SIMULÉE
# ─────────────────────────────────────────
def simulate_cloud_sync():
    """Simule une synchronisation périodique avec le Cloud (agrégats anonymisés seulement)"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM conversations WHERE timestamp > datetime('now', '-1 hour')")
    count = c.fetchone()[0]
    sync_data = {
        "total_queries_last_hour": count,
        "sync_time": datetime.now().isoformat(),
        "edge_node": "ENSA-BeniMellal-Edge-01"
    }
    c.execute("INSERT INTO sync_log (sync_time, records_synced, status) VALUES (?, ?, ?)",
              (datetime.now().isoformat(), count, "success"))
    conn.commit()
    conn.close()
    return sync_data

# ─────────────────────────────────────────
# ROUTES FLASK
# ─────────────────────────────────────────

def validate_password(password: str) -> tuple[bool, str]:
    if len(password) < 8:
        return False, "Le mot de passe doit contenir au moins 8 caractères."
    if not any(c.isupper() for c in password):
        return False, "Le mot de passe doit contenir au moins une majuscule."
    if not any(c.islower() for c in password):
        return False, "Le mot de passe doit contenir au moins une minuscule."
    if not any(c.isdigit() for c in password):
        return False, "Le mot de passe doit contenir au moins un chiffre."
    if not any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?/" for c in password):
        return False, "Le mot de passe doit contenir au moins un caractère spécial."
    return True, ""

# ✅ ROUTE LOGIN — gère connexion et inscription
@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    success = None
    if request.method == "POST":
        action   = request.form.get("action")
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")
        pwd_hash = hashlib.sha256(password.encode()).hexdigest()

        conn = get_db_connection()
        c = conn.cursor()

        if action == "register":
            if not username:
                error = "Le nom d'utilisateur est requis."
            elif not password or not confirm:
                error = "Veuillez renseigner tous les champs du mot de passe."
            elif password != confirm:
                error = "Les mots de passe ne correspondent pas."
            else:
                valid, msg = validate_password(password)
                if not valid:
                    error = msg
                else:
                    try:
                        c.execute("INSERT INTO users (username, password_hash, created_at) VALUES (?,?,?)",
                                  (username, pwd_hash, datetime.now().isoformat()))
                        conn.commit()
                        success = "Inscription réussie. Connectez-vous maintenant avec vos identifiants."
                    except sqlite3.IntegrityError:
                        error = "Ce nom d'utilisateur est déjà pris."

        elif action == "login":
            c.execute("SELECT id FROM users WHERE username=? AND password_hash=?", (username, pwd_hash))
            user = c.fetchone()
            if user:
                session["user"] = username
                session["session_id"] = os.urandom(16).hex()
                conn.close()
                return redirect("/")
            else:
                error = "Identifiants incorrects."

        conn.close()

    return render_template("login.html", error=error, success=success)

# ✅ ROUTE LOGOUT
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

# ✅ ROUTE INDEX — redirige vers login si non connecté
@app.route("/")
def index():
    if "user" not in session:
        return redirect("/login")
    if "session_id" not in session:
        session["session_id"] = os.urandom(16).hex()
    return render_template("index.html", username=session["user"])

@app.route("/profile", methods=["GET", "POST"])
def profile():
    if "user" not in session:
        return redirect("/login")

    message = None
    message_type = None
    if request.method == "POST":
        old_password = request.form.get("old_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not old_password or not new_password or not confirm_password:
            message = "Tous les champs doivent être remplis."
            message_type = "error"
        elif new_password != confirm_password:
            message = "Le nouveau mot de passe et sa confirmation ne correspondent pas."
            message_type = "error"
        elif len(new_password) < 8:
            message = "Le mot de passe doit contenir au moins 8 caractères."
            message_type = "error"
        else:
            conn = get_db_connection()
            c = conn.cursor()
            c.execute("SELECT password_hash FROM users WHERE username=?", (session["user"],))
            row = c.fetchone()
            if not row:
                message = "Utilisateur introuvable."
                message_type = "error"
                conn.close()
            else:
                current_hash = hashlib.sha256(old_password.encode()).hexdigest()
                if row[0] != current_hash:
                    message = "Le mot de passe actuel est incorrect."
                    message_type = "error"
                    conn.close()
                elif old_password == new_password:
                    message = "Le nouveau mot de passe doit être différent de l'ancien."
                    message_type = "error"
                    conn.close()
                else:
                    new_hash = hashlib.sha256(new_password.encode()).hexdigest()
                    c.execute("UPDATE users SET password_hash=? WHERE username=?", (new_hash, session["user"]))
                    conn.commit()
                    conn.close()
                    message = "Votre mot de passe a été mis à jour avec succès."
                    message_type = "success"

    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT created_at FROM users WHERE username=?", (session["user"],))
    row = c.fetchone()
    created_at = row[0] if row else None
    c.execute("SELECT COUNT(*) FROM conversations WHERE username=?", (session["user"],))
    total_messages = c.fetchone()[0]
    conn.close()
    return render_template(
        "profile.html",
        username=session["user"],
        created_at=created_at,
        total_messages=total_messages,
        message=message,
        message_type=message_type
    )

@app.route("/chat", methods=["POST"])
def chat():
    if "user" not in session:
        return jsonify({"error": "Non authentifié"}), 401

    data = request.json
    user_message = data.get("message", "").strip()
    history = data.get("history", [])

    if not user_message:
        return jsonify({"error": "Message vide"}), 400

    session_id = session.get("session_id", "anonymous")
    start_time = time.time()

    # ── ÉTAPE 1 : Détection stress (traitement Edge local — < 5ms) ──
    stress_level = detect_stress(user_message)

    # ── ÉTAPE 2 : Vérification RGPD (Edge local) ──
    if check_rgpd(user_message):
        return jsonify({
            "error": "Données personnelles détectées. RGPD : ne saisissez pas d'informations personnelles."
        }), 400

    # ── ÉTAPE 3 : Vérification cache Edge ──
    cache_key = get_cache_key(user_message)
    cached = get_from_cache(cache_key)
    if cached:
        latency = round((time.time() - start_time) * 1000, 2)
        save_conversation(session_id, session["user"], "user", user_message, latency, "edge_cache", stress_level)
        save_conversation(session_id, session["user"], "assistant", cached, latency, "edge_cache", "none")
        return jsonify({
            "response": stress_prefix(stress_level) + cached,
            "source": "edge_cache",
            "latency_ms": latency,
            "stress_level": stress_level,
            "latency_ok": latency < LATENCY_TARGET
        })

    # ── ÉTAPE 4 : Appel Cloud (Groq API) ──
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for h in history[-6:]:
        messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": user_message})

    try:
        completion = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            max_tokens=1024,
            temperature=0.7
        )
        response_text = completion.choices[0].message.content
        source = "cloud_groq"

        # ── ÉTAPE 5 : Mise en cache Edge ──
        set_cache(cache_key, response_text)

    except Exception as e:
        print(f"ERREUR GROQ: {e}")
        response_text = local_assistant_response(user_message)
        source = "edge_local"

    latency = round((time.time() - start_time) * 1000, 2)
    final_response = stress_prefix(stress_level) + response_text

    # ── ÉTAPE 6 : Historique + log RGPD (anonymisé) ──
    save_conversation(session_id, session["user"], "user", user_message, latency, source, stress_level)
    save_conversation(session_id, session["user"], "assistant", response_text, latency, source, "none")

    return jsonify({
        "response": final_response,
        "source": source,
        "latency_ms": latency,
        "stress_level": stress_level,
        "latency_ok": latency < LATENCY_TARGET
    })

@app.route("/historique")
def historique():
    if "user" not in session:
        return redirect("/login")
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("""SELECT role, message, timestamp, latency_ms, source, stress_level
                 FROM conversations WHERE username=? ORDER BY id DESC LIMIT 50""",
              (session["user"],))
    rows = c.fetchall()
    conn.close()
    convs = [{"role": r[0], "message": r[1], "timestamp": r[2],
               "latency_ms": r[3], "source": r[4], "stress_level": r[5]} for r in rows]
    return render_template("historique.html", conversations=convs)

@app.route("/stats")
def stats():
    if "user" not in session:
        return jsonify({"error": "Non authentifié"}), 401
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM conversations WHERE role='user'")
    total = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM edge_cache")
    cache_size = c.fetchone()[0]
    c.execute("SELECT AVG(latency_ms) FROM conversations WHERE source != 'edge_cache'")
    avg_latency = round(c.fetchone()[0] or 0, 2)
    c.execute("SELECT stress_level, COUNT(*) FROM conversations WHERE role='user' GROUP BY stress_level")
    stress_dist = dict(c.fetchall())
    c.execute("SELECT COUNT(*) FROM conversations WHERE source='edge_degraded'")
    degraded_count = c.fetchone()[0]
    conn.close()

    sync_data = simulate_cloud_sync()

    return jsonify({
        "total_queries": total,
        "cache_entries": cache_size,
        "avg_latency_ms": avg_latency,
        "latency_target_ms": LATENCY_TARGET,
        "stress_distribution": stress_dist,
        "degraded_mode_activations": degraded_count,
        "cloud_sync": sync_data
    })

@app.route("/planning", methods=["POST"])
def save_planning():
    if "user" not in session:
        return jsonify({"error": "Non authentifié"}), 401
    data = request.json
    session_id = session.get("session_id", "anonymous")
    conn = get_db_connection()
    c = conn.cursor()
    for item in data.get("planning", []):
        c.execute("""INSERT INTO planning (session_id, module, jour, heure, duree_min, priorite)
                     VALUES (?, ?, ?, ?, ?, ?)""",
                  (session_id, item["module"], item["jour"], item["heure"],
                   item.get("duree_min", 60), item.get("priorite", 2)))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok", "saved": len(data.get("planning", []))})

if __name__ == "__main__":
    print("🚀 Assistant IA Edge — ENSA Beni Mellal")
    print(f"   Modèle : {MODEL} via Groq Cloud")
    print(f"   Cache Edge TTL : {CACHE_TTL}s")
    print(f"   Latence cible : < {LATENCY_TARGET}ms")
    print("   Accès : http://localhost:5000")
    app.run(debug=True, host="0.0.0.0", port=5000)