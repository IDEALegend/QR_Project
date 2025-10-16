"""
Create Firebase Auth users for SQLite users missing firebase_uid.
Produces migrations/backups/user_mappings_<timestamp>.json containing email, username, sqlite_id, firebase_uid, temp_password.
Run: python scripts\create_firebase_users_from_sqlite.py
"""
import os
import sys
import json
import traceback
from datetime import datetime
import secrets

ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from main import app, db, User, firestore_db, auth

OUT_DIR = os.path.join(ROOT, 'migrations', 'backups')
os.makedirs(OUT_DIR, exist_ok=True)


def gen_temp_password(length=12):
    # generate a reasonably strong password
    return secrets.token_urlsafe(length)[:length]

with app.app_context():
    mappings = []
    try:
        users = User.query.filter((User.firebase_uid == None) | (User.firebase_uid == "")).all()
        if not users:
            print("No users without firebase_uid found.")
        for u in users:
            # Skip users without an email
            if not u.email:
                print(f"Skipping user id={u.id} username={u.username} (no email)")
                continue
            try:
                temp_pw = gen_temp_password()
                firebase_user = auth.create_user(email=u.email, password=temp_pw, display_name=u.username)
                u.firebase_uid = firebase_user.uid
                db.session.commit()

                mapping = {
                    'sqlite_id': u.id,
                    'username': u.username,
                    'email': u.email,
                    'firebase_uid': firebase_user.uid,
                    'temp_password': temp_pw
                }
                mappings.append(mapping)
                print(f"Created Firebase user for {u.email} -> uid={firebase_user.uid}")
            except Exception as e:
                db.session.rollback()
                print(f"Failed to create Firebase user for {u.email}: {e}")
                traceback.print_exc()

        # write mappings file
        if mappings:
            ts = datetime.now().strftime('%Y%m%d%H%M%S')
            path = os.path.join(OUT_DIR, f'user_mappings_{ts}.json')
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(mappings, f, indent=2)
            print(f"Wrote user mappings to {path}")
    except Exception as e:
        print("Error scanning users:", e)
        traceback.print_exc()
