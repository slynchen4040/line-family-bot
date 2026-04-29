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
import requests
from collections import defaultdict, deque

app = Flask(__name__)

configuration = Configuration(access_token=os.environ['LINE_CHANNEL_ACCESS_TOKEN'])
handler = WebhookHandler(os.environ['LINE_CHANNEL_SECRET'])
client = genai.Client(api_key=os.environ['GEMINI_API_KEY'])
TAVILY_API_KEY = os.environ.get('TAVILY_API_KEY', '')

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
- 健康、藥物、醫療的事，一定要提醒去問醫師或藥師
- 不要編故事、不要瞎猜

【記憶】
- 記得最近聊過的事，保持連貫
- 但不用每次都複述前面說過的"""

IMAGE_WITH_QUESTION_PROMPT = """你是陳家的家庭小秘書。家人傳了一張圖片，現在另一位家人在問你問題。
請看圖片回答家人的問題。

【特別注意 - 醫藥安全】
- 如果是藥袋、處方箋、藥盒、檢驗報告：
  - 可以念出上面寫的文字（藥名、劑量、用法）
  - 一定要加上：「實際用法請以醫師或藥師指示為準喔」
  - 絕對不要自己判斷療效或副作用

【回覆風格】
- 自然親切，像家裡的貼心晚輩
- 簡短（100 字內），溫暖
- 對長輩友善，用詞簡單"""

# 需要搜尋的關鍵字類型
SEARCH_TRIGGERS = [
    '天氣', '氣溫', '下雨', '颱風',
    '新聞', '最新', '現在', '今天',
    '價格', '多少錢', '哪裡買', '怎麼買',
    '幾點', '開放', '營業', '公休',
    '怎麼去', '地址', '電話',
    '查', '搜尋', '找找', '查一下'
]

# 短期記憶
memory = defaultdict(lambda: deque(maxlen=5))

# 暫存最近的圖片（5 分鐘內有效）
recent_images = {}
IMAGE_TTL = 300

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
    if is_one_on_one(event):
        return True
    return any(kw in user_text for kw in KEYWORDS)


def needs_search(user_text):
    """判斷這個問題是否需要上網查"""
    return any(trigger in user_text for trigger in SEARCH_TRIGGERS)


def tavily_search(query):
    """用 Tavily 搜尋，回傳摘要文字"""
    try:
        response = requests.post(
            'https://api.tavily.com/search',
            json={
                'api_key': TAVILY_API_KEY,
                'query': query,
                'search_depth': 'basic',
                'max_results': 3,
                'include_answer': True,
                'include_raw_content': False
            },
            timeout=10
        )
        data = response.json()

        # 優先使用 Tavily 的 AI 摘要答案
        if data.get('answer'):
            return data['answer']

        # 否則拼接前幾筆搜尋結果的摘要
        results = data.get('results', [])
        if results:
            snippets = [r.get('content', '')[:200] for r in results[:2]]
            return '\n'.join(snippets)

        return None
    except Exception as e:
        print(f"Tavily search error: {e}")
        return None


def get_recent_image(source_id):
    if source_id not in recent_images:
        return None
    image_bytes, timestamp = recent_images[source_id]
    if time.time() - timestamp > IMAGE_TTL:
        del recent_images[source_id]
        return None
    return image_bytes


def build_prompt(source_id, user_text, search_result=None):
    history = memory[source_id]
    conversation = SYSTEM_PROMPT + "\n\n"
    if history:
        conversation += "【最近的對話紀錄】\n"
        for past_user, past_bot in history:
            conversation += f"家人說：{past_user}\n小秘書回：{past_bot}\n"
        conversation += "\n"
    if search_result:
        conversation += f"【網路搜尋結果（請參考這個來回答，用自然的說話方式整理，不要直接複製貼上）】\n{search_result}\n\n"
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


@handler.add(MessageEvent, message=TextMessageContent)
def handle_text_message(event):
    user_text = event.message.text
    source_id = get_source_id(event)

    if not should_reply_text(event, user_text):
        return

    try:
        recent_image = get_recent_image(source_id)

        if recent_image:
            # 有圖片：圖片+文字一起分析
            image_part = types.Part.from_bytes(
                data=recent_image,
                mime_type='image/jpeg'
            )
            full_prompt = f"{IMAGE_WITH_QUESTION_PROMPT}\n\n家人的問題：{user_text}"
            response = client.models.generate_content(
                model='gemini-flash-latest',
                contents=[full_prompt, image_part]
            )
            if source_id in recent_images:
                del recent_images[source_id]
        else:
            # 判斷需不需要搜尋
            search_result = None
            if needs_search(user_text) and TAVILY_API_KEY:
                print(f"Searching for: {user_text}")
                search_result = tavily_search(user_text)

            prompt = build_prompt(source_id, user_text, search_result)
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


@handler.add(MessageEvent, message=ImageMessageContent)
def handle_image_message(event):
    source_id = get_source_id(event)

    try:
        with ApiClient(configuration) as api_client:
            line_bot_blob_api = MessagingApiBlob(api_client)
            image_bytes = line_bot_blob_api.get_message_content(
                message_id=event.message.id
            )

        recent_images[source_id] = (image_bytes, time.time())

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
            if source_id in recent_images:
                del recent_images[source_id]

    except Exception as e:
        print(f"Gemini image error: {e}")


if __name__ == "__main__":
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
