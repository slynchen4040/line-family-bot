import os
from google import genai
from google.genai import types
from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi,
    ReplyMessageRequest, TextMessage
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent

app = Flask(__name__)

configuration = Configuration(access_token=os.environ['LINE_CHANNEL_ACCESS_TOKEN'])
handler = WebhookHandler(os.environ['LINE_CHANNEL_SECRET'])
client = genai.Client(api_key=os.environ['GEMINI_API_KEY'])

SYSTEM_PROMPT = """你是家庭群組裡的溫暖小秘書，名字叫「小秘書」。
請用溫和、親切、尊重的語氣回應。回覆要簡短，不超過100字。
如果有人分享健康資訊，要溫和提醒這只是參考，建議諮詢醫師。
不要過度插話，只在被叫到名字或有明確問題時才回應。"""

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_text = event.message.text
    keywords = ['小秘書', '你好', '請問', '幫我', '怎麼', '什麼', '為什麼', '健康', '醫生', '藥']
    should_reply = any(kw in user_text for kw in keywords)
    if not should_reply:
        return
    try:
        response = client.models.generate_content(
            model='gemini-1.5-flash',
            contents=f"{SYSTEM_PROMPT}\n\n用戶說：{user_text}"
        )
        reply_text = response.text
    except Exception as e:
        print(f"Gemini error: {e}")
        reply_text = "抱歉，我現在有點忙，稍後再試試看喔！"
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)]
            )
        )

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
