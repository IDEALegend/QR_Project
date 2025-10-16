# main.py
from flask import Flask, render_template, request, redirect, url_for, jsonify, session, flash, send_file
import os
import json
from datetime import datetime
from pyzbar.pyzbar import decode
import cv2
from werkzeug.utils import secure_filename
import qrcode
import csv
from io import StringIO, BytesIO
from werkzeug.exceptions import RequestEntityTooLarge
from functools import wraps
import pandas as pd
from xlsxwriter import Workbook
import requests
from dotenv import load_dotenv

# load .env if present
load_dotenv()

# ---------------------------
# Configuration
# ---------------------------
SERVICE_ACCOUNT = os.getenv("SERVICE_ACCOUNT", "qrpenguincloud-firebase-adminsdk.json")
API_KEY = os.getenv("FIREBASE_WEB_API_KEY", os.getenv("FIREBASE_API_KEY", "YOUR_FIREBASE_WEB_API_KEY"))
# If you didn't set env var, replace the above placeholder string with your API key string manually.

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "fallback-secret-key")

# File upload / folders
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10MB
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['STATIC_QR_FOLDER'] = os.path.join('static', 'qr')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['STATIC_QR_FOLDER'], exist_ok=True)

# Admin password for protected routes (if used anywhere)
PROTECTED_PASSWORD = os.getenv("ADMIN_PASSWORD", "fallback-admin")

# Firestore toggles
FIRESTORE_WRITE = os.getenv("FIRESTORE_WRITE", "1").lower() in ("1", "true", "yes")
FIRESTORE_READ = os.getenv("FIRESTORE_READ", "1").lower() in ("1", "true", "yes")

# ---------------------------
# Initialize Firebase Admin & Firestore
# ---------------------------
import firebase_admin
from firebase_admin import credentials, auth, firestore
try:
    if not os.path.exists(SERVICE_ACCOUNT):
        raise FileNotFoundError(f"Service account file '{SERVICE_ACCOUNT}' not found in project root.")
    cred = credentials.Certificate(SERVICE_ACCOUNT)
    firebase_admin.initialize_app(cred)
    firestore_db = firestore.client()
    print("✅ Firebase Admin initialized")
except Exception as e:
    firestore_db = None
    print(f"❌ Failed to initialize Firebase Admin SDK: {e}")
    # If Firestore not available, app will still run but many features disabled.

