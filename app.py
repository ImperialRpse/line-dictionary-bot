from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from openai import OpenAI
import json, io, os
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

# ------------------ Flask / LINE / OpenAI ------------------
app = Flask(__name__)

LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET")
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
client = OpenAI(api_key=OPENAI_API_KEY)

# ------------------ Google Drive 設定 ------------------
SCOPES = ['https://www.googleapis.com/auth/drive']
SERVICE_ACCOUNT_INFO = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])

creds = service_account.Credentials.from_service_account_info(
    SERVICE_ACCOUNT_INFO, scopes=SCOPES
)

drive_service = build('drive', 'v3', credentials=creds)

# words.json の FILE_ID
FILE_ID = "1uyNTAd4PFzalk0r2LAYaaDtPQWsUmkDv"

# ------------------ JSON操作関数 ------------------
def load_words():
    """Google Driveからwords.jsonを取得してPythonのリストで返す"""
    try:
        request = drive_service.files().get_media(fileId=FILE_ID)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)

        done = False
        while not done:
            status, done = downloader.next_chunk()

        fh.seek(0)
        data = json.load(fh)

        # 空ファイルや dict だった場合は空リストに変換
        if not isinstance(data, list):
            data = []

        return data
    except Exception as e:
        print("Error loading words:", e)
        return []

def save_word(new_word):
    """words.jsonに単語を追加（重複は無視）"""
    try:
        words = load_words()
        # 小文字で重複チェック
        if new_word.lower() not in [w.lower() for w in words]:
            words.append(new_word)
            data = json.dumps(words, ensure_ascii=False, indent=2)

            media = MediaIoBaseUpload(
                io.BytesIO(data.encode("utf-8")),
                mimetype="application/json",
                resumable=False
            )

            drive_service.files().update(
                fileId=FILE_ID,
                media_body=media
            ).execute()
            print(f"Saved new word: {new_word}")
        else:
            print(f"Word already exists: {new_word}")
    except Exception as e:
        print("Error saving word:", e)

# ------------------ Webhook ------------------
@app.route("/webhook", methods=['POST'])
def webhook():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return 'OK'

# ------------------ LINEメッセージ処理 ------------------
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    word = event.message.text.strip()

    # 1. LINEに先に返信
    prompt = f"""
You are an English dictionary tutor.
Explain the meaning of this word in simple English and Japanese,
and make 3 short example sentences.

Word: "{word}"
"""
    try:
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[{"role": "user", "content": prompt}]
        )
        reply = response.choices[0].message.content
    except Exception as e:
        print("OpenAI API error:", e)
        reply = "Sorry, I couldn't process your word at the moment."

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply)
    )

    # 2. Google Drive に単語を追加
    save_word(word)

# ------------------ Run ------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
