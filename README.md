# SecureVault

Sicherer Filehosting-Service mit Backblaze B2 (Modul 346, BBZ BL).
Team: Tim Ziegler, Leonardo Moffat, Nico Orlando.

Dateien liegen in einem privaten B2-Bucket. Zugriff gibt es nur über
Presigned URLs, die 300 Sekunden gültig sind. Zwei Application Keys trennen die Rollen:

| Rolle  | Rechte         | Darf                          |
|--------|----------------|-------------------------------|
| Admin  | Read and Write | hochladen, herunterladen, löschen |
| Viewer | Read Only      | nur herunterladen             |

## Bestandteile

- `presign.py`: Kommandozeilen-Tool (Menü: Upload-URL, Download-URL, Beenden)
- `app.py` + `templates/index.html`: Web-Frontend (Flask, HTML/JS) mit Rollenwahl,
  Dateiliste, Upload, Download, Löschen und Countdown für die Gültigkeit der URL

Die Application Keys bleiben immer auf dem Server bzw. Laptop. Der Browser sieht
nur die zeitlich befristeten Presigned URLs.

## Starten

```powershell
venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Dann im Browser http://127.0.0.1:5000 öffnen.

Zugangsdaten: `.env.example` nach `.env.admin` und `.env.viewer` kopieren und die
Werte der beiden Keys eintragen. Diese Dateien sind in `.gitignore` und werden nie committet.