# ---------------------------
# Helpers: session & user profile
# ---------------------------
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("authenticated") or not session.get("firebase_uid"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper

def get_uid():
    """Return current firebase uid from session (or None)."""
    return session.get("firebase_uid")

def create_user_profile(uid, username, email):
    """Create a user profile document in Firestore under users/{uid}/profile."""
    try:
        if firestore_db is None or not FIRESTORE_WRITE:
            return False
        profile_ref = firestore_db.collection("users").document(uid).collection("meta").document("profile")
        profile_ref.set({
            "username": username,
            "email": email,
            "created_at": firestore.SERVER_TIMESTAMP
        }, merge=True)
        # Maintain a usernames mapping for quick username->uid lookup
        # (optional, but useful for your existing username-based flows)
        firestore_db.collection("usernames").document(username.lower()).set({
            "uid": uid,
            "username": username,
            "email": email,
            "created_at": firestore.SERVER_TIMESTAMP
        }, merge=True)
        # Create default meta counts doc
        firestore_db.collection("users").document(uid).collection("meta").document("counts").set({}, merge=True)
        return True
    except Exception as e:
        print(f"Warning: create_user_profile failed: {e}")
        return False

def get_profile_by_username(username):
    """Return profile dict by username lookup (using usernames collection)."""
    if firestore_db is None or not FIRESTORE_READ:
        return None
    try:
        doc = firestore_db.collection("usernames").document(username.lower()).get()
        if doc.exists:
            data = doc.to_dict()
            return data
    except Exception as e:
        print(f"Warning: get_profile_by_username failed: {e}")
    return None

def get_profile_by_uid(uid):
    """Return profile doc data for a uid."""
    if firestore_db is None or not FIRESTORE_READ:
        return None
    try:
        doc = firestore_db.collection("users").document(uid).collection("meta").document("profile").get()
        if doc.exists:
            return doc.to_dict()
    except Exception as e:
        print(f"Warning: get_profile_by_uid failed: {e}")
    return None

# ---------------------------
# Scan counts helper
# ---------------------------
def increment_scan_count(uid, scan_type):
    """Increment count for a given scan type in /users/{uid}/meta/counts."""
    if firestore_db is None or not FIRESTORE_WRITE:
        return
    try:
        counts_ref = firestore_db.collection("users").document(uid).collection("meta").document("counts")
        # Atomic increment
        counts_ref.set({scan_type: firestore.Increment(1)}, merge=True)
    except Exception as e:
        print(f"Warning: increment_scan_count failed: {e}")

def get_scan_counts(uid=None):
    """Return counts dict for a user or global aggregated counts fallback."""
    try:
        if firestore_db is None or not FIRESTORE_READ:
            return {}
        if uid:
            doc = firestore_db.collection("users").document(uid).collection("meta").document("counts").get()
            if doc.exists:
                return doc.to_dict()
            else:
                return {}
        else:
            return {}
    except Exception as e:
        print(f"Warning: get_scan_counts failed: {e}")
        return {}

# ---------------------------
# Utility: Firestore read/write wrappers
# ---------------------------
def add_scan_to_firestore(uid, data, scan_type, extra=None):
    """Add a scan doc to /users/{uid}/scans"""
    if firestore_db is None or not FIRESTORE_WRITE or not uid:
        return None
    try:
        doc = {
            "data": data,
            "type": scan_type,
            "firebase_uid": uid,
            "timestamp": firestore.SERVER_TIMESTAMP
        }
        if extra:
            doc.update(extra)
        ref = firestore_db.collection("users").document(uid).collection("scans").add(doc)
        # increment counts
        increment_scan_count(uid, scan_type)
        return ref
    except Exception as e:
        print(f"Warning: add_scan_to_firestore failed: {e}")
        return None

def add_record_to_firestore(uid, record_obj):
    """Write a record dict to /users/{uid}/records with auto id."""
    if firestore_db is None or not FIRESTORE_WRITE or not uid:
        return None
    try:
        # record_obj is expected to be a dict with title, subtitle, code, folder_id (optional)
        record_obj.setdefault("firebase_uid", uid)
        record_obj.setdefault("created_at", firestore.SERVER_TIMESTAMP)
        record_obj.setdefault("updated_at", firestore.SERVER_TIMESTAMP)
        ref = firestore_db.collection("users").document(uid).collection("records").add(record_obj)
        return ref
    except Exception as e:
        print(f"Warning: add_record_to_firestore failed: {e}")
        return None

def update_record_firestore(uid, record_id, update_fields):
    try:
        if firestore_db is None or not FIRESTORE_WRITE or not uid:
            return False
        doc_ref = firestore_db.collection("users").document(uid).collection("records").document(record_id)
        update_fields["updated_at"] = firestore.SERVER_TIMESTAMP
        doc_ref.update(update_fields)
        return True
    except Exception as e:
        print(f"Warning: update_record_firestore failed: {e}")
        return False

def delete_record_firestore(uid, record_id):
    try:
        if firestore_db is None or not FIRESTORE_WRITE or not uid:
            return False
        # delete record scans that reference record_id
        scans_q = firestore_db.collection("users").document(uid).collection("record_scans").where("record_id", "==", record_id).stream()
        for s in scans_q:
            s.reference.delete()
        # delete record doc
        firestore_db.collection("users").document(uid).collection("records").document(record_id).delete()
        return True
    except Exception as e:
        print(f"Warning: delete_record_firestore failed: {e}")
        return False

# ---------------------------
# Old local behaviour that we keep:
# - Local QR image generation remains local (static/qr)
# - Uploaded files stored in uploads/ and removed after processing
# ---------------------------

# ---------------------------
# Routes (keeping original structure)
# ---------------------------

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/create")
def create():
    qr_path = session.pop("qr_path", None)
    json_path = session.pop("json_path", None)
    return render_template("create.html", qr_path=qr_path, json_path=json_path)

@app.route("/generate", methods=["POST"])
def generate():
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')

    # Determine firebase uid if authenticated
    uid = get_uid()

    if request.form.get("form_mode"):
        labels = request.form.getlist("label[]")
        values = request.form.getlist("value[]")
        structured_data = dict(zip(labels, values))

        json_data = json.dumps(structured_data, indent=2)
        json_filename = f"data_{timestamp}.json"
        json_dir = os.path.join(app.config['STATIC_QR_FOLDER'], "qr_json")
        os.makedirs(json_dir, exist_ok=True)
        json_path = os.path.join(json_dir, json_filename)
        with open(json_path, "w") as f:
            f.write(json_data)

        qr_filename = f"qr_{timestamp}.png"
        qr_path = os.path.join(app.config['STATIC_QR_FOLDER'], qr_filename)
        img = qrcode.make(json_data)
        img.save(qr_path)

        # Write QR generation metadata to Firestore
        try:
            if firestore_db is not None and FIRESTORE_WRITE and uid:
                firestore_db.collection("users").document(uid).collection("qr_generations").add({
                    "user_id": uid,
                    "data_type": "structured",
                    "qr_data": json_data,
                    "qr_filename": qr_filename,
                    "json_filename": json_filename,
                    "generated_at": firestore.SERVER_TIMESTAMP
                })
        except Exception as e:
            print(f"Warning: could not write qr_generation to Firestore: {e}")

        session["qr_path"] = qr_filename
        session["json_path"] = f"qr_json/{json_filename}"
        session["qr_data"] = json_data
        session["json_preview"] = json.dumps(structured_data, indent=2)
        return redirect(url_for("create"))

    data = request.form.get("data")
    if not data:
        return redirect(url_for("create"))

    qr_filename = f"qr_{timestamp}.png"
    qr_path = os.path.join(app.config['STATIC_QR_FOLDER'], qr_filename)
    img = qrcode.make(data)
    img.save(qr_path)

    # Write QR generation metadata to Firestore
    try:
        if firestore_db is not None and FIRESTORE_WRITE and uid:
            firestore_db.collection("users").document(uid).collection("qr_generations").add({
                "user_id": uid,
                "data_type": "text",
                "qr_data": data,
                "qr_filename": qr_filename,
                "json_filename": None,
                "generated_at": firestore.SERVER_TIMESTAMP
            })
    except Exception as e:
        print(f"Warning: could not write qr_generation to Firestore: {e}")

    session["qr_path"] = qr_filename
    session["qr_data"] = data
    session.pop("json_path", None)
    session.pop("json_preview", None)
    return redirect(url_for("create"))

@app.route("/scan")
def scan():
    return render_template("scan.html")

@app.route("/webcam")
def webcam():
    return render_template("webcam.html")

# ---------------------------
# Upload handling (file upload + camera capture)
# ---------------------------
@app.route("/upload", methods=["POST"])
def upload():
    files = request.files.getlist("image")
    if not files or files[0].filename == "":
        return "No file(s) uploaded", 400

    new_scans = []
    uid = get_uid()

    for file in files:
        if file.filename == "":
            continue

        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)

        file_size = os.path.getsize(filepath) if os.path.exists(filepath) else 0
        codes_found = 0
        success = False
        error_message = None

        try:
            image = cv2.imread(filepath)
            if image is None:
                error_message = "Could not process image file"
                continue

            decoded = decode(image)
            codes_found = len(decoded)

            for obj in decoded:
                code_data = obj.data.decode("utf-8")
                code_type = str(obj.type)
                # Add to Firestore scans (avoid duplicates by checking latest few)
                is_new = True
                if uid and firestore_db is not None and FIRESTORE_READ:
                    # simple duplicate check: see if same data exists in last 100 scans
                    try:
                        recent = firestore_db.collection("users").document(uid).collection("scans").where("data", "==", code_data).limit(1).stream()
                        if any(recent):
                            is_new = False
                    except Exception:
                        is_new = True

                if is_new:
                    add_scan_to_firestore(uid if uid else "anonymous", code_data, code_type)
                    new_scans.append({"type": code_type, "data": code_data})

            success = codes_found > 0

        except Exception as e:
            error_message = str(e)
            print(f"Error processing image {filename}: {e}")
        finally:
            # Track upload attempt in Firestore meta collection (best-effort)
            try:
                attempt_doc = {
                    "upload_type": "file_upload",
                    "filename": filename,
                    "file_size": file_size,
                    "success": success,
                    "codes_found": codes_found,
                    "error_message": error_message,
                    "uploaded_at": firestore.SERVER_TIMESTAMP
                }
                if uid and firestore_db is not None and FIRESTORE_WRITE:
                    firestore_db.collection("users").document(uid).collection("upload_attempts").add(attempt_doc)
            except Exception as e:
                print(f"Warning: could not save upload attempt to Firestore: {e}")

            # Clean up uploaded file
            if os.path.exists(filepath):
                os.remove(filepath)

    return render_template("upload_result.html", results=new_scans, counts=get_scan_counts(get_uid()))

