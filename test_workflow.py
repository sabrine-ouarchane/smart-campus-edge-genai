"""
test_workflow.py — Vérification des 6 étapes du diagramme
Assistant IA Edge | ENSA Beni Mellal
"""

import requests
import json

BASE = "http://localhost:5000"
PASS = "✅"
FAIL = "❌"
results = []

def check(label, ok, detail=""):
    status = PASS if ok else FAIL
    results.append(ok)
    print(f"  {status}  {label}")
    if detail:
        print(f"       → {detail}")

print("\n" + "═"*55)
print("  TEST WORKFLOW — Assistant IA Edge ENSA Beni Mellal")
print("═"*55 + "\n")

# ──────────────────────────────────────────
# ÉTAPE 1 — Étudiant pose une question (Flask /chat)
# ──────────────────────────────────────────
print("📌 ÉTAPE 1 : Interface Flask — route /chat")
try:
    r = requests.post(f"{BASE}/chat",
                      json={"message": "Explique l'Edge Computing", "history": []},
                      timeout=30)
    check("Route /chat répond (200)", r.status_code == 200,
          f"status={r.status_code}")
    data = r.json()
    check("Réponse contient 'response'", "response" in data)
    check("Réponse non vide", bool(data.get("response", "").strip()))
except Exception as e:
    check("Route /chat accessible", False, str(e))
    data = {}

print()

# ──────────────────────────────────────────
# ÉTAPE 2 — Vérification RGPD (Edge local)
# ──────────────────────────────────────────
print("📌 ÉTAPE 2 : Vérification RGPD")
rgpd_tests = [
    ("cin", "carte nationale"),
    ("password", "mot de passe"),
    ("email perso", "email"),
    ("RIB bancaire", "rib"),
]
for label, keyword in rgpd_tests:
    try:
        r = requests.post(f"{BASE}/chat",
                          json={"message": f"Mon {keyword} est 12345", "history": []},
                          timeout=10)
        check(f"Bloque '{label}'", r.status_code == 400,
              f"status={r.status_code}")
    except Exception as e:
        check(f"Bloque '{label}'", False, str(e))

print()

# ──────────────────────────────────────────
# ÉTAPE 3 — Cache Edge (SQLite local)
# ──────────────────────────────────────────
print("📌 ÉTAPE 3 : Cache Edge")
try:
    msg = "Qu'est-ce que le machine learning ?"

    # Premier appel — doit aller au Cloud
    r1 = requests.post(f"{BASE}/chat",
                       json={"message": msg, "history": []}, timeout=30)
    d1 = r1.json()
    source1 = d1.get("source", "")
    check("1er appel : source cloud ou dégradé",
          source1 in ["cloud_groq", "edge_degraded"],
          f"source={source1}")

    # Deuxième appel — doit venir du cache
    r2 = requests.post(f"{BASE}/chat",
                       json={"message": msg, "history": []}, timeout=10)
    d2 = r2.json()
    source2 = d2.get("source", "")
    check("2e appel : source = edge_cache", source2 == "edge_cache",
          f"source={source2}")

    lat2 = d2.get("latency_ms", 9999)
    check(f"Cache ultra-rapide (< 50ms)", lat2 < 50, f"latency={lat2}ms")

except Exception as e:
    check("Test cache", False, str(e))

print()

# ──────────────────────────────────────────
# ÉTAPE 4 — Appel Cloud Groq
# ──────────────────────────────────────────
print("📌 ÉTAPE 4 : Appel Cloud (Groq API)")
try:
    # Message unique pour forcer un appel cloud (pas encore en cache)
    import time
    unique_msg = f"Définition unique test {int(time.time())}"
    r = requests.post(f"{BASE}/chat",
                      json={"message": unique_msg, "history": []}, timeout=30)
    d = r.json()
    source = d.get("source", "")
    check("Appel cloud ou dégradé réussi",
          source in ["cloud_groq", "edge_degraded"],
          f"source={source}")
    check("Latence retournée", "latency_ms" in d,
          f"latency={d.get('latency_ms')}ms")
    check("Indicateur latency_ok présent", "latency_ok" in d)
except Exception as e:
    check("Appel Cloud", False, str(e))

print()

# ──────────────────────────────────────────
# ÉTAPE 5 — Sauvegarde dans le cache
# ──────────────────────────────────────────
print("📌 ÉTAPE 5 : Sauvegarde cache (vérifiée via /stats)")
try:
    r = requests.get(f"{BASE}/stats", timeout=10)
    check("Route /stats répond", r.status_code == 200)
    s = r.json()
    check("cache_entries > 0", s.get("cache_entries", 0) > 0,
          f"entrées={s.get('cache_entries')}")
    check("avg_latency_ms présent", "avg_latency_ms" in s,
          f"avg={s.get('avg_latency_ms')}ms")
except Exception as e:
    check("Stats cache", False, str(e))

print()

# ──────────────────────────────────────────
# ÉTAPE 6 — Historique + log RGPD
# ──────────────────────────────────────────
print("📌 ÉTAPE 6 : Historique + log RGPD")
try:
    r = requests.get(f"{BASE}/historique", timeout=10)
    check("Route /historique répond (200)", r.status_code == 200,
          f"status={r.status_code}")
    check("Page HTML retournée", "text/html" in r.headers.get("Content-Type", ""))

    # Vérification stress_distribution dans stats
    rs = requests.get(f"{BASE}/stats", timeout=10)
    s = rs.json()
    check("stress_distribution présent", "stress_distribution" in s,
          str(s.get("stress_distribution")))
    check("total_queries > 0", s.get("total_queries", 0) > 0,
          f"total={s.get('total_queries')}")
    check("cloud_sync présent (anonymisé)", "cloud_sync" in s)
except Exception as e:
    check("Historique/Log", False, str(e))

print()

# ──────────────────────────────────────────
# BONUS — Mode dégradé
# ──────────────────────────────────────────
print("📌 BONUS : Mode dégradé (réponse locale si cloud KO)")
try:
    rs = requests.get(f"{BASE}/stats", timeout=10)
    s = rs.json()
    check("degraded_mode_activations tracké",
          "degraded_mode_activations" in s,
          f"count={s.get('degraded_mode_activations')}")
except Exception as e:
    check("Mode dégradé tracké", False, str(e))

# ──────────────────────────────────────────
# RÉSUMÉ
# ──────────────────────────────────────────
total = len(results)
passed = sum(results)
failed = total - passed

print("\n" + "═"*55)
print(f"  RÉSULTAT : {passed}/{total} tests passés", end="  ")
if failed == 0:
    print("🎉 PROJET 100% FONCTIONNEL")
elif failed <= 2:
    print("⚠️  Quelques points à vérifier")
else:
    print("❌  Des étapes ne fonctionnent pas")
print("═"*55 + "\n")