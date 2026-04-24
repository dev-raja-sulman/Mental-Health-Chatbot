import os
import pickle
import sqlite3
import datetime
import random
import csv
import io
import json
import hashlib
import uuid
import torch
from flask import Flask, request, jsonify, render_template, Response, session, redirect, url_for
from transformers import AutoModelForSequenceClassification, AutoTokenizer

# Load .env if python-dotenv is installed
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────
MODEL_DIR = os.path.join(os.path.dirname(__file__), "MentalHealthModel")
DB_PATH   = os.path.join(os.path.dirname(__file__), "chat_history.db")

CRISIS_LABELS = {"Suicidal", "suicidal", "suicide", "Suicide"}

# ─────────────────────────────────────────────
# ADMIN CREDENTIALS
# ─────────────────────────────────────────────
ADMIN_ID       = "raja"
ADMIN_PASSWORD = "786"

EMERGENCY_RESPONSE = (
    "⚠️ CRISIS ALERT — Please read this carefully.\n\n"
    "It sounds like you may be in serious distress. Your life has value "
    "and help is available right now.\n\n"
    "Immediate Resources:\n"
    "• National Suicide Prevention Lifeline: 988 (call or text, 24/7)\n"
    "• Crisis Text Line: Text HOME to 741741\n"
    "• International: https://www.iasp.info/resources/Crisis_Centres/\n"
    "• Emergency Services: 911\n\n"
    "Please reach out to one of these resources or go to your nearest "
    "emergency room. You do not have to face this alone."
)

# ── Rich multi-response fallbacks per label ──────────────────
# Used when Gemini is unavailable — randomly selected so responses
# don't feel repetitive across turns.
SMART_FALLBACKS = {
    "Anxiety": [
        "I can hear that anxiety is weighing on you right now. That feeling of worry can be really exhausting. Let's take this one breath at a time — what's the biggest thing on your mind?",
        "Anxiety can make everything feel urgent and overwhelming. You're not alone in this. Can you tell me more about what's been triggering these feelings?",
        "It takes courage to acknowledge anxiety. Your feelings are completely valid. Would a simple grounding exercise help you feel more centered right now?",
        "I understand how unsettling anxiety can feel. Remember, this feeling is temporary. What's one small thing you could do right now to feel a little safer?",
    ],
    "Depression": [
        "I'm really glad you're talking about this. Depression can make everything feel heavy and distant. I'm here to listen — what's been the hardest part of your day?",
        "Thank you for trusting me with how you're feeling. Depression is real and it's not your fault. You don't have to carry this alone. What's been on your mind?",
        "I hear you, and I want you to know your feelings matter. Even small steps forward count. Is there anything — even tiny — that brought you a moment of relief recently?",
        "Depression can make it hard to see a way forward, but you reaching out shows real strength. What would feel most supportive for you right now?",
    ],
    "Stress": [
        "It sounds like you're carrying a lot right now. Stress can build up quietly until it feels unbearable. What's been putting the most pressure on you lately?",
        "That level of stress sounds really draining. Your mind and body are telling you they need some care. What does your day look like — is there any space for rest?",
        "Stress is your body's signal that something needs attention. You're doing the right thing by acknowledging it. What's one thing you could let go of today, even temporarily?",
        "I can sense how much you're dealing with. Remember, you don't have to solve everything at once. What feels most urgent to you right now?",
    ],
    "Normal": [
        "It's good to hear from you. Even on calm days, it's valuable to check in with yourself. Is there anything on your mind you'd like to explore or talk through?",
        "I'm glad you're doing okay. These quieter moments are a great time to reflect. How have you been taking care of yourself lately?",
        "It's wonderful that you're feeling balanced. Is there anything you'd like to work on or any goals you'd like to talk about today?",
        "Good to connect with you. Sometimes the best conversations happen when things are calm. What's been going well for you recently?",
    ],
    "Bipolar": [
        "Thank you for sharing that with me. Navigating mood shifts can be really challenging. How are you feeling right now in this moment?",
        "I appreciate your openness. Bipolar experiences can feel like a rollercoaster. What kind of support feels most helpful to you today?",
        "Your awareness of your own emotional patterns shows real insight. How has your energy been lately — are you in a high or low phase right now?",
        "Living with mood fluctuations takes a lot of resilience. I'm here to support you through whatever you're experiencing. What's been most difficult recently?",
    ],
    "Personality disorder": [
        "I appreciate you opening up. Navigating intense emotions and relationships can be really hard. What's been most challenging for you lately?",
        "Thank you for trusting me. Your experiences and feelings are valid. What would feel most supportive for you in this conversation?",
        "I hear you, and I want you to know you're not defined by your diagnosis. What's been on your mind that you'd like to talk through?",
        "It takes real courage to seek support. Let's take this at your pace. What's the most important thing you'd like me to understand about what you're going through?",
    ],
}