@app.route("/save-scan", methods=["POST"])
def save_scan():
    data = request.get_json()
    format = str(data.get("format"))
    text = data.get("text")

    if not format or not text:
        return jsonify({"error": "Missing data"}), 400

    uid = get_uid()
    if uid:
        add_scan_to_firestore(uid, text, format)
    else:
        # Optionally store anonymous scans under a 'public' uid or ignore
        add_scan_to_firestore("anonymous", text, format)

    return jsonify({
        "status": "saved",
        "counts": get_scan_counts(get_uid())
    })

@app.route("/scans")
def scans():
    try:
        uid = get_uid()
        if FIRESTORE_READ and firestore_db is not None and uid:
            docs = firestore_db.collection("users").document(uid).collection("scans").order_by("timestamp", direction=firestore.Query.DESCENDING).stream()
            scan_list = []
            for d in docs:
                dd = d.to_dict()
                # normalized timestamp
                t = dd.get("timestamp")
                if hasattr(t, "isoformat"):
                    dd["timestamp"] = t.isoformat()
                scan_list.append(dd)
            return jsonify(scan_list)
    except Exception as e:
        print(f"Warning: could not read scans from Firestore: {e}")

    # fallback: return empty or previous local caching behavior (none)
    return jsonify([])

@app.route("/camera")
def camera():
    return render_template("camera.html")

@app.route("/capture-upload", methods=["POST"])
def capture_upload():
    file = request.files.get("image")
    if not file:
        return render_template("upload_result.html", results=[], counts={}, error="No image uploaded.")

    filename = secure_filename(f"capture_{datetime.now().strftime('%Y%m%d%H%M%S')}.png")
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)

    uid = get_uid()
    file_size = os.path.getsize(filepath) if os.path.exists(filepath) else 0
    codes_found = 0
    success = False
    error_message = None
    new_scans = []

    try:
        image = cv2.imread(filepath)
        if image is None:
            error_message = "Snapshot could not be processed"
            return render_template("upload_result.html", results=[], counts={},
                                   error="❌ Snapshot could not be processed.")

        decoded = decode(image)
        codes_found = len(decoded)

        for obj in decoded:
            code_data = obj.data.decode("utf-8")
            code_type = str(obj.type)
            # duplicate check
            is_new = True
            if uid and firestore_db is not None and FIRESTORE_READ:
                try:
                    recent = firestore_db.collection("users").document(uid).collection("scans").where("data", "==", code_data).limit(1).stream()
                    if any(recent):
                        is_new = False
                except Exception:
                    is_new = True

            if is_new:
                add_scan_to_firestore(uid if uid else "anonymous", code_data, code_type)
                new_scans.append({"type": code_type, "data": code_data})

        success = codes_found > 0

        return render_template(
            "upload_result.html",
            results=new_scans,
            counts=get_scan_counts(uid),
            image_path=url_for('static', filename=f'uploads/{filename}')
        )

    except Exception as e:
        error_message = str(e)
        return render_template("upload_result.html", results=[], counts={}, error=f"❌ Error processing image: {str(e)}")
    finally:
        # Track upload attempt in Firestore
        try:
            attempt_doc = {
                "upload_type": "camera_capture",
                "filename": filename,
                "file_size": file_size,
                "success": success,
                "codes_found": codes_found,
                "error_message": error_message,
                "uploaded_at": firestore.SERVER_TIMESTAMP
            }
            if uid and firestore_db is not None and FIRESTORE_WRITE:
                firestore_db.collection("users").document(uid).collection("upload_attempts").add(attempt_doc)
        except Exception as e:
            print(f"Warning: could not save capture attempt to Firestore: {e}")

        # Clean up uploaded file
        if os.path.exists(filepath):
            os.remove(filepath)

# ---------------------------
# History & exports
# ---------------------------
@app.route("/history")
@login_required
def history():
    try:
        uid = get_uid()
        if FIRESTORE_READ and firestore_db is not None and uid:
            docs = firestore_db.collection("users").document(uid).collection("scans").order_by("timestamp", direction=firestore.Query.DESCENDING).stream()
            scan_list = []
            types = set()
            for d in docs:
                doc = d.to_dict()
                types.add(doc.get("type"))
                # normalize timestamp
                t = doc.get("timestamp")
                doc["timestamp"] = t.isoformat() if hasattr(t, "isoformat") else t
                scan_list.append(doc)
            return render_template("history.html", scans=scan_list, types=sorted(types))
    except Exception as e:
        print(f"Warning: could not read scans from Firestore: {e}")

    # fallback empty
    return render_template("history.html", scans=[], types=[])

