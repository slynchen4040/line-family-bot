from google.genai import types
from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi,
    ReplyMessageRequest, TextMessage
)
from linebot.v3.messaging import MessagingApiBlob
from linebot.v3.webhooks import (
    MessageEvent, TextMessageContent, ImageMessageContent
)
from google import genai
import os
from collections import defaultdict, deque

app = Flask(__name__)

configuration = Configuration(access_token=os.environ['LINE_CHANNEL_ACCESS_TOKEN'])
handler = WebhookHandler(os.environ['LINE_CHANNEL_SECRET'])
client = genai.Client(api_key=os.environ['GEMINI_API_KEY'])

# 人設：陳家家庭秘書
SYSTEM_PROMPT = """你是陳家的家庭群組小秘書，名字叫「小秘書」。

【個性與語氣】
- 溫暖、親切、尊重，會稱呼大家「家人們」
- 對長輩特別有耐心，用詞要簡單清楚，避免艱澀術語
- 回覆要溫暖但不過度熱情，像一個貼心的家庭幫手

【回覆規則】
- 回覆務必簡短，不超過 100 個字
- 不要過度插話、不要用過多表情符號（最多一個）
- 保持自然、不刻意

【誠實原則 - 非常重要】
- 如果不確定答案，請直說：「這個我不太確定，建議再查證一下喔」
- 絕對不要編造資訊，特別是健康、藥物、醫療相關
- 涉及健康或用藥問題，一律提醒「建議諮詢醫師或藥師」
- 不要假裝知道你不知道的事

【記憶】
- 你會看到最近的對話紀錄，請保持上下文連貫
- 但不需要每次都複述前面講過的內容"""

# 圖片識別專用 prompt（特別針對醫藥安全）
IMAGE_PROMPT = """你是陳家的家庭小秘書，家人傳了一張圖片給你。請幫忙看看這是什麼。

【判斷與回覆原則】
1. 先簡單描述圖片內容（一兩句）
2. 如果是藥袋、處方箋、藥盒、檢驗報告：
   - 念出上面寫的重點文字（藥名、劑量、用法）
   - 一定要加上：「實際用法請以醫師或藥師指示為準喔」
   - 絕對不要自己判斷療效或副作用
3. 如果是食物：簡單說明這是什麼食物
4. 如果是文件、表格：幫忙念出重點資訊
5. 如果看不清楚或不確定：直說「這張圖我看得不太清楚，可以再拍一張嗎？」

【回覆風格】
- 稱呼「家人們」
- 簡短（100 字內），溫暖
- 對長輩友善，用詞簡單
- 表情符號最多一個"""

# 短期記憶
memory = defaultdict(lambda: deque(maxlen=5))

# 觸發關鍵字（在群組中需要這些字才回應文字訊息）
KEYWORDS = ['小秘書', '你好', '請問', '幫我', '怎麼', '什麼', '為什麼', '健康', '醫生', '藥']


def get_source_id(event):
    source = event.source
    if source.type == 'group':
        return f"group_{source.group_id}"
    elif source.type == 'room':
        return f"room_{source.room_id}"
    else:
        return f"user_{source.user_id}"


def should_reply_text(event, user_text):
    """文字訊息：一對一每則都回，群組要關鍵字"""
    if event.source.type == 'user':
        return True
    return any(kw in user_text for kw in KEYWORDS)


def should_reply_image(event):
    """圖片訊息：一對一一律回應，群組也回應（家人特別傳圖通常是想問）"""
    return True


def build_prompt(source_id, user_text):
    history = memory[source_id]
    conversation = SYSTEM_PROMPT + "\n\n"
    if history:
        conversation += "【最近的對話紀錄】\n"
        for past_user, past_bot in history:
            conversation += f"家人說：{past_user}\n小秘書回：{past_bot}\n"
        conversation += "\n"
    conversation += f"【現在的訊息】\n家人說：{user_text}\n小秘書回："
    return conversation


def reply_to_line(event, reply_text):
    """把回覆送回 LINE"""
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)]
            )
        )


@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'


# === 處理文字訊息 ===
@handler.add(MessageEvent, message=TextMessageContent)
def handle_text_message(event):
    user_text = event.message.text
    source_id = get_source_id(event)

    if not should_reply_text(event, user_text):
        return

    try:
        prompt = build_prompt(source_id, user_text)
        response = client.models.generate_content(
            model='gemini-flash-latest',
            contents=prompt
        )
        reply_text = response.text.strip()
        if len(reply_text) > 500:
            reply_text = reply_text[:497] + "..."
        memory[source_id].append((user_text, reply_text))
    except Exception as e:
        print(f"Gemini text error: {e}")
        reply_text = "抱歉，我現在有點忙，稍後再試試看喔！"

    reply_to_line(event, reply_text)


# === 處理圖片訊息 ===
@handler.add(MessageEvent, message=ImageMessageContent)
def handle_image_message(event):
    if not should_reply_image(event):
        return

    source_id = get_source_id(event)

    try:
        # 從 LINE 下載圖片
        with ApiClient(configuration) as api_client:
            line_bot_blob_api = MessagingApiBlob(api_client)
            image_bytes = line_bot_blob_api.get_message_content(
                message_id=event.message.id
            )

        # 傳給 Gemini 分析
        image_part = types.Part.from_bytes(
            data=image_bytes,
            mime_type='image/jpeg'
        )

        response = client.models.generate_content(
            model='gemini-flash-latest',
            contents=[IMAGE_PROMPT, image_part]
        )
        reply_text = response.text.strip()
        if len(reply_text) > 500:
            reply_text = reply_text[:497] + "..."

        # 存入記憶（圖片用佔位符）
        memory[source_id].append(("[家人傳了一張圖片]", reply_text))

    except Exception as e:
        print(f"Gemini image error: {e}")
        reply_text = "抱歉，這張圖我現在看不太清楚，等等再試試看好嗎？"

    reply_to_line(event, reply_text)


if __name__ == "__main__":
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
