# 📋 LINE 家庭機器人「我們這一家的小秘書」

## 🎯 專案目的
為家族 LINE 群組打造的 AI 小秘書，使用 Google Gemini 自動回覆家人問題，個性溫和、親切、尊重長輩。

---

## 🔑 重要資訊與資產

**LINE Bot**
- Bot 名稱：我們這一家的小秘書
- Bot ID：@555arjiq
- LINE Channel ID：2009930837
- Provider：陳思伶

**程式碼與部署**
- GitHub Repo：slynchen4040/line-family-bot（Public）
- 本地資料夾：~/line-family-bot
- Railway 專案名稱：romantic-healing
- Railway 服務 URL：https://web-production-392a6.up.railway.app
- Webhook URL：https://web-production-392a6.up.railway.app/callback

**Google Gemini**
- Google AI Studio 專案：LINE-Family-Bot（gen-lang-client-0061681573）
- 使用模型：gemini-flash-latest（免費額度）
- SDK 套件：google-genai（新版）

**Railway 環境變數（已設定）**
- LINE_CHANNEL_ACCESS_TOKEN
- LINE_CHANNEL_SECRET
- GEMINI_API_KEY

> ⚠️ Token、Secret、API key 不要外流，不要 commit 到 GitHub。

---

## 🛠 技術架構
**檔案結構**
- main.py：Flask + LINE webhook + Gemini 整合
- requirements.txt：flask, line-bot-sdk, google-genai
- Procfile：web: python main.py

---

## 🤖 機器人行為設定

**觸發關鍵字**（在 main.py 的 KEYWORDS 列表）：
小秘書、你好、請問、幫我、怎麼、什麼、為什麼、健康、醫生、藥

**回覆風格**（在 main.py 的 system_prompt）：
- 溫和、親切、尊重的小秘書角色
- 回覆控制在 100 字以內
- 不會在群組裡每句都搶話，只在被叫到或有關鍵字時回應

---

## 🔄 修改流程（標準 SOP）

1. 在 Terminal 進入資料夾：`cd ~/line-family-bot`
2. 編輯 main.py（用 nano、VS Code 等）
3. 推送到 GitHub：
4. Railway 偵測到 GitHub 更新後會自動重新部署（約 1-2 分鐘）
5. 部署完成後直接到 LINE 測試

---

## 👤 使用者背景
- 系統：Mac
- 慣用語言：繁體中文
- 有基本 Terminal 經驗
- GitHub 帳號：slynchen4040
- 使用 Personal Access Token (PAT) 推送（已設定在 git remote URL）

---

## 📝 已踩過的雷（避免重複）

1. **不要用 gemini-2.0-flash**：免費額度 limit=0
2. **不要用 gemini-1.5-flash**：新版 google-genai SDK 在 v1beta API 找不到
3. **要用 gemini-flash-latest** ✅ 穩定可用
4. **不要用舊套件 google-generativeai**：已 deprecated，改用 google-genai
5. **記得關閉 LINE 自動回覆**（LINE Official Account Manager → 回應設定）
6. **環境變數修改後要 Deploy 套用**（Railway 不會自動套用）

---

## 🚀 接下來可以做的事

- 把小秘書加入家族 LINE 群組
- 調整關鍵字、回覆個性
- 增加功能（例如：天氣、提醒、行事曆）
- 接其他資料來源（Notion、Google Sheets 等）

---

## 💬 與 Claude 接續對話時這樣說

> 「我有個 LINE 家庭機器人專案『我們這一家的小秘書』，已部署在 Railway，使用 Gemini API。我想調整 [XXX 功能]，幫我看看怎麼改。」

或直接貼上這份 README，Claude 就能立刻接手 ✅