@app.route("/export/json")
def export_json():
    try:
        uid = get_uid()
        if FIRESTORE_READ and firestore_db is not None and uid:
            docs = firestore_db.collection("users").document(uid).collection("scans").stream()
            scans = [d.to_dict() for d in docs]
            data = {"scans": scans, "counts": get_scan_counts(uid)}
            return jsonify(data)
    except Exception as e:
        print(f"Warning: could not export scans from Firestore: {e}")

    return jsonify({"scans": [], "counts": {}})

@app.route("/download/csv")
def download_csv():
    try:
        uid = get_uid()
        if FIRESTORE_READ and firestore_db is not None and uid:
            docs = firestore_db.collection("users").document(uid).collection("scans").order_by("timestamp", direction=firestore.Query.DESCENDING).stream()
            scans = [d.to_dict() for d in docs]
        else:
            scans = []
    except Exception as e:
        print(f"Warning: could not read scans for CSV from Firestore: {e}")
        scans = []

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Type", "Data", "Scanned At", "User ID"])

    for scan in scans:
        scanned_at = scan.get("timestamp")
        if hasattr(scanned_at, "isoformat"):
            scanned_at = scanned_at.isoformat()
        writer.writerow([scan.get("type"), scan.get("data"), scanned_at or "", scan.get("firebase_uid") or ""])

    output.seek(0)
    return send_file(
        BytesIO(output.getvalue().encode('utf-8')),
        mimetype='text/csv',
        as_attachment=True,
        download_name='scan_history.csv'
    )

@app.route("/download/json")
def download_json():
    try:
        uid = get_uid()
        if FIRESTORE_READ and firestore_db is not None and uid:
            docs = firestore_db.collection("users").document(uid).collection("scans").stream()
            scans = [d.to_dict() for d in docs]
            data = {"scans": scans, "counts": get_scan_counts(uid)}
            return send_file(
                BytesIO(json.dumps(data, indent=4).encode('utf-8')),
                mimetype='application/json',
                as_attachment=True,
                download_name='scan_history.json'
            )
    except Exception as e:
        print(f"Warning: could not create JSON from Firestore: {e}")

    return send_file(
        BytesIO(json.dumps({"scans": [], "counts": {}}, indent=4).encode('utf-8')),
        mimetype='application/json',
        as_attachment=True,
        download_name='scan_history.json'
    )

@app.errorhandler(RequestEntityTooLarge)
def handle_large_file(e):
    return render_template("upload_result.html", results=[], counts={}, error="❌ Image too large. Please upload a file under 10MB."), 413

# ---------------------------
# Authentication routes: signup, login, logout
# ---------------------------
@app.route("/signup", methods=["GET", "POST"])
def signup():
    # Create a user with Firebase Auth (Admin SDK) and create profile doc in Firestore
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "").strip()

        if not username or not email or not password:
            return render_template("signup.html", error="All fields required.")

        # Check if username already exists (usernames collection)
        try:
            if firestore_db is not None and FIRESTORE_READ:
                existing = firestore_db.collection("usernames").document(username.lower()).get()
                if existing.exists:
                    return render_template("signup.html", error="Username already exists.")
        except Exception as e:
            print(f"Warning: username uniqueness check failed: {e}")

        try:
            # Create Firebase Auth user using Admin SDK
            firebase_user = auth.create_user(email=email, password=password, display_name=username)
            uid = firebase_user.uid
            # Create profile in Firestore
            created = create_user_profile(uid, username, email)
            # Set session
            session["authenticated"] = True
            session["firebase_uid"] = uid
            session["username"] = username
            session["email"] = email
            flash("✅ Signup successful! You are now logged in.")
            return redirect(url_for("record_builder"))
        except Exception as e:
            print(f"Error creating user in Firebase Auth: {e}")
            # Try to surface a friendly message
            return render_template("signup.html", error=f"Could not create account: {str(e)}")

    return render_template("signup.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    # Use Firebase Auth REST API to sign in with email & password and obtain localId (uid)
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        if not username or not password:
            return render_template("login.html", error="Username and password required.")

        # First, look up email by username using user mapping
        profile = get_profile_by_username(username)
        if not profile:
            return render_template("login.html", error="Invalid username or password.")

        email = profile.get("email")
        if not email:
            return render_template("login.html", error="Invalid username or password.")

        try:
            url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={API_KEY}"
            payload = {"email": email, "password": password, "returnSecureToken": True}
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                uid = data.get("localId")
                id_token = data.get("idToken")
                session["authenticated"] = True
                session["firebase_uid"] = uid
                session["username"] = username
                session["email"] = email
                # (Optional) store idToken short-lived if needed: session["idToken"] = id_token
                flash("✅ Login successful!")
                return redirect(url_for("history"))
            else:
                err = resp.json().get("error", {}).get("message", "Login failed.")
                return render_template("login.html", error=f"❌ {err}")
        except Exception as e:
            print(f"Warning: Firebase login request failed: {e}")
            return render_template("login.html", error="❌ Login failed; try again later.")

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))

# ---------------------------
# Clear history (delete user's scans)
# ---------------------------
@app.route("/clear-history", methods=["POST"])
@login_required
def clear_history():
    uid = get_uid()
    if not uid:
        return redirect(url_for("login"))

    try:
        # Delete all scans subcollection docs
        scans_col = firestore_db.collection("users").document(uid).collection("scans")
        # batch delete
        docs = scans_col.stream()
        batch = firestore_db.batch()
        count = 0
        for d in docs:
            batch.delete(d.reference)
            count += 1
            if count == 500:
                batch.commit()
                batch = firestore_db.batch()
                count = 0
        if count > 0:
            batch.commit()
        # Reset counts doc
        firestore_db.collection("users").document(uid).collection("meta").document("counts").set({}, merge=True)
        flash("✅ Scan history cleared successfully!")
    except Exception as e:
        print(f"Error clearing history in Firestore: {e}")
        flash("❌ Error clearing history.")
    return redirect(url_for("history"))

# ---------------------------
# Record builder / record scans
# ---------------------------
@app.route("/record-builder")
@login_required
def record_builder():
    return render_template("record-builder.html")

