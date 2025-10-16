"""
Backfill local SQLite data into Firestore.
Run with: python scripts\backfill_to_firestore.py

This script is best-effort and idempotent: it writes documents using sqlite IDs as Firestore document IDs.
It requires that serviceAccountKey.json exists and firestore_db is available.
"""
import sys
import traceback
import os

# Ensure project root is on sys.path so we can import main when run from scripts/
ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from main import app, db, User, Folder, Record, RecordScan, Scan, ScanCount, firestore_db, FIRESTORE_WRITE, auth
import secrets
import json

OUT_DIR = os.path.join(ROOT, 'migrations', 'backups')
os.makedirs(OUT_DIR, exist_ok=True)

def gen_temp_password(length=12):
    return secrets.token_urlsafe(length)[:length]


def backfill_user(user):
    uid = user.firebase_uid
    used_legacy = False
    # If user has no firebase_uid, attempt to create one
    if not uid:
        try:
            if user.email:
                temp_pw = gen_temp_password()
                firebase_user = auth.create_user(email=user.email, password=temp_pw, display_name=user.username)
                uid = firebase_user.uid
                user.firebase_uid = uid
                db.session.commit()
                # record mapping
                mapping = {
                    'sqlite_id': user.id,
                    'username': user.username,
                    'email': user.email,
                    'firebase_uid': uid,
                    'temp_password': temp_pw
                }
                # append mapping to file
                mappings_file = os.path.join(OUT_DIR, 'user_mappings_pending.json')
                try:
                    existing = []
                    if os.path.exists(mappings_file):
                        with open(mappings_file, 'r', encoding='utf-8') as f:
                            existing = json.load(f)
                    existing.append(mapping)
                    with open(mappings_file, 'w', encoding='utf-8') as f:
                        json.dump(existing, f, indent=2)
                except Exception:
                    pass
                print(f"Created Firebase user for {user.email} -> uid={uid}")
            else:
                print(f"User {user.username} has no email; will write to legacy namespace")
                used_legacy = True
        except Exception as e:
            print(f"Could not create Firebase user for {user.username}: {e}")
            used_legacy = True

    # If still no uid, write under legacy path
    if not uid:
        used_legacy = True
        uid = f"legacy_{user.id}"
    if firestore_db is None:
        print("Firestore not initialized. Aborting backfill.")
        return
    target_root = "users" if not used_legacy else "users_legacy"
    print(f"Backfilling user {user.username} -> {target_root}/{uid}")

    try:
        # Folders
        folders = Folder.query.filter_by(user_id=user.id).all()
        for f in folders:
            doc_ref = firestore_db.collection(target_root).document(uid).collection("folders").document(str(f.id))
            doc_ref.set({
                "sqlite_id": f.id,
                "user_id": f.user_id,
                "name": f.name,
                "parent_id": f.parent_id,
                "created_at": f.created_at.isoformat(),
                "firebase_uid": uid if not used_legacy else None
            })

        # Records and record scans
        records = Record.query.filter_by(user_id=user.id).all()
        for r in records:
            r_ref = firestore_db.collection(target_root).document(uid).collection("records").document(str(r.id))
            r_ref.set({
                "sqlite_id": r.id,
                "user_id": r.user_id,
                "title": r.title,
                "subtitle": r.subtitle,
                "code": r.code,
                "folder_id": r.folder_id,
                "created_at": r.created_at.isoformat(),
                "updated_at": r.updated_at.isoformat(),
                "firebase_uid": uid if not used_legacy else None
            })
            scans = RecordScan.query.filter_by(record_id=r.id).all()
            for s in scans:
                firestore_db.collection(target_root).document(uid).collection("record_scans").document(str(s.id)).set({
                    "sqlite_id": s.id,
                    "record_sqlite_id": r.id,
                    "data": s.data,
                    "type": s.type,
                    "scanned_at": s.scanned_at.isoformat(),
                    "firebase_uid": uid if not used_legacy else None
                })

        # Scans
        scans = Scan.query.filter_by(user_id=user.id).all()
        for s in scans:
            firestore_db.collection(target_root).document(uid).collection("scans").document(str(s.id)).set({
                "sqlite_id": s.id,
                "data": s.data,
                "type": s.type,
                "scanned_at": s.scanned_at.isoformat(),
                "user_id": s.user_id,
                "firebase_uid": uid if not used_legacy else None
            })

        # Counts (optional): write scan counts to meta/counts
        counts = ScanCount.get_counts()
        try:
            firestore_db.collection(target_root).document(uid).collection("meta").document("counts").set(counts)
        except Exception:
            pass

        print(f"Backfill completed for user {user.username}")

    except Exception as e:
        print(f"Error backfilling user {user.username}: {e}")
        traceback.print_exc()


if __name__ == '__main__':
    with app.app_context():
        if not FIRESTORE_WRITE:
            print("FIRESTORE_WRITE is disabled. Export aborted.")
            sys.exit(1)

        users = User.query.all()
        if not users:
            print("No users found to backfill.")
            sys.exit(0)

        for u in users:
            backfill_user(u)

        print("Backfill run complete.")
