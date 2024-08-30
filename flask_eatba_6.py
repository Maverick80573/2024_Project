import random  # 用於隨機選擇圖片
from flask import Flask, request, abort, url_for
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi, ReplyMessageRequest,
    TextMessage, TemplateMessage, QuickReply, QuickReplyItem,
    CarouselTemplate, CarouselColumn, ButtonsTemplate, 
    PostbackAction, MessageAction, URIAction
)
from linebot.v3.webhooks import MessageEvent, FollowEvent, TextMessageContent, PostbackEvent
import pandas as pd
from urllib.parse import parse_qsl, quote
import logging
import os
from handle_keys import get_secret_and_token
from create_linebot_messages_sample import *

app = Flask(__name__)
keys = get_secret_and_token()
handler = WebhookHandler(keys['LINEBOT_SECRET_KEY'])
configuration = Configuration(access_token=keys['LINEBOT_ACCESS_TOKEN'])

# 靜態圖片資料夾路徑
IMAGE_FOLDER = 'static/images'

# 載入餐廳資料，包含圖片檔名
rest_dict = {meal: pd.read_csv(f'taichungeatba/{meal}.csv').dropna(axis=1).groupby('區域')
             for meal in ['breakfast_rest', 'lunch_rest', 'dinner_rest']}

# 儲存使用者選擇的餐廳推薦資料
rest_recommand_memory = dict()

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        app.logger.info("Invalid signature.")
        abort(400)

    return 'OK'

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_id = event.source.user_id
    user_message = event.message.text

    known_commands = ["連絡電話", "餐廳評價","sample"]
    if any(cmd in user_message for cmd in known_commands):
        return  # 不回覆引導訊息，只處理按鈕的訊息

    response = process_message(user_id, user_message)

    with ApiClient(configuration) as api_client:
        MessagingApi(api_client).reply_message_with_http_info(
            ReplyMessageRequest(reply_token=event.reply_token, messages=[response])
        )

def process_message(user_id, user_message):
    if "sample" in user_message:
        return handle_sample(user_message)
    elif '美食推薦' in user_message:
        return handle_choose_time()
    elif user_message.startswith('#'):
        return handle_hashtag_messages(user_id, user_message)
    else:
        return TextMessage(text="想吃什麼，就大聲說出來吧！輸入『美食推薦』，我來滿足你的味蕾！")

def handle_hashtag_messages(user_id, user_message):
    if user_message.endswith('餐'):
        return handle_choose_section(user_id, user_message)
    elif user_message.endswith('區'):
        section_name = user_message[1:]
        return handle_rests_recommand(user_id, section_name)

def handle_choose_time():
    actions = [
        MessageAction(text='#文青早餐', label='享用文青早點'),
        MessageAction(text='#在地午餐', label='品嘗在地美食'),
        MessageAction(text='#高檔晚餐', label='暢享高檔餐廳')
    ]
    response = ButtonsTemplate(
        thumbnail_image_url='https://i.imgur.com/b9oaYpu.jpeg',
        title='歡迎使用!!',
        text='請選擇要推薦的風格餐廳。',
        actions=actions
    )
    return TemplateMessage(altText="TemplateMessage", template=response)

def handle_choose_section(user_id, time_message):
    meal_dict = {'#文青早餐': 'breakfast_rest', '#在地午餐': 'lunch_rest', '#高檔晚餐': 'dinner_rest'}
    meal_type = meal_dict.get(time_message)
    
    if meal_type:
        rest_recommand_memory[user_id] = rest_dict[meal_type]
        rest_recommand_memory[user_id].meal_type = meal_type  # 儲存餐廳類型
        sections = rest_recommand_memory[user_id].groups.keys()
        quick_reply_items = [QuickReplyItem(action=MessageAction(text=f'#{sec}', label=f'{sec}')) for sec in sections]
        return TextMessage(text="請選擇你的所在區域~", quickReply=QuickReply(items=quick_reply_items))

