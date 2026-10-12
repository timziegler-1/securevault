import os
import boto3
from dotenv import load_dotenv

load_dotenv()  # liest die Werte aus der .env-Datei ein

s3 = boto3.client(
    "s3",
    endpoint_url=os.environ["B2_ENDPOINT"],
    region_name=os.environ["B2_REGION"],
    aws_access_key_id=os.environ["B2_KEY_ID"],
    aws_secret_access_key=os.environ["B2_APP_KEY"],
)

BUCKET = os.environ["B2_BUCKET"]

def get_upload_url(key, expires=300):
    return s3.generate_presigned_url(
        "put_object",
        Params={"Bucket": BUCKET, "Key": key},
        ExpiresIn=expires,
    )

def get_download_url(key, expires=300):
    return s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": BUCKET, "Key": key},
        ExpiresIn=expires,
    )

def menu():
    while True:
        print("\n1) Upload-URL erzeugen")
        print("2) Download-URL erzeugen")
        print("3) Beenden")
        choice = input("Auswahl: ")
        if choice == "1":
            key = input("Dateiname (Key) fuers Hochladen: ")
            print(get_upload_url(key))
        elif choice == "2":
            key = input("Dateiname (Key) fuers Herunterladen: ")
            print(get_download_url(key))
        elif choice == "3":
            break

if __name__ == "__main__":
    menu()
