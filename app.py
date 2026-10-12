"""SecureVault Web-Frontend.

Kleiner lokaler Webserver (Flask), der fuer die gewaehlte Rolle (Admin/Viewer)
Presigned URLs erzeugt. Die Application Keys bleiben auf dem Server und werden
nie an den Browser geschickt.

Start:  python app.py   ->  http://127.0.0.1:5000
"""
import os
import urllib.error
import urllib.request

import boto3
from botocore.config import Config
from dotenv import dotenv_values
from flask import Flask, jsonify, render_template, request

EXPIRES = 300  # Gueltigkeit der Presigned URLs in Sekunden

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # max. 50 MB pro Upload


def load_roles():
    """Liest .env.admin und .env.viewer. Fehlen beide, wird .env als einzige Rolle genutzt."""
    roles = {}
    for name in ("admin", "viewer"):
        path = f".env.{name}"
        if os.path.exists(path):
            roles[name] = dotenv_values(path)
    if not roles and os.path.exists(".env"):
        roles["standard"] = dotenv_values(".env")
    return roles


ROLES = load_roles()


def client_for(role):
    cfg = ROLES[role]
    s3 = boto3.client(
        "s3",
        endpoint_url=cfg["B2_ENDPOINT"],
        region_name=cfg["B2_REGION"],
        aws_access_key_id=cfg["B2_KEY_ID"],
        aws_secret_access_key=cfg["B2_APP_KEY"],
        config=Config(signature_version="s3v4"),
    )
    return s3, cfg["B2_BUCKET"]


def get_role():
    role = request.values.get("role", "")
    if role not in ROLES:
        return None
    return role


def b2_error(body):
    """Holt <Code> und <Message> aus der XML-Fehlerantwort von B2."""
    text = body.decode("utf-8", "replace")
    def tag(t):
        if f"<{t}>" in text:
            return text.split(f"<{t}>")[1].split(f"</{t}>")[0]
        return ""
    return {"code": tag("Code"), "message": tag("Message")}


@app.route("/")
def index():
    return render_template("index.html", roles=list(ROLES), expires=EXPIRES)


@app.route("/api/files")
def list_files():
    role = get_role()
    if not role:
        return jsonify(error="Unbekannte Rolle"), 400
    s3, bucket = client_for(role)
    try:
        resp = s3.list_objects_v2(Bucket=bucket)
    except Exception as e:  # z. B. AccessDenied
        return jsonify(error=str(e)), 403
    files = [
        {"key": o["Key"], "size": o["Size"], "modified": o["LastModified"].isoformat()}
        for o in resp.get("Contents", [])
    ]
    return jsonify(bucket=bucket, files=files)


@app.route("/api/upload", methods=["POST"])
def upload():
    role = get_role()
    f = request.files.get("file")
    if not role or not f or not f.filename:
        return jsonify(error="Rolle oder Datei fehlt"), 400
    s3, bucket = client_for(role)
    key = os.path.basename(f.filename)
    url = s3.generate_presigned_url(
        "put_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=EXPIRES
    )
    # Der Server laedt die Datei mit der Presigned URL hoch (gleich wie curl -X PUT -T).
    req = urllib.request.Request(
        url,
        data=f.read(),
        method="PUT",
        headers={"Content-Type": f.mimetype or "application/octet-stream"},
    )
    try:
        with urllib.request.urlopen(req) as r:
            return jsonify(ok=True, key=key, status=r.status, url=url, expires=EXPIRES)
    except urllib.error.HTTPError as e:
        return jsonify(ok=False, key=key, status=e.code, url=url, **b2_error(e.read())), 200


@app.route("/api/download-url")
def download_url():
    role = get_role()
    key = request.args.get("key", "")
    if not role or not key:
        return jsonify(error="Rolle oder Dateiname fehlt"), 400
    s3, bucket = client_for(role)
    url = s3.generate_presigned_url(
        "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=EXPIRES
    )
    return jsonify(url=url, expires=EXPIRES)


@app.route("/api/delete", methods=["POST"])
def delete():
    role = get_role()
    key = request.values.get("key", "")
    if not role or not key:
        return jsonify(error="Rolle oder Dateiname fehlt"), 400
    s3, bucket = client_for(role)
    url = s3.generate_presigned_url(
        "delete_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=EXPIRES
    )
    req = urllib.request.Request(url, method="DELETE")
    try:
        with urllib.request.urlopen(req) as r:
            return jsonify(ok=True, key=key, status=r.status)
    except urllib.error.HTTPError as e:
        return jsonify(ok=False, key=key, status=e.code, **b2_error(e.read())), 200


if __name__ == "__main__":
    if not ROLES:
        raise SystemExit("Keine .env.admin, .env.viewer oder .env gefunden.")
    print("Rollen geladen:", ", ".join(ROLES))
    app.run(host="127.0.0.1", port=5000, debug=False)