DEFAULT_FALLBACKS = [
    "Thank you for sharing that with me. I'm here to listen and support you. Can you tell me more about what you're experiencing?",
    "I hear you, and your feelings are completely valid. What would be most helpful for you right now?",
    "It takes strength to reach out. I'm here with you. What's been weighing on your mind?",
]

# ─────────────────────────────────────────────
# FLASK APP
# ─────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "ethereal-clinic-secret-2024")

# ─────────────────────────────────────────────
# DATABASE
# ─────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # ── Users table ──────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id     TEXT PRIMARY KEY,
            username    TEXT UNIQUE NOT NULL,
            email       TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            full_name   TEXT,
            created_at  TEXT NOT NULL,
            last_login  TEXT
        )
    """)
    # ── Sessions table ───────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_id  TEXT PRIMARY KEY,
            user_id     TEXT,
            created_at  TEXT NOT NULL,
            last_active TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
    """)
    # ── Migrate: add user_id column if it doesn't exist ──────
    try:
        c.execute("ALTER TABLE sessions ADD COLUMN user_id TEXT")
        print("[DB] Migrated: added user_id column to sessions")
    except Exception:
        pass  # column already exists — fine
    c.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id  TEXT NOT NULL,
            role        TEXT NOT NULL,
            content     TEXT NOT NULL,
            label       TEXT,
            timestamp   TEXT NOT NULL,
            FOREIGN KEY (session_id) REFERENCES sessions(session_id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS user_states (
            session_id  TEXT PRIMARY KEY,
            last_label  TEXT,
            turn_count  INTEGER DEFAULT 0,
            FOREIGN KEY (session_id) REFERENCES sessions(session_id)
        )
    """)
    conn.commit()
    conn.close()


def upsert_session(session_id, user_id=None):
    now = datetime.datetime.utcnow().isoformat()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT OR IGNORE INTO sessions (session_id, user_id, created_at, last_active) VALUES (?,?,?,?)",
        (session_id, user_id, now, now),
    )
    c.execute("UPDATE sessions SET last_active=? WHERE session_id=?", (now, session_id))
    conn.commit()
    conn.close()


# ── User auth helpers ─────────────────────────────────────────
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


def generate_user_id():
    """Generate a short readable user ID like EC-A3F2B1."""
    return "EC-" + uuid.uuid4().hex[:6].upper()


def create_user(username, email, password, full_name=""):
    user_id   = generate_user_id()
    pw_hash   = hash_password(password)
    now       = datetime.datetime.utcnow().isoformat()
    conn      = sqlite3.connect(DB_PATH)
    c         = conn.cursor()
    try:
        c.execute(
            "INSERT INTO users (user_id,username,email,password_hash,full_name,created_at) VALUES (?,?,?,?,?,?)",
            (user_id, username.lower().strip(), email.lower().strip(), pw_hash, full_name.strip(), now),
        )
        conn.commit()
        return {"ok": True, "user_id": user_id}
    except sqlite3.IntegrityError as e:
        err = str(e)
        if "username" in err:
            return {"ok": False, "error": "Username already taken."}
        if "email" in err:
            return {"ok": False, "error": "Email already registered."}
        return {"ok": False, "error": "Registration failed."}
    finally:
        conn.close()


def verify_user(username_or_email, password):
    pw_hash = hash_password(password)
    conn    = sqlite3.connect(DB_PATH)
    c       = conn.cursor()
    c.execute(
        """SELECT user_id, username, full_name FROM users
           WHERE (username=? OR email=?) AND password_hash=?""",
        (username_or_email.lower().strip(),
         username_or_email.lower().strip(), pw_hash),
    )
    row = c.fetchone()
    if row:
        now = datetime.datetime.utcnow().isoformat()
        c.execute("UPDATE users SET last_login=? WHERE user_id=?", (now, row[0]))
        conn.commit()
    conn.close()
    return {"user_id": row[0], "username": row[1], "full_name": row[2]} if row else None


def get_user_by_id(user_id):
    conn = sqlite3.connect(DB_PATH)
    c    = conn.cursor()
    c.execute("SELECT user_id,username,email,full_name,created_at,last_login FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    return {"user_id": row[0], "username": row[1], "email": row[2],
            "full_name": row[3], "created_at": row[4], "last_login": row[5]}


def save_message(session_id, role, content, label=None):
    now = datetime.datetime.utcnow().isoformat()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO messages (session_id,role,content,label,timestamp) VALUES (?,?,?,?,?)",
        (session_id, role, content, label, now),
    )
    conn.commit()
    conn.close()


def update_user_state(session_id, label):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO user_states (session_id, last_label, turn_count) VALUES (?,?,1)
        ON CONFLICT(session_id) DO UPDATE SET
            last_label = excluded.last_label,
            turn_count = turn_count + 1
        """,
        (session_id, label),
    )
    conn.commit()
    conn.close()


