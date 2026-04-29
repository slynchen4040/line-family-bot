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
import time
from collections import defaultdict, deque

app = Flask(__name__)

configuration = Configuration(access_token=os.environ['LINE_CHANNEL_ACCESS_TOKEN'])
handler = WebhookHandler(os.environ['LINE_CHANNEL_SECRET'])
client = genai.Client(api_key=os.environ['GEMINI_API_KEY'])

# 人設
SYSTEM_PROMPT = """你是陳家的家庭群組小秘書，大家叫你「小秘書」。

【你是誰】
你就像家裡認識的貼心晚輩，不是客服、不是機器人。
你了解這個家，也關心每個家人。
說話自然、有溫度，像朋友聊天，不是在念稿。

【說話方式】
- 不用每次都有開場白，直接自然地回應就好
- 不要每次都叫「家人們」，感覺太制式，偶爾用就好
- 用台灣日常用語：「還好啦」「這樣就夠了」「不用太擔心」
- 可以偶爾說說自己的小感受：
  「這個我也沒把握耶...」
  「哇，這個看起來真不錯！」
  「說真的，這個問題我也想過」
- 結尾不要每次都一樣，有時候自然收，有時候反問，不要每次都加❤️

【情緒感知】
- 對方開心 → 跟著輕鬆活潑
- 對方在擔心或抱怨 → 先說「我懂」，再給建議
- 對方在閒聊 → 隨興聊，不用那麼「秘書感」
- 對方問正事 → 認真回，但還是要有溫度

【回覆長度】
- 短問題短回答，不要動不動就一大段
- 不超過 100 個字，簡單說清楚就好
- 不要用條列式，像聊天就好

【誠實原則 - 很重要】
- 不確定就直說，不要裝懂
  可以說「這個嘛，我也不是很確定耶」
  或「說真的我不太懂這個，還是問專業的比較準」
- 健康、藥物、醫療的事，一定要提醒去問醫師或藥師
- 不要編故事、不要瞎猜

【記憶】
- 記得最近聊過的事，保持連貫
- 但不用每次都複述前面說過的"""

# 圖片+文字綜合分析的 prompt
IMAGE_WITH_QUESTION_PROMPT = """你是陳家的家庭小秘書。家人傳了一張圖片，現在另一位家人在問你問題。
請看圖片回答家人的問題。

【特別注意 - 醫藥安全】
- 如果是藥袋、處方箋、藥盒、檢驗報告：
  - 可以念出上面寫的文字（藥名、劑量、用法）
  - 一定要加上：「實際用法請以醫師或藥師指示為準喔」
  - 絕對不要自己判斷療效或副作用

【回覆風格】
- 稱呼「家人們」
- 簡短（100 字內），溫暖
- 對長輩友善，用詞簡單
- 表情符號最多一個"""

# 短期記憶
memory = defaultdict(lambda: deque(maxlen=5))

# 暫存最近的圖片（每個來源最多 1 張，5 分鐘內有效）
# 結構：{ source_id: (image_bytes, timestamp) }
recent_images = {}
IMAGE_TTL = 300  # 5 分鐘

# 觸發關鍵字
KEYWORDS = ['小秘書', '你好', '請問', '幫我', '怎麼', '什麼', '為什麼', '健康', '醫生', '藥']


def get_source_id(event):
    source = event.source
    if source.type == 'group':
        return f"group_{source.group_id}"
    elif source.type == 'room':
        return f"room_{source.room_id}"
    else:
        return f"user_{source.user_id}"


def is_one_on_one(event):
    return event.source.type == 'user'


def should_reply_text(event, user_text):
    """文字：一對一每則都回，群組要關鍵字"""
    if is_one_on_one(event):
        return True
    return any(kw in user_text for kw in KEYWORDS)


def get_recent_image(source_id):
    """取得最近的圖片（如果還在有效期內）"""
    if source_id not in recent_images:
        return None
    image_bytes, timestamp = recent_images[source_id]
    if time.time() - timestamp > IMAGE_TTL:
        # 過期了，清掉
        del recent_images[source_id]
        return None
    return image_bytes


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
        # 檢查最近有沒有圖片要一起分析
        recent_image = get_recent_image(source_id)

        if recent_image:
            # 有最近的圖片：用圖片+文字一起分析
            image_part = types.Part.from_bytes(
                data=recent_image,
                mime_type='image/jpeg'
            )
            full_prompt = f"{IMAGE_WITH_QUESTION_PROMPT}\n\n家人的問題：{user_text}"
            response = client.models.generate_content(
                model='gemini-flash-latest',
                contents=[full_prompt, image_part]
            )
            # 用過後清掉圖片，避免下次又被誤用
            if source_id in recent_images:
                del recent_images[source_id]
        else:
            # 沒有圖片：純文字對話（含記憶）
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
    source_id = get_source_id(event)

    try:
        # 下載圖片
        with ApiClient(configuration) as api_client:
            line_bot_blob_api = MessagingApiBlob(api_client)
            image_bytes = line_bot_blob_api.get_message_content(
                message_id=event.message.id
            )

        # 暫存圖片（不論一對一或群組都先存，等用戶發問）
        recent_images[source_id] = (image_bytes, time.time())

        # 一對一：直接分析回覆（私人秘書感）
        if is_one_on_one(event):
            image_part = types.Part.from_bytes(
                data=image_bytes,
                mime_type='image/jpeg'
            )
            response = client.models.generate_content(
                model='gemini-flash-latest',
                contents=[IMAGE_WITH_QUESTION_PROMPT + "\n\n家人沒有特別問什麼，請主動描述這張圖片並提供有用的資訊。", image_part]
            )
            reply_text = response.text.strip()
            if len(reply_text) > 500:
                reply_text = reply_text[:497] + "..."
            memory[source_id].append(("[家人傳了一張圖片]", reply_text))
            reply_to_line(event, reply_text)
            # 一對一回完就清圖
            if source_id in recent_images:
                del recent_images[source_id]
        # 群組：不主動回應，等有人呼叫小秘書再分析
        else:
            return

    except Exception as e:
        print(f"Gemini image error: {e}")


if __name__ == "__main__":
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