@app.route("/save-record-scan", methods=["POST"])
@login_required
def save_record_scan():
    try:
        data = request.get_json(force=True)
        fmt = data.get("format")
        text = data.get("text")
        meta_info = data.get("meta_info", {})

        if not fmt or not text or not meta_info:
            return jsonify({"error": "Missing format, text, or meta_info"}), 400

        title = meta_info.get("title", "").strip()
        subtitle = meta_info.get("subtitle", "").strip()
        code = meta_info.get("code", "").strip()
        folder_id = meta_info.get("folder_id") or None

        if not title:
            return jsonify({"error": "Title is required in meta_info"}), 400

        uid = get_uid()
        if not uid:
            return jsonify({"error": "User not authenticated"}), 401

        user_doc = firestore_db.collection("users").document(uid)

        # ---- Look up or create record ----
        records_col = user_doc.collection("records")
        q = records_col.where("title", "==", title).limit(1).stream()
        rec_docs = list(q)

        if rec_docs:
            rec_doc = rec_docs[0]
            record_id = rec_doc.id
            record_data = rec_doc.to_dict()
        else:
            # Create new record
            record_doc = {
                "user_id": uid,
                "title": title,
                "subtitle": subtitle,
                "code": code,
                "folder_id": folder_id,
                "folder_name": None,
                "created_at": firestore.SERVER_TIMESTAMP,
                "updated_at": firestore.SERVER_TIMESTAMP
            }

            # Resolve folder name
            if folder_id:
                folder_ref = user_doc.collection("folders").document(folder_id)
                folder_doc = folder_ref.get()
                if folder_doc.exists:
                    record_doc["folder_name"] = folder_doc.to_dict().get("name")

            new_ref = records_col.add(record_doc)
            record_id = new_ref[1].id
            record_data = record_doc

        # ---- Prevent duplicate scans ----
        rec_scans_col = user_doc.collection("record_scans")
        duplicates = rec_scans_col.where("record_id", "==", record_id).where("data", "==", text).limit(1).stream()
        if any(duplicates):
            return jsonify({"new": False, "message": "Duplicate scan."})

        # ---- Save scan ----
        new_scan_doc = {
            "record_id": record_id,
            "data": text,
            "type": fmt,
            "scanned_at": firestore.SERVER_TIMESTAMP,
            "user_id": uid
        }
        rec_scans_col.add(new_scan_doc)

        # ---- Update record metadata ----
        records_col.document(record_id).update({
            "updated_at": firestore.SERVER_TIMESTAMP,
            "subtitle": subtitle or record_data.get("subtitle", ""),
            "folder_id": folder_id or record_data.get("folder_id"),
            "folder_name": record_data.get("folder_name") or None
        })

        # ---- Increment scan statistics ----
        increment_scan_count(uid, fmt)

        return jsonify({"new": True, "message": "Scan saved."})

    except Exception as e:
        print("❌ Error saving record scan:", e)
        return jsonify({"error": f"Exception: {str(e)}"}), 500


@app.route("/record-camera")
@login_required
def record_camera():
    return render_template("record-camera.html")

@app.route("/preview-record")
@login_required
def preview_record():
    title = request.args.get("title", "").strip()
    if not title:
        return jsonify({"error": "Title is required"}), 400

    uid = get_uid()
    if not uid:
        return jsonify({"error": "User not authenticated"}), 401

    try:
        # Find record by title
        docs = firestore_db.collection("users").document(uid).collection("records").where("title", "==", title).stream()
        rec_docs = list(docs)
        if not rec_docs:
            return jsonify({"record": {}})
        rec = rec_docs[0].to_dict()
        rec_id = rec_docs[0].id

        scans_docs = firestore_db.collection("users").document(uid).collection("record_scans").where("record_id", "==", rec_id).stream()
        record_data = {}
        label_keys = ["name", "full_name", "title", "username"]
        for sd in scans_docs:
            s_dict = sd.to_dict()
            raw_data = s_dict.get("data", "")
            cleaned_data = raw_data
            label = "unknown"
            try:
                parsed = json.loads(raw_data)
                if isinstance(parsed, dict):
                    cleaned_data = json.dumps(parsed, separators=(",", ":"))
                    for key_option in label_keys:
                        if key_option in parsed and parsed[key_option].strip():
                            label = parsed[key_option].strip().lower()
                            break
            except:
                if raw_data.strip().lower().startswith("http"):
                    label = "link"
            key = f"{s_dict.get('type')}:{label}"
            record_data[key] = {
                "data": cleaned_data,
                "id": sd.id,
                "scanned_at": s_dict.get("scanned_at"),
                "type": s_dict.get("type")
            }
        return jsonify(record_data)
    except Exception as e:
        print(f"Warning: preview_record failed: {e}")
        return jsonify({"record": {}})

# ---------------------------
# Utilities: time_ago, dashboard, record-dash operations
# ---------------------------
def time_ago(from_time):
    now = datetime.now()
    if isinstance(from_time, datetime):
        delta = now - from_time
    else:
        return ""
    seconds = int(delta.total_seconds())
    minutes = seconds // 60
    hours = minutes // 60
    days = delta.days
    if seconds < 60:
        return f"{seconds} second{'s' if seconds != 1 else ''} ago"
    elif minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    elif hours < 24:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    elif days < 30:
        return f"{days} day{'s' if days != 1 else ''} ago"
    elif days < 365:
        months = days // 30
        return f"{months} month{'s' if months != 1 else ''} ago"
    else:
        years = days // 365
        return f"{years} year{'s' if years != 1 else ''} ago"