def get_chat_history(session_id, limit=20):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT role,content,label,timestamp FROM messages "
        "WHERE session_id=? ORDER BY id DESC LIMIT ?",
        (session_id, limit),
    )
    rows = c.fetchall()
    conn.close()
    return [
        {"role": r[0], "content": r[1], "label": r[2], "timestamp": r[3]}
        for r in reversed(rows)
    ]


def get_user_state(session_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT last_label, turn_count FROM user_states WHERE session_id=?",
        (session_id,),
    )
    row = c.fetchone()
    conn.close()
    return (
        {"last_label": row[0], "turn_count": row[1]}
        if row
        else {"last_label": None, "turn_count": 0}
    )


def get_smart_fallback(label):
    """Return a random empathetic response for the given label."""
    options = SMART_FALLBACKS.get(label, DEFAULT_FALLBACKS)
    return random.choice(options)


# ─────────────────────────────────────────────
# BERT MODEL
# ─────────────────────────────────────────────
_tokenizer     = None
_bert_model    = None
_label_encoder = None
_device        = None


def load_model():
    global _tokenizer, _bert_model, _label_encoder, _device
    if _bert_model is not None:
        return
    _device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"[BERT] Loading model on {_device}")
    _tokenizer  = AutoTokenizer.from_pretrained(MODEL_DIR)
    _bert_model = AutoModelForSequenceClassification.from_pretrained(MODEL_DIR)
    _bert_model.to(_device)
    _bert_model.eval()
    with open(os.path.join(MODEL_DIR, "label_encoder.pkl"), "rb") as f:
        _label_encoder = pickle.load(f)
    print(f"[BERT] Ready. Classes: {list(_label_encoder.classes_)}")


def classify_text(text):
    inputs = _tokenizer(
        text, return_tensors="pt", truncation=True, padding=True, max_length=512
    ).to(_device)
    with torch.no_grad():
        outputs    = _bert_model(**inputs)
        prediction = torch.argmax(outputs.logits, dim=1).item()
    return _label_encoder.inverse_transform([prediction])[0]


# ─────────────────────────────────────────────
# OLLAMA  (local LLaMA — no API key needed)
# Install: https://ollama.com/download
# Then run: ollama pull llama3.2
# ─────────────────────────────────────────────
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL    = os.environ.get("OLLAMA_MODEL",    "llama3.2")

_llm_ready  = False
_llm_model  = None
_llm_error  = None


