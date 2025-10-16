QR_Project
==========

This project is a Flask application for scanning and managing QR codes. It uses SQLite locally and can optionally integrate with Firebase Authentication and Cloud Firestore.

Quick setup
-----------

Prerequisites:
- Python 3.10+ (use the workspace's `.venv`)
- Google Cloud Firebase project and a service account JSON key

1. Create and activate the virtual environment (if you haven't already):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

2. Install dependencies:

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If network timeouts occur while installing `firebase-admin` and its dependencies, try re-running the install with a higher timeout:

```powershell
python -m pip install --default-timeout=120 -r requirements.txt
```

3. Add your Firebase service account key to the project root as `serviceAccountKey.json`. Do NOT commit this file. `.gitignore` already excludes it.

4. (Optional) Set your Firebase Web API Key in an environment variable for safety:

```powershell
$env:FIREBASE_WEB_API_KEY = "YOUR_FIREBASE_WEB_API_KEY_HERE"
```

By default, the app uses the API key embedded in the code as a fallback.

Run the app
-----------

```powershell
.\.venv\Scripts\Activate.ps1
python main.py
```

Testing Firebase integration
---------------------------
- Sign up a user in the app. The user will be created in SQLite and a best-effort attempt will be made to create that user in Firebase Authentication.
- Log in: after local verification, the app will call the Firebase Auth REST API to sign in and place `firebase_uid` in the session on success.
- Perform a scan: scans are saved to SQLite and also pushed to Firestore (collection `scans`) if Firebase was initialized successfully.

Security
--------
- Keep `serviceAccountKey.json` private. It's ignored via `.gitignore`.
- Prefer setting the Firebase Web API Key via the `FIREBASE_WEB_API_KEY` environment variable rather than hard-coding.

Notes and next steps
--------------------
- Firebase writes are best-effort; failures are logged and do not block local SQLite operations.
- When ready to migrate fully to Firestore, remove SQLAlchemy calls and replace them with Firestore queries.

If you'd like, I can:
- Retry the dependency install for you (I can run it here), or
- Add a small admin script to list Firestore documents for quick verification.

*** End Patch