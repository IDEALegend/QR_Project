from flask import Flask, render_template, request, redirect, url_for, jsonify, session, flash
import json
import os
from datetime import datetime
from pyzbar.pyzbar import decode
import cv2
from werkzeug.utils import secure_filename
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import qrcode
from flask import send_file
import csv
from io import StringIO, BytesIO
from werkzeug.exceptions import RequestEntityTooLarge
from functools import wraps
import pandas as pd
from xlsxwriter import Workbook
from sqlalchemy import and_, desc

import os


app = Flask(__name__)

app.secret_key = os.getenv("SECRET_KEY", "fallback-secret-key")
# Database setup
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///site.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Set max content length to 10MB
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10MB
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['STATIC_QR_FOLDER'] = os.path.join('static', 'qr')

# Basic password for protected routes
PROTECTED_PASSWORD = os.getenv("ADMIN_PASSWORD", "fallback-admin")



# Database Models
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)

    # Relationships
    scans = db.relationship('Scan', backref='scan_user', lazy=True)
    records = db.relationship('Record', backref='record_user', lazy=True)


class Scan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    data = db.Column(db.Text, nullable=False)
    type = db.Column(db.String(50), nullable=False)
    scanned_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "data": self.data,
            "type": self.type,
            "scanned_at": self.scanned_at.strftime("%Y-%m-%d %H:%M:%S"),
            "user_id": self.user_id
        }


class Record(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    folder_id = db.Column(db.Integer, db.ForeignKey('folder.id'), nullable=True)
    title = db.Column(db.String(200), nullable=False)
    subtitle = db.Column(db.String(500), nullable=True)
    code = db.Column(db.String(100), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    record_scans = db.relationship('RecordScan', backref='parent_record', lazy=True, cascade='all, delete-orphan')

    def get_scan_count(self):
        return len(self.record_scans)

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "subtitle": self.subtitle,
            "code": self.code,
            "count": self.get_scan_count(),
            "folder": self.folder.name if self.folder else "Uncategorized",
            "folder_id": self.folder_id,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            "updated_at": self.updated_at.strftime("%Y-%m-%d %H:%M:%S")
        }


class RecordScan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    record_id = db.Column(db.Integer, db.ForeignKey('record.id'), nullable=False)
    data = db.Column(db.Text, nullable=False)
    type = db.Column(db.String(50), nullable=False)
    scanned_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "data": self.data,
            "type": self.type,
            "scanned_at": self.scanned_at.strftime("%Y-%m-%d %H:%M:%S")
        }


class ScanCount(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(50), unique=True, nullable=False)
    count = db.Column(db.Integer, default=0)

    @staticmethod
    def get_counts():
        counts = {}
        for scan_count in ScanCount.query.all():
            counts[scan_count.type] = scan_count.count
        return counts

    @staticmethod
    def increment_count(scan_type):
        scan_count = ScanCount.query.filter_by(type=scan_type).first()
        if scan_count:
            scan_count.count += 1
        else:
            scan_count = ScanCount(type=scan_type, count=1)
            db.session.add(scan_count)
        db.session.commit()

class Folder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey('folder.id'), nullable=True)  # NEW: For nested folders
    name = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    records = db.relationship('Record', backref='folder', lazy=True)
    children = db.relationship('Folder', backref=db.backref('parent', remote_side=[id]), lazy=True)  # NEW

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "parent_id": self.parent_id,  # NEW
            "record_count": len(self.records),
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S")
        }

class QRGeneration(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    data_type = db.Column(db.String(50), nullable=False)  # 'text' or 'structured'
    qr_data = db.Column(db.Text, nullable=False)
    qr_filename = db.Column(db.String(200), nullable=False)
    json_filename = db.Column(db.String(200), nullable=True)  # Only for structured data
    generated_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "data_type": self.data_type,
            "qr_data": self.qr_data,
            "qr_filename": self.qr_filename,
            "json_filename": self.json_filename,
            "generated_at": self.generated_at.strftime("%Y-%m-%d %H:%M:%S"),
            "user_id": self.user_id
        }