def _init_llm():
    """Ping Ollama and verify the model is available."""
    global _llm_ready, _llm_model, _llm_error
    import urllib.request

    try:
        req  = urllib.request.urlopen(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        data = json.loads(req.read().decode())
    except Exception as e:
        _llm_error = f"Ollama not reachable at {OLLAMA_BASE_URL} — start with: ollama serve"
        print(f"[Ollama] ✗ {_llm_error}")
        return

    available = [m.get("name", "") for m in data.get("models", [])]
    print(f"[Ollama] Available models: {available}")

    # Match exact or prefix (e.g. "llama3.2" matches "llama3.2:latest")
    matched = next(
        (m for m in available
         if m == OLLAMA_MODEL or m.startswith(OLLAMA_MODEL.split(":")[0])),
        None
    )

    if not matched:
        # Try a live generate — Ollama may serve it even if not listed
        try:
            _ollama_generate("hi", OLLAMA_MODEL)
            matched = OLLAMA_MODEL
        except Exception:
            _llm_error = (
                f"Model '{OLLAMA_MODEL}' not found.\n"
                f"Run: ollama pull {OLLAMA_MODEL}\n"
                f"Available: {available or 'none — run: ollama pull llama3.2'}"
            )
            print(f"[Ollama] ✗ {_llm_error}")
            return

    _llm_ready = True
    _llm_model = matched or OLLAMA_MODEL
    print(f"[Ollama] ✓ Ready — model: {_llm_model}")


def _ollama_generate(prompt: str, model: str) -> str:
    """Raw Ollama /api/generate call."""
    import urllib.request
    payload = json.dumps({
        "model":  model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature":        0.75,
            "top_p":              0.9,
            "repeat_penalty":     1.2,
            "num_predict":        300,
        },
    }).encode()
    req = urllib.request.Request(
        f"{OLLAMA_BASE_URL}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        result = json.loads(resp.read().decode())
    return result.get("response", "").strip()


def _build_llm_prompt(user_input: str, label: str,
                      history: list, user_name: str = "") -> str:
    """
    Build a rich counselor prompt with:
    - Dr. Aria persona + BERT label context
    - Last 8 turns of conversation history
    - Current user message
    """
    name_part = f" The patient's name is {user_name}." if user_name else ""
    system = (
        f"You are Dr. Aria, a compassionate and professional mental health counselor "
        f"at The Ethereal Clinic.{name_part}\n"
        f"The patient is currently experiencing: {label}.\n"
        f"Instructions:\n"
        f"- Acknowledge and validate their feelings warmly.\n"
        f"- Respond in 3-5 sentences, conversational and human.\n"
        f"- Ask one gentle follow-up question.\n"
        f"- Never diagnose or prescribe medication.\n"
        f"- If crisis is detected, encourage professional help immediately.\n\n"
    )

    recent = history[-8:] if len(history) > 8 else history
    convo  = ""
    for msg in recent:
        if msg["role"] == "user":
            convo += f"Patient: {msg['content']}\n"
        elif msg["role"] in ("assistant", "counselor"):
            convo += f"Dr. Aria: {msg['content']}\n"

    return f"{system}{convo}Patient: {user_input}\nDr. Aria:"


def get_llm_response(user_input: str, label: str,
                     history: list, user_name: str = "") -> str:
    """Get a response from local Ollama LLaMA model."""
    if not _llm_ready:
        raise RuntimeError(_llm_error or "Ollama not available")
    prompt = _build_llm_prompt(user_input, label, history, user_name)
    reply  = _ollama_generate(prompt, _llm_model)

    # Clean up — stop at next "Patient:" if model kept going
    if "Patient:" in reply:
        reply = reply.split("Patient:")[0].strip()
    if len(reply) < 8:
        raise ValueError("Response too short")
    return reply


# ─────────────────────────────────────────────
# USER AUTH ROUTES
# ─────────────────────────────────────────────

@app.route("/login", methods=["GET", "POST"])
def user_login():
    if session.get("user_id"):
        return redirect(url_for("index"))
    error = None
    if request.method == "POST":
        identifier = request.form.get("identifier", "").strip()
        password   = request.form.get("password", "").strip()
        user = verify_user(identifier, password)
        if user:
            session["user_id"]   = user["user_id"]
            session["username"]  = user["username"]
            session["full_name"] = user["full_name"] or user["username"]
            return redirect(url_for("index"))
        error = "Invalid username/email or password."
    return render_template("user_login.html", error=error, mode="login")


@app.route("/signup", methods=["GET", "POST"])
def user_signup():
    if session.get("user_id"):
        return redirect(url_for("index"))
    error   = None
    success = None
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        username  = request.form.get("username", "").strip()
        email     = request.form.get("email", "").strip()
        password  = request.form.get("password", "").strip()
        confirm   = request.form.get("confirm", "").strip()

        if not username or not email or not password:
            error = "All fields are required."
        elif len(username) < 3:
            error = "Username must be at least 3 characters."
        elif len(password) < 4:
            error = "Password must be at least 4 characters."
        elif password != confirm:
            error = "Passwords do not match."
        else:
            result = create_user(username, email, password, full_name)
            if result["ok"]:
                success = f"Account created! Your Patient ID is {result['user_id']}. Please log in."
            else:
                error = result["error"]
    return render_template("user_login.html", error=error, success=success, mode="signup")


@app.route("/logout", methods=["GET"])
def user_logout():
    session.pop("user_id",   None)
    session.pop("username",  None)
    session.pop("full_name", None)
    return redirect(url_for("user_login"))


@app.route("/me", methods=["GET"])
def user_profile():
    """Return current logged-in user info as JSON."""
    uid = session.get("user_id")
    if not uid:
        return jsonify({"error": "Not logged in"}), 401
    user = get_user_by_id(uid)
    return jsonify(user), 200


# ─────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────
@app.route("/", methods=["GET"])
def index():
    if not session.get("user_id"):
        return redirect(url_for("user_login"))
    return render_template("index.html",
                           username=session.get("username"),
                           full_name=session.get("full_name"),
                           user_id=session.get("user_id"))


@app.route("/dashboard", methods=["GET"])
def dashboard():
    return render_template("index.html")


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status":      "ok",
        "bert_loaded": _bert_model is not None,
        "llm_ready":   _llm_ready,
        "llm_model":   _llm_model,
        "llm_error":   _llm_error,
        "ollama_url":  OLLAMA_BASE_URL,
    }), 200