@app.route("/record-dashboard")
@login_required
def record_dashboard():
    uid = get_uid()
    if not uid:
        return redirect(url_for("login"))

    record_list = []
    folder_list = []
    try:
        if FIRESTORE_READ and firestore_db is not None and uid:
            # Fetch records
            records = firestore_db.collection("users").document(uid).collection("records").stream()
            for r in records:
                rd = r.to_dict()
                record_list.append({
                    "title": rd.get("title"),
                    "subtitle": rd.get("subtitle"),
                    "count": rd.get("count", 0),  # optional stored count
                    "folder": rd.get("folder", "Uncategorized"),
                    "folder_id": rd.get("folder_id"),
                    "last_modified": rd.get("updated_at"),
                    "modified": rd.get("updated_at")
                })
            # Fetch folders
            folders = firestore_db.collection("users").document(uid).collection("folders").stream()
            for f in folders:
                folder_list.append(f.to_dict())
            return render_template("record-dashboard.html", records=record_list, folders=folder_list)
    except Exception as e:
        print(f"Warning: could not read records from Firestore: {e}")

    # fallback empty
    return render_template("record-dashboard.html", records=record_list, folders=folder_list)

@app.route("/delete-record", methods=["POST"])
@login_required
def delete_record():
    title = request.form.get("title")
    uid = get_uid()
    if not uid:
        return redirect(url_for("login"))

    try:
        # Find record by title
        docs = firestore_db.collection("users").document(uid).collection("records").where("title", "==", title).stream()
        recs = list(docs)
        if recs:
            rec_id = recs[0].id
            # delete record doc and its record_scans
            delete_record_firestore(uid, rec_id)
            flash(f"✅ Record '{title}' deleted successfully!")
    except Exception as e:
        print(f"Warning: could not delete record: {e}")
    return redirect(url_for("record_dashboard"))

@app.route("/update-subtitle", methods=["POST"])
@login_required
def update_subtitle():
    try:
        uid = get_uid()
        if not uid:
            return jsonify({"success": False, "error": "User not authenticated"}), 401

        # Detect whether request came from fetch (JSON) or form
        if request.is_json:
            data = request.get_json(force=True)
            title = data.get("title", "").strip()
            new_subtitle = data.get("subtitle", "").strip()
        else:
            title = request.form.get("title", "").strip()
            new_subtitle = request.form.get("subtitle", "").strip()

        if not title:
            return jsonify({"success": False, "error": "Missing title"}), 400

        # Find the record by title
        records_ref = firestore_db.collection("users").document(uid).collection("records")
        docs = records_ref.where("title", "==", title).limit(1).stream()
        docs_l = list(docs)

        if not docs_l:
            return jsonify({"success": False, "error": f"Record '{title}' not found"}), 404

        rec_id = docs_l[0].id
        records_ref.document(rec_id).update({
            "subtitle": new_subtitle,
            "updated_at": firestore.SERVER_TIMESTAMP
        })

        print(f"✅ Subtitle updated for '{title}' → '{new_subtitle}'")

        # Handle both frontend fetch and legacy redirect
        if request.is_json:
            return jsonify({
                "success": True,
                "message": f"Subtitle updated for '{title}'",
                "subtitle": new_subtitle
            })
        else:
            flash(f"✅ Subtitle updated for '{title}'!")
            return redirect(url_for("record_dashboard"))

    except Exception as e:
        print(f"⚠️ Error updating subtitle: {e}")
        if request.is_json:
            return jsonify({"success": False, "error": str(e)}), 500
        flash("⚠️ Could not update subtitle.")
        return redirect(url_for("record_dashboard"))


@app.route("/download-record")
@login_required
def download_record():
    title = request.args.get("title", "").strip()
    format = request.args.get("format", "csv").lower()
    uid = get_uid()
    if not title or not uid:
        return "Missing title", 400

    try:
        rec_docs = firestore_db.collection("users").document(uid).collection("records").where("title", "==", title).stream()
        rec_list = list(rec_docs)
        if not rec_list:
            return f"Record '{title}' not found", 404
        rec_doc = rec_list[0]
        rec = rec_doc.to_dict()
        rec_id = rec_doc.id
        scans_docs = firestore_db.collection("users").document(uid).collection("record_scans").where("record_id", "==", rec_id).order_by("scanned_at", direction=firestore.Query.DESCENDING).stream()
        scans = [d.to_dict() for d in scans_docs]
    except Exception as e:
        print(f"Warning: could not read record from Firestore: {e}")
        scans = []

    # build rows dedup logic similar to old code
    seen = set()
    rows = []
    all_keys = set(["id", "scanned at"])

    for scan in scans:
        row = {}
        raw = scan.get("data")
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(parsed, dict):
                row = {k.strip().lower(): str(v).strip().lower() for k, v in parsed.items()}
            else:
                row = {"data": str(raw).strip().lower()}
        except Exception:
            row = {"data": str(raw).strip().lower()}

        identity_key = tuple(sorted(row.items()))
        if identity_key in seen:
            continue
        seen.add(identity_key)

        row["id"] = scan.get("id", "")
        scanned_at = scan.get("scanned_at")
        if hasattr(scanned_at, "isoformat"):
            row["scanned at"] = scanned_at.isoformat()
        else:
            row["scanned_at"] = scanned_at
        all_keys.update(row.keys())
        rows.append(row)

    sorted_keys = sorted(all_keys)

    if format == "csv":
        output = StringIO()
        writer = csv.DictWriter(output, fieldnames=sorted_keys)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in sorted_keys})
        output.seek(0)
        return send_file(
            BytesIO(output.getvalue().encode("utf-8")),
            mimetype="text/csv",
            as_attachment=True,
            download_name=f"{secure_filename(title)}.csv"
        )
    elif format == "excel":
        df = pd.DataFrame([{k: row.get(k, "") for k in sorted_keys} for row in rows])
        output = BytesIO()
        with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
            df.to_excel(writer, index=False, sheet_name="Record")
        output.seek(0)
        return send_file(
            output,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name=f"{secure_filename(title)}.xlsx"
        )
    return "Unsupported format", 400