class UploadAttempt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    upload_type = db.Column(db.String(50), nullable=False)  # 'file_upload' or 'camera_capture'
    filename = db.Column(db.String(200), nullable=False)
    file_size = db.Column(db.Integer, nullable=True)
    success = db.Column(db.Boolean, default=False)
    codes_found = db.Column(db.Integer, default=0)
    error_message = db.Column(db.Text, nullable=True)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "upload_type": self.upload_type,
            "filename": self.filename,
            "file_size": self.file_size,
            "success": self.success,
            "codes_found": self.codes_found,
            "error_message": self.error_message,
            "uploaded_at": self.uploaded_at.strftime("%Y-%m-%d %H:%M:%S"),
            "user_id": self.user_id
        }
# Create directories
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])
if not os.path.exists(app.config['STATIC_QR_FOLDER']):
    os.makedirs(app.config['STATIC_QR_FOLDER'])


# Initialize database with migration handling
def init_database():
    """Initialize database and handle migrations"""
    try:
        # Try to create all tables
        db.create_all()

        # Check if parent_id column exists in Folder table
        try:
            # Try to query with parent_id - if it fails, column doesn't exist
            db.session.execute(db.text("SELECT parent_id FROM folder LIMIT 1"))
        except:
            # Add parent_id column
            db.session.execute(db.text("ALTER TABLE folder ADD COLUMN parent_id INTEGER"))
            db.session.commit()
            print("✅ Added parent_id column to folder table")

        # Check if QRGeneration table exists
        try:
            db.session.execute(db.text("SELECT * FROM qr_generation LIMIT 1"))
        except:
            # Create QRGeneration table manually if it doesn't exist
            db.session.execute(db.text("""
                CREATE TABLE qr_generation (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER,
                    data_type VARCHAR(50) NOT NULL,
                    qr_data TEXT NOT NULL,
                    qr_filename VARCHAR(200) NOT NULL,
                    json_filename VARCHAR(200),
                    generated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES user(id)
                )
            """))
            db.session.commit()
            print("✅ Created qr_generation table")

        # Check if UploadAttempt table exists
        try:
            db.session.execute(db.text("SELECT * FROM upload_attempt LIMIT 1"))
        except:
            # Create UploadAttempt table manually if it doesn't exist
            db.session.execute(db.text("""
                CREATE TABLE upload_attempt (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER,
                    upload_type VARCHAR(50) NOT NULL,
                    filename VARCHAR(200) NOT NULL,
                    file_size INTEGER,
                    success BOOLEAN DEFAULT 0,
                    codes_found INTEGER DEFAULT 0,
                    error_message TEXT,
                    uploaded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES user(id)
                )
            """))
            db.session.commit()
            print("✅ Created upload_attempt table")

        print("✅ Database initialized successfully")
        migrate_old_data()

    except Exception as e:
        print(f"Database initialization error: {e}")
        db.session.rollback()