@app.route("/test-llm", methods=["GET"])
def test_llm():
    if _llm_ready:
        return jsonify({
            "status":  "OK",
            "model":   _llm_model,
            "message": f"Ollama LLaMA is running — model: {_llm_model}",
        }), 200
    return jsonify({
        "status": "FAIL",
        "error":  _llm_error,
        "fix": [
            "1. Download Ollama: https://ollama.com/download",
            "2. Open a NEW terminal after install",
            f"3. Run: ollama pull {OLLAMA_MODEL}",
            "4. Run: ollama serve  (keep this terminal open)",
            "5. Restart Flask: python app.py",
        ],
    }), 200


@app.route("/chat", methods=["POST"])
def chat():
    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"error": "Request body must be JSON."}), 400

        session_id   = data.get("session_id", "").strip()
        user_message = data.get("message", "").strip()

        if not session_id:
            return jsonify({"error": "session_id is required."}), 400
        if not user_message:
            return jsonify({"error": "message is required."}), 400

        # 1. Session
        upsert_session(session_id, user_id=session.get("user_id"))

        # 2. BERT classification
        try:
            label = classify_text(user_message)
            print(f"[BERT] '{user_message[:60]}' → {label}")
        except Exception as e:
            app.logger.error("BERT failed: %s", e)
            return jsonify({"error": "Classification failed.", "detail": str(e)}), 500

        # 3. Save user turn
        save_message(session_id, "user", user_message, label)
        update_user_state(session_id, label)

        # 4. Crisis check — always hardcoded, never LLM
        is_crisis   = label in CRISIS_LABELS
        llm_used    = False
        llm_error   = None

        if is_crisis:
            bot_response = EMERGENCY_RESPONSE

        elif _llm_ready:
            history = get_chat_history(session_id)
            # Get user's name for personalised responses
            user_name = session.get("full_name") or session.get("username") or ""
            try:
                bot_response = get_llm_response(user_message, label, history, user_name)
                llm_used     = True
                print(f"[Groq] ✓ {len(bot_response)} chars — label: {label}")
            except Exception as e:
                llm_error    = str(e)
                print(f"[Groq] ✗ {e}")
                bot_response = get_smart_fallback(label)

        else:
            bot_response = get_smart_fallback(label)
            llm_error    = _llm_error
            print(f"[Fallback] LLM offline — label: {label}")

        # 5. Save bot turn
        save_message(session_id, "assistant", bot_response)

        # 6. Return
        history = get_chat_history(session_id)
        return jsonify({
            "session_id":  session_id,
            "label":       label,
            "response":    bot_response,
            "is_crisis":   is_crisis,
            "llm_used":    llm_used,
            "llm_engine":  f"groq/{_llm_model}" if llm_used else "fallback",
            "llm_error":   llm_error,
            "history":     history,
        }), 200

    except Exception as e:
        app.logger.error("Unhandled /chat error: %s", e, exc_info=True)
        return jsonify({
            "error":    "Internal server error",
            "detail":   str(e),
            "response": get_smart_fallback("Normal"),
            "label":    "Unknown",
            "is_crisis": False,
            "llm_used": False,
            "history":  [],
        }), 200  # return 200 so frontend still shows the fallback message