def handle_rests_recommand(user_id, section_name):
    def create_rest_col(name, opentime, phone, section, address, comment, image_file_folder):
        address = address if address else '台中市政府'  # 如果沒有地址，使用一個預設位置
        phone = phone if phone else '這是電話'
        comment = comment if comment else '這是評論'

        # 建立本地圖片 URL，隨機選擇一張圖片
        folder_path = os.path.join(IMAGE_FOLDER, image_file_folder)
        if image_file_folder and os.path.exists(folder_path):
            # 列出資料夾內的圖片檔案
            image_files = [f for f in os.listdir(folder_path) if os.path.isfile(os.path.join(folder_path, f))]
            if image_files:  # 確認資料夾內有圖片
                image_file = random.choice(image_files)  # 隨機選擇圖片
                image_url = url_for('static', filename=f'images/{image_file_folder}/{image_file}', _external=True, _scheme='https')
            else:
                image_url = 'https://i.imgur.com/97LucO0.jpg'  # 若資料夾內無圖片，使用預設圖片
        else:
            image_url = 'https://i.imgur.com/97LucO0.jpg'  # 預設圖片 URL

        # 記錄日誌以檢查生成的圖片 URL
        app.logger.info(f"Generated Image URL for {name}: {image_url}")
        
        # 使用 URIAction 讓地址點擊時打開 Google 地圖，地址需要進行 URL 編碼
        encoded_address = quote(address)
        map_url = f"https://www.google.com/maps/search/?api=1&query={encoded_address}"
        text_for_postback = f"comment={name}の餐廳評價：{comment}"
        text_for_phone = f"comment={name}の聯絡電話： {phone}"
        
        return CarouselColumn(
            text=opentime, title=name, thumbnail_image_url=image_url,
            actions=[
                URIAction(label='餐廳地址', uri=map_url),
                PostbackAction(
                    label='聯絡電話',
                    displayText=f'{name}の聯絡電話',
                    data=text_for_phone
                ),
                PostbackAction(
                    label='餐廳評價',
                    displayText=f'{name}の餐廳評價',
                    data=text_for_postback
                ),
            ]
        )

    group = rest_recommand_memory[user_id].get_group(section_name)
    samples = group.sample(min(len(group), 3))

    columns = []
    for rest in samples.values:
        # 根據 CSV 檔案中的列數調整解包數量
        name, opentime, phone, section, address, comment = rest[:6]
        image_file_folder = f'{section}_{name}'
        columns.append(create_rest_col(name, opentime, phone, section, address, comment, image_file_folder))
    
    # 確認生成的 columns 非空，否則返回錯誤消息
    if not columns:
        return TextMessage(text="找不到餐廳資料，請稍後再試！")
    
    return TemplateMessage(altText="TemplateMessage", template=CarouselTemplate(columns=columns))

@handler.add(FollowEvent)
def handle_follow(event):
    welcome_msg = "嗨！歡迎加入台中美食小幫手！想找美食嗎？輸入「美食推薦」就能開始你的美食探索之旅囉！"
    with ApiClient(configuration) as api_client:
        MessagingApi(api_client).reply_message_with_http_info(
            ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=welcome_msg)])
        )

@handler.add(PostbackEvent) 
def handle_postback(event):
    ts = event.postback.data
    postback_data = {k:v for k,v in parse_qsl(ts)}
    response = postback_data.get('comment', "Get PostBack Event!")  # 取得評價
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=response)]
            )
        )

def handle_sample(user_message):
    if "按鈕sample" in user_message:
        return create_buttons_template()
    elif "輪播sample" in user_message:
        return create_carousel_template()
    elif "確認sample" in user_message:
        return create_check_template()
    else:
        return create_quick_reply()

if __name__ == "__main__":
    # 設置日誌級別
    logging.basicConfig(level=logging.INFO)
    app.run(debug=True)