def migrate_old_data():
    """Migrate data from old JSON files to database if they exist"""
    try:
        # Migrate from scanned_codes.json if it exists
        old_data_file = "scanned_codes.json"
        if os.path.exists(old_data_file):
            print("📦 Migrating old scan data...")
            with open(old_data_file, "r") as f:
                old_data = json.load(f)

            for key, entry in old_data.items():
                if key == "counts":
                    # Migrate counts
                    for scan_type, count in entry.items():
                        existing_count = ScanCount.query.filter_by(type=scan_type).first()
                        if not existing_count:
                            scan_count = ScanCount(type=scan_type, count=count)
                            db.session.add(scan_count)
                else:
                    # Migrate scan entries
                    if isinstance(entry, dict) and "data" in entry and "type" in entry:
                        existing_scan = Scan.query.filter_by(
                            data=entry["data"],
                            type=entry["type"]
                        ).first()
                        if not existing_scan:
                            scan_time = datetime.strptime(
                                entry.get("scanned_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                                "%Y-%m-%d %H:%M:%S"
                            )
                            new_scan = Scan(
                                data=entry["data"],
                                type=entry["type"],
                                scanned_at=scan_time
                            )
                            db.session.add(new_scan)

            db.session.commit()
            print("✅ Old scan data migrated successfully")

            # Backup old file
            backup_name = f"{old_data_file}.backup"
            os.rename(old_data_file, backup_name)
            print(f"📄 Old data backed up as {backup_name}")

    except Exception as e:
        print(f"Migration error: {e}")
        db.session.rollback()


with app.app_context():
    init_database()


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("authenticated"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)

    return decorated_function


# Helper function to get scan counts from database
def get_scan_counts():
    return ScanCount.get_counts()


# Helper function to save scan to database with duplicate checking
def save_scan_to_db(data, scan_type, user_id=None):
    try:
        # Check if scan already exists (simple check without unique constraint)
        existing_scan = Scan.query.filter_by(data=data, type=scan_type).first()
        if not existing_scan:
            new_scan = Scan(data=data, type=scan_type, user_id=user_id)
            db.session.add(new_scan)
            ScanCount.increment_count(scan_type)
            db.session.commit()
            return True, new_scan
        return False, existing_scan
    except Exception as e:
        db.session.rollback()
        print(f"Error saving scan: {e}")
        return False, None


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

    # Get current user
    user_id = None
    if session.get("authenticated"):
        user = User.query.filter_by(username=session.get("username")).first()
        user_id = user.id if user else None

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

        # Save to database
        try:
            qr_generation = QRGeneration(
                user_id=user_id,
                data_type='structured',
                qr_data=json_data,
                qr_filename=qr_filename,
                json_filename=json_filename
            )
            db.session.add(qr_generation)
            db.session.commit()
        except Exception as e:
            print(f"Error saving QR generation to database: {e}")
            db.session.rollback()

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

    # Save to database
    try:
        qr_generation = QRGeneration(
            user_id=user_id,
            data_type='text',
            qr_data=data,
            qr_filename=qr_filename,
            json_filename=None
        )
        db.session.add(qr_generation)
        db.session.commit()
    except Exception as e:
        print(f"Error saving QR generation to database: {e}")
        db.session.rollback()

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


@app.route("/upload", methods=["POST"])
def upload():
    files = request.files.getlist("image")
    if not files or files[0].filename == "":
        return "No file(s) uploaded", 400

    new_scans = []
    user_id = None
    if session.get("authenticated"):
        user = User.query.filter_by(username=session.get("username")).first()
        user_id = user.id if user else None

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

                is_new, scan = save_scan_to_db(code_data, code_type, user_id)
                if is_new:
                    new_scans.append({"type": code_type, "data": code_data})

            success = codes_found > 0

        except Exception as e:
            error_message = str(e)
            print(f"Error processing image {filename}: {e}")
        finally:
            # Track upload attempt in database
            try:
                upload_attempt = UploadAttempt(
                    user_id=user_id,
                    upload_type='file_upload',
                    filename=filename,
                    file_size=file_size,
                    success=success,
                    codes_found=codes_found,
                    error_message=error_message
                )
                db.session.add(upload_attempt)
                db.session.commit()
            except Exception as e:
                print(f"Error saving upload attempt: {e}")
                db.session.rollback()

            # Clean up uploaded file
            if os.path.exists(filepath):
                os.remove(filepath)

    return render_template("upload_result.html", results=new_scans, counts=get_scan_counts())


@app.route("/save-scan", methods=["POST"])
def save_scan():
    data = request.get_json()
    format = str(data.get("format"))
    text = data.get("text")

    if not format or not text:
        return jsonify({"error": "Missing data"}), 400

    user_id = None
    if session.get("authenticated"):
        user = User.query.filter_by(username=session.get("username")).first()
        user_id = user.id if user else None

    is_new, scan = save_scan_to_db(text, format, user_id)

    return jsonify({
        "status": "saved",
        "new": is_new,
        "counts": get_scan_counts()
    })


@app.route("/scans")
def scans():
    scans = Scan.query.order_by(desc(Scan.scanned_at)).all()
    scan_list = [s.to_dict() for s in scans]
    return jsonify(scan_list)


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

    user_id = None
    if session.get("authenticated"):
        user = User.query.filter_by(username=session.get("username")).first()
        user_id = user.id if user else None

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

            is_new, scan = save_scan_to_db(code_data, code_type, user_id)
            if is_new:
                new_scans.append({"type": code_type, "data": code_data})

        success = codes_found > 0

        return render_template(
            "upload_result.html",
            results=new_scans,
            counts=get_scan_counts(),
            image_path=url_for('static', filename=f'uploads/{filename}')
        )

    except Exception as e:
        error_message = str(e)
        return render_template("upload_result.html", results=[], counts={}, error=f"❌ Error processing image: {str(e)}")
    finally:
        # Track upload attempt in database
        try:
            upload_attempt = UploadAttempt(
                user_id=user_id,
                upload_type='camera_capture',
                filename=filename,
                file_size=file_size,
                success=success,
                codes_found=codes_found,
                error_message=error_message
            )
            db.session.add(upload_attempt)
            db.session.commit()
        except Exception as e:
            print(f"Error saving capture attempt: {e}")
            db.session.rollback()

        # Clean up uploaded file
        if os.path.exists(filepath):
            os.remove(filepath)

@app.route("/history")
@login_required
def history():
    scans = Scan.query.order_by(desc(Scan.scanned_at)).all()
    return render_template("history.html", scans=scans, types=sorted({s.type for s in scans}))


@app.route("/export/json")
def export_json():
    scans = Scan.query.all()
    data = {
        "scans": [scan.to_dict() for scan in scans],
        "counts": get_scan_counts()
    }
    return jsonify(data)


@app.route("/download/csv")
def download_csv():
    scans = Scan.query.order_by(desc(Scan.scanned_at)).all()
    output = StringIO()
    writer = csv.writer(output)

    writer.writerow(["Type", "Data", "Scanned At", "User ID"])

    for scan in scans:
        writer.writerow([scan.type, scan.data, scan.scanned_at.strftime("%Y-%m-%d %H:%M:%S"), scan.user_id or ""])

    output.seek(0)
    return send_file(
        BytesIO(output.getvalue().encode('utf-8')),
        mimetype='text/csv',
        as_attachment=True,
        download_name='scan_history.csv'
    )


@app.route("/download/json")
def download_json():
    scans = Scan.query.all()
    data = {
        "scans": [scan.to_dict() for scan in scans],
        "counts": get_scan_counts()
    }
    return send_file(
        BytesIO(json.dumps(data, indent=4).encode('utf-8')),
        mimetype='application/json',
        as_attachment=True,
        download_name='scan_history.json'
    )


@app.errorhandler(RequestEntityTooLarge)
def handle_large_file(e):
    return render_template("upload_result.html", results=[], counts={},
                           error="❌ Image too large. Please upload a file under 10MB."), 413


 # Required for sessions


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        user = User.query.filter_by(username=username).first()

        if user and check_password_hash(user.password, password):
            session["authenticated"] = True
            session["username"] = user.username
            session["user_id"] = user.id
            flash("✅ Login successful!")
            return redirect(url_for("history"))
        else:
            return render_template("login.html", error="❌ Invalid username or password.")
    return render_template("login.html")


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form.get("username").strip()
        email = request.form.get("email").strip()
        password = request.form.get("password").strip()

        # Check for existing user
        existing_user = User.query.filter((User.username == username) | (User.email == email)).first()
        if existing_user:
            return render_template("signup.html", error="❌ Username or email already exists.")

        hashed_password = generate_password_hash(password)

        new_user = User(username=username, email=email, password=hashed_password)
        db.session.add(new_user)
        db.session.commit()

        flash("✅ Signup successful! Please login.")
        return redirect(url_for("login"))
    return render_template("signup.html")


@app.route("/clear-history", methods=["POST"])
@login_required
def clear_history():
    try:
        # Clear all scans
        Scan.query.delete()
        # Reset all scan counts
        ScanCount.query.delete()
        db.session.commit()
        flash("✅ Scan history cleared successfully!")
    except Exception as e:
        db.session.rollback()
        flash(f"❌ Error clearing history: {str(e)}")
    return redirect(url_for("history"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


@app.route("/record-builder")
@login_required
def record_builder():
    return render_template("record-builder.html")


@app.route("/save-record-scan", methods=["POST"])
@login_required
def save_record_scan():
    try:
        data = request.get_json(force=True)

        format = data.get("format")
        text = data.get("text")
        meta_info = data.get("meta_info")

        if not format or not text or not meta_info:
            return jsonify({"error": "Missing format, text, or meta_info"}), 400

        title = meta_info.get("title", "").strip()
        if not title:
            return jsonify({"error": "Title is required in meta_info"}), 400

        # Get the current user
        username = session.get("username")
        if not username:
            return jsonify({"error": "User not authenticated"}), 401

        user = User.query.filter_by(username=username).first()
        if not user:
            return jsonify({"error": "User not found"}), 401

        # Get or create record
        record = Record.query.filter_by(user_id=user.id, title=title).first()
        if not record:
            record = Record(
                user_id=user.id,
                title=title,
                subtitle=meta_info.get("subtitle", ""),
                code=meta_info.get("code", "")
            )
            db.session.add(record)
            db.session.commit()

        # Check if scan already exists in this record (simple check)
        existing_scan = RecordScan.query.filter_by(
            record_id=record.id,
            data=text,
            type=format
        ).first()

        if not existing_scan:
            new_scan = RecordScan(
                record_id=record.id,
                data=text,
                type=format
            )
            db.session.add(new_scan)

            # Update record's updated_at timestamp
            record.updated_at = datetime.utcnow()
            db.session.commit()

            return jsonify({"new": True, "message": "Scan saved."})
        else:
            return jsonify({"new": False, "message": "Duplicate scan."})

    except Exception as e:
        db.session.rollback()
        import traceback
        print("Error saving scan:", traceback.format_exc())
        return jsonify({"error": f"Exception: {str(e)}"}), 500


@app.route("/record-camera")
@login_required
def record_camera():
    return render_template("record-camera.html")


@app.route("/preview-record")
def preview_record():
    title = request.args.get("title", "").strip()
    if not title:
        return jsonify({"error": "Title is required"}), 400

    # Get current user
    username = session.get("username")
    if not username:
        return jsonify({"error": "User not authenticated"}), 401

    user = User.query.filter_by(username=username).first()
    if not user:
        return jsonify({"error": "User not found"}), 401

    # Get record
    record = Record.query.filter_by(user_id=user.id, title=title).first()
    if not record:
        return jsonify({"record": {}})

    # Get all scans for this record
    scans = RecordScan.query.filter_by(record_id=record.id).all()
    record_data = {}

    for scan in scans:
        key = f"{scan.type}:{scan.data}"
        record_data[key] = scan.to_dict()

    return jsonify(record_data)


def time_ago(from_time):
    now = datetime.now()
    delta = now - from_time
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
    username = session.get("username")
    user = User.query.filter_by(username=username).first()

    if not user:
        return redirect(url_for("login"))

    # Get all records and folders for the user
    records = Record.query.filter_by(user_id=user.id).order_by(desc(Record.updated_at)).all()
    folders = Folder.query.filter_by(user_id=user.id).all()

    record_list = []
    for record in records:
        record_list.append({
            "title": record.title,
            "subtitle": record.subtitle,
            "count": record.get_scan_count(),
            "folder": record.folder.name if record.folder else "Uncategorized",
            "folder_id": record.folder_id,
            "last_modified": record.updated_at.timestamp(),
            "modified": time_ago(record.updated_at)
        })

    folder_list = [folder.to_dict() for folder in folders]

    return render_template("record-dashboard.html", records=record_list, folders=folder_list)

@app.route("/delete-record", methods=["POST"])
@login_required
def delete_record():
    title = request.form.get("title")
    username = session.get("username")

    user = User.query.filter_by(username=username).first()
    if not user:
        return redirect(url_for("login"))

    record = Record.query.filter_by(user_id=user.id, title=title).first()
    if record:
        # This will also delete associated RecordScans due to cascade
        db.session.delete(record)
        db.session.commit()
        flash(f"✅ Record '{title}' deleted successfully!")

    return redirect(url_for("record_dashboard"))


@app.route("/update-subtitle", methods=["POST"])
@login_required
def update_subtitle():
    title = request.form.get("title", "").strip()
    new_subtitle = request.form.get("subtitle", "").strip()

    username = session.get("username")
    user = User.query.filter_by(username=username).first()

    if not user:
        return redirect(url_for("login"))

    record = Record.query.filter_by(user_id=user.id, title=title).first()
    if record:
        record.subtitle = new_subtitle
        record.updated_at = datetime.utcnow()
        db.session.commit()
        flash(f"✅ Subtitle updated for '{title}'!")

    return redirect(url_for("record_dashboard"))


@app.route("/download-record")
@login_required
def download_record():
    title = request.args.get("title", "").strip()
    format = request.args.get("format", "csv").lower()

    if not title:
        return "Missing title", 400

    username = session.get("username")
    user = User.query.filter_by(username=username).first()

    if not user:
        return "User not found", 401

    record = Record.query.filter_by(user_id=user.id, title=title).first()
    if not record:
        return f"Record '{title}' not found", 404

    # Get all scans for this record
    scans = RecordScan.query.filter_by(record_id=record.id).order_by(desc(RecordScan.scanned_at)).all()

    if format == "csv":
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(["Type", "Data", "Scanned At"])

        for scan in scans:
            writer.writerow([
                scan.type,
                scan.data,
                scan.scanned_at.strftime("%Y-%m-%d %H:%M:%S")
            ])

        output.seek(0)
        return send_file(
            BytesIO(output.getvalue().encode("utf-8")),
            mimetype="text/csv",
            as_attachment=True,
            download_name=f"{secure_filename(title)}.csv"
        )

    elif format == "excel":
        scan_data = [scan.to_dict() for scan in scans]
        df = pd.DataFrame(scan_data)
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


@app.route("/create-folder", methods=["POST"])
@login_required
def create_folder():
    try:
        data = request.get_json()
        name = data.get("name", "").strip()

        if not name:
            return jsonify({"error": "Folder name is required"}), 400

        username = session.get("username")
        user = User.query.filter_by(username=username).first()

        if not user:
            return jsonify({"error": "User not found"}), 401

        # Check if folder already exists
        existing_folder = Folder.query.filter_by(user_id=user.id, name=name).first()
        if existing_folder:
            return jsonify({"error": "Folder already exists"}), 400

        new_folder = Folder(user_id=user.id, name=name)
        db.session.add(new_folder)
        db.session.commit()

        return jsonify({"success": True, "folder": new_folder.to_dict()})

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@app.route("/rename-folder", methods=["POST"])
@login_required
def rename_folder():
    try:
        data = request.get_json()
        folder_id = data.get("id")
        new_name = data.get("name", "").strip()

        if not new_name:
            return jsonify({"error": "Folder name is required"}), 400

        username = session.get("username")
        user = User.query.filter_by(username=username).first()

        if not user:
            return jsonify({"error": "User not found"}), 401

        folder = Folder.query.filter_by(id=folder_id, user_id=user.id).first()
        if not folder:
            return jsonify({"error": "Folder not found"}), 404

        folder.name = new_name
        db.session.commit()

        return jsonify({"success": True, "folder": folder.to_dict()})

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@app.route("/delete-folder", methods=["POST"])
@login_required
def delete_folder():
    try:
        data = request.get_json()
        folder_id = data.get("id")

        username = session.get("username")
        user = User.query.filter_by(username=username).first()

        if not user:
            return jsonify({"error": "User not found"}), 401

        folder = Folder.query.filter_by(id=folder_id, user_id=user.id).first()
        if not folder:
            return jsonify({"error": "Folder not found"}), 404

        # Move all records in this folder to uncategorized (folder_id = None)
        Record.query.filter_by(folder_id=folder_id).update({"folder_id": None})

        # Delete the folder
        db.session.delete(folder)
        db.session.commit()

        return jsonify({"success": True})

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@app.route("/move-record-to-folder", methods=["POST"])
@login_required
def move_record_to_folder():
    try:
        data = request.get_json()
        record_title = data.get("title")
        folder_id = data.get("folder_id")  # Can be None for uncategorized

        username = session.get("username")
        user = User.query.filter_by(username=username).first()

        if not user:
            return jsonify({"error": "User not found"}), 401

        record = Record.query.filter_by(user_id=user.id, title=record_title).first()
        if not record:
            return jsonify({"error": "Record not found"}), 404

        # Validate folder exists if folder_id is provided
        if folder_id:
            folder = Folder.query.filter_by(id=folder_id, user_id=user.id).first()
            if not folder:
                return jsonify({"error": "Folder not found"}), 404

        record.folder_id = folder_id
        record.updated_at = datetime.utcnow()
        db.session.commit()

        return jsonify({"success": True})

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@app.route("/api/dashboard-data")
@login_required
def api_dashboard_data():
    """Get all folders and records for the dashboard"""
    try:
        username = session.get("username")
        user = User.query.filter_by(username=username).first()

        if not user:
            return jsonify({"success": False, "error": "User not found"}), 401

        # Create default folders if user has no folders
        create_default_folders_if_needed(user.id)

        # Get all folders for the user
        folders = Folder.query.filter_by(user_id=user.id).all()
        folder_list = [folder.to_dict() for folder in folders]

        # Get all records for the user with additional info
        records = Record.query.filter_by(user_id=user.id).order_by(desc(Record.updated_at)).all()
        record_list = []

        for record in records:
            record_data = record.to_dict()
            record_data['scan_count'] = record.get_scan_count()
            record_data['updated_at'] = record.updated_at.strftime("%Y-%m-%d")
            record_list.append(record_data)

        return jsonify({
            "success": True,
            "folders": folder_list,
            "records": record_list
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


def create_default_folders_if_needed(user_id):
    """Create default folders for new users if they don't have any folders"""
    existing_folders = Folder.query.filter_by(user_id=user_id).count()

    if existing_folders == 0:
        default_folders = [
            'Work Projects',
            'Personal Records',
            'Archive',
            'Important Documents'
        ]

        for folder_name in default_folders:
            new_folder = Folder(
                user_id=user_id,
                name=folder_name,
                parent_id=None
            )
            db.session.add(new_folder)

        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            raise e

@app.route("/api/create-folder", methods=["POST"])
@login_required
def api_create_folder():
    """Create a new folder (with optional parent)"""
    try:
        data = request.get_json()
        name = data.get("name", "").strip()
        parent_id = data.get("parent_id")  # NEW: Optional parent folder

        if not name:
            return jsonify({"success": False, "error": "Folder name is required"}), 400

        username = session.get("username")
        user = User.query.filter_by(username=username).first()

        if not user:
            return jsonify({"success": False, "error": "User not found"}), 401

        # Check if parent folder exists and belongs to user (if specified)
        if parent_id:
            parent_folder = Folder.query.filter_by(id=parent_id, user_id=user.id).first()
            if not parent_folder:
                return jsonify({"success": False, "error": "Parent folder not found"}), 404

        # Check if folder already exists with same name and parent
        existing_folder = Folder.query.filter_by(
            user_id=user.id,
            name=name,
            parent_id=parent_id
        ).first()

        if existing_folder:
            return jsonify({"success": False, "error": "Folder already exists"}), 400

        new_folder = Folder(user_id=user.id, name=name, parent_id=parent_id)
        db.session.add(new_folder)
        db.session.commit()

        return jsonify({"success": True, "folder": new_folder.to_dict()})

    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/rename-folder", methods=["POST"])
@login_required
def api_rename_folder():
    """Rename an existing folder"""
    try:
        data = request.get_json()
        folder_id = data.get("id")
        new_name = data.get("name", "").strip()

        if not new_name:
            return jsonify({"success": False, "error": "Folder name is required"}), 400

        username = session.get("username")
        user = User.query.filter_by(username=username).first()

        if not user:
            return jsonify({"success": False, "error": "User not found"}), 401

        folder = Folder.query.filter_by(id=folder_id, user_id=user.id).first()
        if not folder:
            return jsonify({"success": False, "error": "Folder not found"}), 404

        # Check for name conflicts in the same parent
        existing_folder = Folder.query.filter_by(
            user_id=user.id,
            name=new_name,
            parent_id=folder.parent_id
        ).filter(Folder.id != folder_id).first()

        if existing_folder:
            return jsonify({"success": False, "error": "Folder name already exists"}), 400

        folder.name = new_name
        db.session.commit()

        return jsonify({"success": True, "folder": folder.to_dict()})

    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/delete-folder", methods=["POST"])
@login_required
def api_delete_folder():
    """Delete a folder and move its records to uncategorized"""
    try:
        data = request.get_json()
        folder_id = data.get("id")

        username = session.get("username")
        user = User.query.filter_by(username=username).first()

        if not user:
            return jsonify({"success": False, "error": "User not found"}), 401

        folder = Folder.query.filter_by(id=folder_id, user_id=user.id).first()
        if not folder:
            return jsonify({"success": False, "error": "Folder not found"}), 404

        # Move all records in this folder (and subfolders) to uncategorized
        def move_folder_records(folder_to_delete):
            # Move records in this folder
            Record.query.filter_by(folder_id=folder_to_delete.id).update({"folder_id": None})

            # Move records in subfolders recursively
            subfolders = Folder.query.filter_by(parent_id=folder_to_delete.id).all()
            for subfolder in subfolders:
                move_folder_records(subfolder)

        move_folder_records(folder)

        # Delete all subfolders recursively
        def delete_subfolders(parent_folder):
            subfolders = Folder.query.filter_by(parent_id=parent_folder.id).all()
            for subfolder in subfolders:
                delete_subfolders(subfolder)
                db.session.delete(subfolder)

        delete_subfolders(folder)

        # Delete the main folder
        db.session.delete(folder)
        db.session.commit()

        return jsonify({"success": True})

    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/move-record-to-folder", methods=["POST"])
@login_required
def api_move_record_to_folder():
    """Move a record to a different folder"""
    try:
        data = request.get_json()
        record_title = data.get("title")
        folder_id = data.get("folder_id")  # Can be None for uncategorized

        username = session.get("username")
        user = User.query.filter_by(username=username).first()

        if not user:
            return jsonify({"success": False, "error": "User not found"}), 401

        record = Record.query.filter_by(user_id=user.id, title=record_title).first()
        if not record:
            return jsonify({"success": False, "error": "Record not found"}), 404

        # Validate folder exists if folder_id is provided
        if folder_id:
            folder = Folder.query.filter_by(id=folder_id, user_id=user.id).first()
            if not folder:
                return jsonify({"success": False, "error": "Folder not found"}), 404

        record.folder_id = folder_id
        record.updated_at = datetime.utcnow()
        db.session.commit()

        return jsonify({"success": True})

    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=True)

    # Locally work online work
    # from development on site no