@app.route("/history/<session_id>", methods=["GET"])
def get_history(session_id):
    return jsonify({
        "session_id": session_id,
        "state":      get_user_state(session_id),
        "history":    get_chat_history(session_id, limit=100),
    }), 200


@app.route("/sessions", methods=["GET"])
def list_sessions():
    conn = sqlite3.connect(DB_PATH)
    c    = conn.cursor()
    c.execute(
        "SELECT session_id, created_at, last_active FROM sessions ORDER BY last_active DESC"
    )
    rows = c.fetchall()
    conn.close()
    return jsonify({
        "sessions": [
            {"session_id": r[0], "created_at": r[1], "last_active": r[2]}
            for r in rows
        ]
    }), 200


# ─────────────────────────────────────────────
# ADMIN — Patient History Panel
# ─────────────────────────────────────────────

@app.route("/admin", methods=["GET"])
def admin_panel():
    """Serve the admin patient history UI — requires login."""
    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login"))
    return render_template("admin.html")


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    """Admin login page."""
    error = None
    if request.method == "POST":
        admin_id  = request.form.get("admin_id", "").strip()
        password  = request.form.get("password", "").strip()
        if admin_id == ADMIN_ID and password == ADMIN_PASSWORD:
            session["admin_logged_in"] = True
            return redirect(url_for("admin_panel"))
        error = "Invalid ID or password. Please try again."
    return render_template("admin_login.html", error=error)


@app.route("/admin/logout", methods=["GET"])
def admin_logout():
    """Log out of admin panel."""
    session.pop("admin_logged_in", None)
    return redirect(url_for("admin_login"))


@app.route("/admin/stats", methods=["GET"])
def admin_stats():
    """All sessions + aggregate stats for the admin panel."""
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    conn = sqlite3.connect(DB_PATH)
    c    = conn.cursor()

    c.execute("SELECT COUNT(*) FROM sessions")
    total_sessions = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM messages WHERE role='user'")
    total_messages = c.fetchone()[0]

    c.execute("""
        SELECT label, COUNT(*) as cnt FROM messages
        WHERE role='user' AND label IS NOT NULL
        GROUP BY label ORDER BY cnt DESC
    """)
    label_counts = {row[0]: row[1] for row in c.fetchall()}

    c.execute("""
        SELECT s.session_id, s.created_at, s.last_active,
               COALESCE(us.last_label,'Unknown') AS last_label,
               COALESCE(us.turn_count, 0)        AS turn_count,
               (SELECT COUNT(*) FROM messages m
                WHERE m.session_id = s.session_id) AS msg_count,
               u.username, u.user_id
        FROM sessions s
        LEFT JOIN user_states us ON s.session_id = us.session_id
        LEFT JOIN users u ON s.user_id = u.user_id
        ORDER BY s.last_active DESC
    """)
    sessions = [
        {
            "session_id":  r[0],
            "created_at":  r[1],
            "last_active": r[2],
            "last_label":  r[3],
            "turn_count":  r[4],
            "msg_count":   r[5],
            "username":    r[6],
            "user_id":     r[7],
        }
        for r in c.fetchall()
    ]
    conn.close()

    return jsonify({
        "total_sessions":     total_sessions,
        "total_messages":     total_messages,
        "label_distribution": label_counts,
        "sessions":           sessions,
        "gemini_status": {
            "ready": _llm_ready,
            "model": _llm_model,
            "error": _llm_error,
        },
    }), 200


