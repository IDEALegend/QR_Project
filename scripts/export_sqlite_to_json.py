"""
Export SQLite tables to JSON files under migrations/backups/
Run: python scripts\export_sqlite_to_json.py
"""
import os
import sys
import json
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from main import app, db, User, Scan, Record, RecordScan, Folder, QRGeneration, UploadAttempt, ScanCount

OUT_DIR = os.path.join(ROOT, 'migrations', 'backups')
os.makedirs(OUT_DIR, exist_ok=True)

def to_json_serializable(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    return obj

with app.app_context():
    try:
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        files_written = []

        # Users
        users = []
        for u in User.query.all():
            users.append({
                'id': u.id,
                'username': u.username,
                'email': u.email,
                'password': u.password,
                'firebase_uid': u.firebase_uid
            })
        path = os.path.join(OUT_DIR, f'users_{timestamp}.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(users, f, default=to_json_serializable, indent=2)
        files_written.append(path)

        # Scans
        scans = []
        for s in Scan.query.all():
            scans.append({
                'id': s.id,
                'user_id': s.user_id,
                'data': s.data,
                'type': s.type,
                'scanned_at': getattr(s.scanned_at, 'isoformat', lambda: s.scanned_at)()
            })
        path = os.path.join(OUT_DIR, f'scans_{timestamp}.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(scans, f, default=to_json_serializable, indent=2)
        files_written.append(path)

        # Records
        records = []
        for r in Record.query.all():
            records.append({
                'id': r.id,
                'user_id': r.user_id,
                'folder_id': r.folder_id,
                'title': r.title,
                'subtitle': r.subtitle,
                'code': r.code,
                'created_at': r.created_at.isoformat(),
                'updated_at': r.updated_at.isoformat()
            })
        path = os.path.join(OUT_DIR, f'records_{timestamp}.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(records, f, default=to_json_serializable, indent=2)
        files_written.append(path)

        # RecordScans
        record_scans = []
        for rs in RecordScan.query.all():
            record_scans.append({
                'id': rs.id,
                'record_id': rs.record_id,
                'data': rs.data,
                'type': rs.type,
                'scanned_at': rs.scanned_at.isoformat()
            })
        path = os.path.join(OUT_DIR, f'record_scans_{timestamp}.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(record_scans, f, default=to_json_serializable, indent=2)
        files_written.append(path)

        # Folders
        folders = []
        for f in Folder.query.all():
            folders.append({
                'id': f.id,
                'user_id': f.user_id,
                'parent_id': f.parent_id,
                'name': f.name,
                'created_at': f.created_at.isoformat()
            })
        path = os.path.join(OUT_DIR, f'folders_{timestamp}.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(folders, f, default=to_json_serializable, indent=2)
        files_written.append(path)

        # QRGeneration
        qrs = []
        for q in QRGeneration.query.all():
            qrs.append({
                'id': q.id,
                'user_id': q.user_id,
                'data_type': q.data_type,
                'qr_data': q.qr_data,
                'qr_filename': q.qr_filename,
                'json_filename': q.json_filename,
                'generated_at': q.generated_at.isoformat()
            })
        path = os.path.join(OUT_DIR, f'qr_generation_{timestamp}.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(qrs, f, default=to_json_serializable, indent=2)
        files_written.append(path)

        # UploadAttempt
        attempts = []
        for a in UploadAttempt.query.all():
            attempts.append({
                'id': a.id,
                'user_id': a.user_id,
                'upload_type': a.upload_type,
                'filename': a.filename,
                'file_size': a.file_size,
                'success': a.success,
                'codes_found': a.codes_found,
                'error_message': a.error_message,
                'uploaded_at': a.uploaded_at.isoformat()
            })
        path = os.path.join(OUT_DIR, f'upload_attempts_{timestamp}.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(attempts, f, default=to_json_serializable, indent=2)
        files_written.append(path)

        # ScanCount
        counts = ScanCount.get_counts()
        path = os.path.join(OUT_DIR, f'scan_counts_{timestamp}.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(counts, f, default=to_json_serializable, indent=2)
        files_written.append(path)

        print("Export complete. Files written:")
        for p in files_written:
            print(" -", p)

    except Exception as e:
        print("Error exporting data:", e)
        raise
