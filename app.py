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


def clean_prefix(raw):
    """Macht aus 'a//b/' oder '/a/b' den Ordnerpfad 'a/b/' ('' = oberste Ebene)."""
    parts = [p.strip() for p in (raw or "").replace("\\", "/").split("/")]
    parts = [p for p in parts if p]
    if any(p in (".", "..") for p in parts):
        raise ValueError("Ungueltiger Ordnerpfad")
    return "/".join(parts) + "/" if parts else ""


def presigned_put(s3, bucket, key, data, content_type):
    """Laedt mit einer Presigned URL hoch (gleich wie curl -X PUT -T)."""
    url = s3.generate_presigned_url(
        "put_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=EXPIRES
    )
    req = urllib.request.Request(
        url, data=data, method="PUT", headers={"Content-Type": content_type}
    )
    try:
        with urllib.request.urlopen(req) as r:
            return {"ok": True, "key": key, "status": r.status, "url": url, "expires": EXPIRES}
    except urllib.error.HTTPError as e:
        return {"ok": False, "key": key, "status": e.code, "url": url, **b2_error(e.read())}


def presigned_delete(s3, bucket, key):
    url = s3.generate_presigned_url(
        "delete_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=EXPIRES
    )
    req = urllib.request.Request(url, method="DELETE")
    try:
        with urllib.request.urlopen(req) as r:
            return {"ok": True, "key": key, "status": r.status}
    except urllib.error.HTTPError as e:
        return {"ok": False, "key": key, "status": e.code, **b2_error(e.read())}


@app.route("/api/files")
def list_files():
    role = get_role()
    if not role:
        return jsonify(error="Unbekannte Rolle"), 400
    try:
        prefix = clean_prefix(request.args.get("prefix"))
    except ValueError as e:
        return jsonify(error=str(e)), 400
    s3, bucket = client_for(role)
    folders, files = [], []
    try:
        # Delimiter="/" fasst alles unterhalb eines Unterordners zu einem Ordner zusammen
        pages = s3.get_paginator("list_objects_v2").paginate(
            Bucket=bucket, Prefix=prefix, Delimiter="/"
        )
        for page in pages:
            for p in page.get("CommonPrefixes", []):
                folders.append({"prefix": p["Prefix"], "name": p["Prefix"][len(prefix):-1]})
            for o in page.get("Contents", []):
                if o["Key"] == prefix:  # Platzhalter des Ordners selbst
                    continue
                files.append({
                    "key": o["Key"],
                    "name": o["Key"][len(prefix):],
                    "size": o["Size"],
                    "modified": o["LastModified"].isoformat(),
                })
    except Exception as e:  # z. B. AccessDenied
        return jsonify(error=str(e)), 403
    return jsonify(bucket=bucket, prefix=prefix, folders=folders, files=files)


@app.route("/api/folders")
def all_folders():
    """Alle Ordner im Bucket (fuer die Zielauswahl beim Upload)."""
    role = get_role()
    if not role:
        return jsonify(error="Unbekannte Rolle"), 400
    s3, bucket = client_for(role)
    found = set()
    try:
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket):
            for o in page.get("Contents", []):
                parts = o["Key"].split("/")[:-1]  # letzter Teil ist der Dateiname
                for i in range(1, len(parts) + 1):
                    found.add("/".join(parts[:i]) + "/")
    except Exception as e:
        return jsonify(error=str(e)), 403
    return jsonify(folders=sorted(found, key=str.lower))


@app.route("/api/upload", methods=["POST"])
def upload():
    role = get_role()
    f = request.files.get("file")
    if not role or not f or not f.filename:
        return jsonify(error="Rolle oder Datei fehlt"), 400
    try:
        prefix = clean_prefix(request.values.get("prefix"))
    except ValueError as e:
        return jsonify(error=str(e)), 400
    s3, bucket = client_for(role)
    key = prefix + os.path.basename(f.filename)
    result = presigned_put(s3, bucket, key, f.read(), f.mimetype or "application/octet-stream")
    return jsonify(**result)


@app.route("/api/mkdir", methods=["POST"])
def mkdir():
    role = get_role()
    name = (request.values.get("name") or "").strip()
    if not role or not name:
        return jsonify(error="Rolle oder Ordnername fehlt"), 400
    if "/" in name or "\\" in name or name in (".", ".."):
        return jsonify(error="Der Ordnername darf kein / oder \\ enthalten"), 400
    try:
        prefix = clean_prefix(request.values.get("prefix"))
    except ValueError as e:
        return jsonify(error=str(e)), 400
    s3, bucket = client_for(role)
    # B2 kennt keine echten Ordner: ein leeres Objekt "name/" dient als Platzhalter
    result = presigned_put(s3, bucket, prefix + name + "/", b"", "application/x-directory")
    result.pop("url", None)
    return jsonify(**result)


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
    if not key.endswith("/"):
        return jsonify(**presigned_delete(s3, bucket, key))

    # Ordner: alles darunter loeschen, Platzhalter zuletzt
    try:
        prefix = clean_prefix(key)
    except ValueError as e:
        return jsonify(error=str(e)), 400
    keys = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        keys += [o["Key"] for o in page.get("Contents", [])]
    keys.sort(key=lambda k: (k == prefix, k))
    deleted = 0
    for k in keys:
        result = presigned_delete(s3, bucket, k)
        if not result["ok"]:  # z. B. AccessDenied beim Viewer: sofort abbrechen
            return jsonify(**result, deleted=deleted)
        deleted += 1
    return jsonify(ok=True, key=prefix, status=204, deleted=deleted)


if __name__ == "__main__":
    if not ROLES:
        raise SystemExit("Keine .env.admin, .env.viewer oder .env gefunden.")
    print("Rollen geladen:", ", ".join(ROLES))
    app.run(host="127.0.0.1", port=5000, debug=False)