@app.route("/admin/delete/<session_id>", methods=["DELETE"])
def delete_session(session_id):
    """Delete a single session and all its messages."""
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    conn = sqlite3.connect(DB_PATH)
    c    = conn.cursor()
    c.execute("DELETE FROM messages    WHERE session_id=?", (session_id,))
    c.execute("DELETE FROM user_states WHERE session_id=?", (session_id,))
    c.execute("DELETE FROM sessions    WHERE session_id=?", (session_id,))
    conn.commit()
    conn.close()
    return jsonify({"status": "deleted", "session_id": session_id}), 200


@app.route("/admin/delete-all", methods=["DELETE"])
def delete_all():
    """Wipe the entire database."""
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    conn = sqlite3.connect(DB_PATH)
    c    = conn.cursor()
    c.execute("DELETE FROM messages")
    c.execute("DELETE FROM user_states")
    c.execute("DELETE FROM sessions")
    conn.commit()
    conn.close()
    return jsonify({"status": "all_deleted"}), 200


@app.route("/admin/export/<session_id>/json", methods=["GET"])
def export_session_json(session_id):
    """Download one session as JSON."""
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    payload = {
        "session_id":  session_id,
        "exported_at": datetime.datetime.utcnow().isoformat(),
        "state":       get_user_state(session_id),
        "messages":    get_chat_history(session_id, limit=1000),
    }
    return Response(
        json.dumps(payload, indent=2, ensure_ascii=False),
        mimetype="application/json",
        headers={"Content-Disposition":
                 f"attachment; filename=session_{session_id[:12]}.json"},
    )


@app.route("/admin/export/<session_id>/csv", methods=["GET"])
def export_session_csv(session_id):
    """Download one session as CSV."""
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    history = get_chat_history(session_id, limit=1000)
    out     = io.StringIO()
    w       = csv.DictWriter(out, fieldnames=["timestamp","role","label","content"])
    w.writeheader()
    for msg in history:
        w.writerow({k: msg.get(k,"") for k in ["timestamp","role","label","content"]})
    return Response(
        out.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition":
                 f"attachment; filename=session_{session_id[:12]}.csv"},
    )


@app.route("/admin/export-all/json", methods=["GET"])
def export_all_json():
    """Download every session as one JSON file."""
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    conn = sqlite3.connect(DB_PATH)
    c    = conn.cursor()
    c.execute("SELECT session_id, created_at, last_active FROM sessions ORDER BY last_active DESC")
    rows = c.fetchall()
    conn.close()
    all_data = [
        {
            "session_id":  r[0], "created_at": r[1], "last_active": r[2],
            "state":       get_user_state(r[0]),
            "messages":    get_chat_history(r[0], limit=1000),
        }
        for r in rows
    ]
    payload = {
        "exported_at":    datetime.datetime.utcnow().isoformat(),
        "total_sessions": len(all_data),
        "sessions":       all_data,
    }
    return Response(
        json.dumps(payload, indent=2, ensure_ascii=False),
        mimetype="application/json",
        headers={"Content-Disposition": "attachment; filename=all_sessions.json"},
    )


@app.route("/admin/respond", methods=["POST"])
def counselor_respond():
    """Inject a manual counselor message into a patient session."""
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    data       = request.get_json(silent=True) or {}
    session_id = data.get("session_id", "").strip()
    message    = data.get("message", "").strip()
    if not session_id:
        return jsonify({"error": "session_id required"}), 400
    if not message:
        return jsonify({"error": "message required"}), 400
    save_message(session_id, "counselor", message, label="Manual")
    return jsonify({"status": "sent", "session_id": session_id}), 200


# ─────────────────────────────────────────────
# STARTUP
# ─────────────────────────────────────────────
with app.app_context():
    init_db()
    load_model()
    _init_llm()   # connect to Groq LLM at startup

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