# ---------------------------
# Folders: create, rename, delete, move records
# ---------------------------
@app.route("/create-folder", methods=["POST"])
@login_required
def create_folder():
    try:
        data = request.get_json()
        name = data.get("name", "").strip()
        parent_id = data.get("parent_id")
        uid = get_uid()
        if not name:
            return jsonify({"error": "Folder name is required"}), 400

        # Check exists
        q = firestore_db.collection("users").document(uid).collection("folders").where("name", "==", name).limit(1).stream()
        if any(q):
            return jsonify({"error": "Folder already exists"}), 400

        new_folder = {
            "user_id": uid,
            "name": name,
            "parent_id": parent_id,
            "created_at": firestore.SERVER_TIMESTAMP
        }
        ref = firestore_db.collection("users").document(uid).collection("folders").add(new_folder)
        new_doc = new_folder.copy()
        new_doc["id"] = ref[1].id
        return jsonify({"success": True, "folder": new_doc})
    except Exception as e:
        print(f"Error creating folder: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/rename-record", methods=["POST"])
@login_required
def rename_record():
    try:
        uid = get_uid()
        if not uid:
            return jsonify({"success": False, "error": "User not authenticated"}), 401

        # Support both JSON (fetch) and form submissions
        if request.is_json:
            data = request.get_json(force=True)
            old_title = data.get("old_title", "").strip()
            new_title = data.get("new_title", "").strip()
        else:
            old_title = request.form.get("old_title", "").strip()
            new_title = request.form.get("new_title", "").strip()

        if not old_title or not new_title:
            return jsonify({"success": False, "error": "Both old_title and new_title are required"}), 400

        # Prevent renaming to an existing title (duplicate)
        records_ref = firestore_db.collection("users").document(uid).collection("records")
        existing = list(records_ref.where("title", "==", new_title).limit(1).stream())
        if existing:
            return jsonify({
                "success": False,
                "error": f"A record with the title '{new_title}' already exists."
            }), 409  # Conflict

        # Find the record to rename
        docs = list(records_ref.where("title", "==", old_title).limit(1).stream())
        if not docs:
            return jsonify({"success": False, "error": f"Record '{old_title}' not found"}), 404

        rec_id = docs[0].id

        # Update record title
        records_ref.document(rec_id).update({
            "title": new_title,
            "updated_at": firestore.SERVER_TIMESTAMP
        })

        print(f"✅ Record renamed from '{old_title}' → '{new_title}' (uid: {uid})")

        # JSON or form response
        if request.is_json:
            return jsonify({
                "success": True,
                "message": f"Record renamed to '{new_title}'",
                "new_title": new_title
            })
        else:
            flash(f"✅ Record renamed to '{new_title}'")
            return redirect(url_for("record_dashboard"))

    except Exception as e:
        print("⚠️ Error renaming record:", e)
        if request.is_json:
            return jsonify({"success": False, "error": str(e)}), 500
        flash("⚠️ Could not rename record.")
        return redirect(url_for("record_dashboard"))


@app.route("/rename-folder", methods=["POST"])
@login_required
def rename_folder():
    try:
        data = request.get_json()
        folder_id = data.get("id")
        new_name = data.get("name", "").strip()
        uid = get_uid()
        if not new_name:
            return jsonify({"error": "Folder name is required"}), 400

        folder_ref = firestore_db.collection("users").document(uid).collection("folders").document(folder_id)
        folder_doc = folder_ref.get()
        if not folder_doc.exists:
            return jsonify({"error": "Folder not found"}), 404

        # check conflict
        conflict = firestore_db.collection("users").document(uid).collection("folders").where("name", "==", new_name).limit(1).stream()
        if any(conflict):
            return jsonify({"error": "Folder name already exists"}), 400

        folder_ref.update({"name": new_name})
        return jsonify({"success": True, "folder": {"id": folder_id, "name": new_name}})
    except Exception as e:
        print(f"Error renaming folder: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/delete-folder", methods=["POST"])
@login_required
def delete_folder():
    try:
        data = request.get_json()
        folder_id = data.get("id")
        uid = get_uid()

        folder_ref = firestore_db.collection("users").document(uid).collection("folders").document(folder_id)
        folder_doc = folder_ref.get()
        if not folder_doc.exists:
            return jsonify({"error": "Folder not found"}), 404

        # Move records in this folder to uncategorized
        records_q = firestore_db.collection("users").document(uid).collection("records").where("folder_id", "==", folder_id).stream()
        batch = firestore_db.batch()
        for r in records_q:
            doc_ref = firestore_db.collection("users").document(uid).collection("records").document(r.id)
            batch.update(doc_ref, {"folder_id": None})
        batch.commit()

        # Delete folder (and optionally subfolders recursively - omitted for brevity)
        folder_ref.delete()
        return jsonify({"success": True})
    except Exception as e:
        print(f"Error deleting folder: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/move-record-to-folder", methods=["POST"])
@login_required
def move_record_to_folder():
    try:
        data = request.get_json()
        record_title = data.get("title")
        folder_id = data.get("folder_id")  # Can be None
        uid = get_uid()

        rec_docs = firestore_db.collection("users").document(uid).collection("records").where("title", "==", record_title).limit(1).stream()
        recs = list(rec_docs)
        if not recs:
            return jsonify({"success": False, "error": "Record not found"}), 404
        rec_id = recs[0].id
        update_record_firestore(uid, rec_id, {"folder_id": folder_id})
        return jsonify({"success": True})
    except Exception as e:
        print(f"Error moving record to folder: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

# ---------------------------
# Dashboard API (folders & records)
# ---------------------------
@app.route("/api/dashboard-data")
@login_required
def api_dashboard_data():
    try:
        uid = get_uid()
        if not uid:
            return jsonify({"success": False, "error": "No UID found"}), 401

        # ---- Folders ----
        folders_col = firestore_db.collection("users").document(uid).collection("folders")
        folders_docs = list(folders_col.stream())

        # Create default folders only if missing
        existing_names = [f.to_dict().get("name", "").lower() for f in folders_docs]
        default_folders = [
            "All Records", "Uncategorized", "Work Projects",
            "Personal Records", "Archive", "Important Documents"
        ]

        batch = firestore_db.batch()
        for name in default_folders:
            if name.lower() not in existing_names:
                ref = folders_col.document()
                batch.set(ref, {
                    "user_id": uid,
                    "name": name,
                    "created_at": firestore.SERVER_TIMESTAMP
                })
        if batch:
            batch.commit()

        # Re-fetch all folders (ensures consistency)
        folders_docs = list(folders_col.stream())
        folder_list = [
            {"id": f.id, **f.to_dict()} for f in folders_docs
        ]

        # ---- Records ----
        records_col = firestore_db.collection("users").document(uid).collection("records")
        records_docs = records_col.order_by(
            "updated_at", direction=firestore.Query.DESCENDING
        ).stream()

        record_list = []
        for r in records_docs:
            rd = r.to_dict()
            rd["id"] = r.id
            rd["updated_at"] = rd.get("updated_at")

            # Count related scans (safe: one filter only)
            try:
                scans_ref = firestore_db.collection("users").document(uid).collection("record_scans")
                scans_query = scans_ref.where("record_id", "==", r.id).stream()
                rd["scan_count"] = sum(1 for _ in scans_query)
            except Exception as scan_err:
                print("⚠️ Scan count error:", scan_err)
                rd["scan_count"] = 0

            # Resolve folder name if missing
            if not rd.get("folder_name") and rd.get("folder_id"):
                folder_ref = firestore_db.collection("users").document(uid).collection("folders").document(rd["folder_id"])
                folder_doc = folder_ref.get()
                if folder_doc.exists:
                    rd["folder_name"] = folder_doc.to_dict().get("name", "Unknown")

            record_list.append(rd)

        return jsonify({
            "success": True,
            "folders": folder_list,
            "records": record_list
        })

    except Exception as e:
        print("❌ Dashboard data error:", e)
        return jsonify({"success": False, "error": str(e)}), 500

# ---------------------------
# API endpoints for folder operations (mirrors earlier endpoints)
# ---------------------------

@app.route("/api/create-folder", methods=["POST"])
@login_required
def api_create_folder():
    try:
        data = request.get_json()
        name = data.get("name", "").strip()
        parent_id = data.get("parent_id")
        uid = get_uid()
        if not name:
            return jsonify({"success": False, "error": "Folder name is required"}), 400

        existing = firestore_db.collection("users").document(uid).collection("folders").where("name", "==", name).limit(1).stream()
        if any(existing):
            return jsonify({"success": False, "error": "Folder already exists"}), 400

        ref = firestore_db.collection("users").document(uid).collection("folders").add({
            "user_id": uid,
            "name": name,
            "parent_id": parent_id,
            "created_at": firestore.SERVER_TIMESTAMP
        })
        doc = {"id": ref[1].id, "name": name, "parent_id": parent_id}
        return jsonify({"success": True, "folder": doc})
    except Exception as e:
        print(f"Error api_create_folder: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/rename-folder", methods=["POST"])
@login_required
def api_rename_folder():
    try:
        data = request.get_json()
        folder_id = data.get("id")
        new_name = data.get("name", "").strip()
        uid = get_uid()
        if not new_name:
            return jsonify({"success": False, "error": "Folder name is required"}), 400
        folder_ref = firestore_db.collection("users").document(uid).collection("folders").document(folder_id)
        folder_doc = folder_ref.get()
        if not folder_doc.exists:
            return jsonify({"success": False, "error": "Folder not found"}), 404
        # conflict check
        conflict = firestore_db.collection("users").document(uid).collection("folders").where("name", "==", new_name).limit(1).stream()
        if any(conflict):
            return jsonify({"success": False, "error": "Folder name already exists"}), 400
        folder_ref.update({"name": new_name})
        # Update all records that reference this folder_id to reflect the new name
        records_q = firestore_db.collection("users").document(uid).collection("records").where("folder_id", "==", folder_id).stream()
        batch = firestore_db.batch()
        for r in records_q:
            rec_ref = firestore_db.collection("users").document(uid).collection("records").document(r.id)
            batch.update(rec_ref, {"folder_name": new_name})
        batch.commit()

        return jsonify({"success": True, "folder": {"id": folder_id, "name": new_name}})
    except Exception as e:
        print(f"Error api_rename_folder: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/delete-folder", methods=["POST"])
@login_required
def api_delete_folder():
    try:
        data = request.get_json()
        folder_id = data.get("id")
        uid = get_uid()
        folder_ref = firestore_db.collection("users").document(uid).collection("folders").document(folder_id)
        folder_doc = folder_ref.get()
        if not folder_doc.exists:
            return jsonify({"success": False, "error": "Folder not found"}), 404

        # move records out of folder
        records_q = firestore_db.collection("users").document(uid).collection("records").where("folder_id", "==", folder_id).stream()
        batch = firestore_db.batch()
        for r in records_q:
            doc_ref = firestore_db.collection("users").document(uid).collection("records").document(r.id)
            batch.update(doc_ref, {"folder_id": None})
        batch.commit()

        # delete subfolders recursively is omitted for simplicity
        folder_ref.delete()
        return jsonify({"success": True})
    except Exception as e:
        print(f"Error api_delete_folder: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/move-record-to-folder", methods=["POST"])
@login_required
def api_move_record_to_folder():
    try:
        data = request.get_json()
        record_title = data.get("title")
        folder_id = data.get("folder_id")
        uid = get_uid()
        rec_docs = firestore_db.collection("users").document(uid).collection("records").where("title", "==", record_title).limit(1).stream()
        recs = list(rec_docs)
        if not recs:
            return jsonify({"success": False, "error": "Record not found"}), 404
        rec_id = recs[0].id
        update_record_firestore(uid, rec_id, {"folder_id": folder_id})
        return jsonify({"success": True})
    except Exception as e:
        print(f"Error api_move_record_to_folder: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

# ---------------------------
# Run
# ---------------------------
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    # debug=True for local development only
    app.run(host='0.0.0.0', port=port, debug=True)
