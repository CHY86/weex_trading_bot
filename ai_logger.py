import logging
import json
import os
from logging.handlers import RotatingFileHandler
from datetime import datetime

# 確保 logs 資料夾存在
LOG_DIR = "logs"
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

# 設定 Log 檔案路徑
LOG_FILE_PATH = os.path.join(LOG_DIR, "ai_history.jsonl")

# 建立專屬的 Logger
logger = logging.getLogger("AI_Recorder")
logger.setLevel(logging.INFO)

# 設定輪替機制 (Rotating)
# maxBytes=10*1024*1024 (10MB), backupCount=5 (保留最近 5 個檔)
handler = RotatingFileHandler(LOG_FILE_PATH, maxBytes=10*1024*1024, backupCount=50, encoding='utf-8')

# 設定格式 (這裡我們只存純訊息，因為訊息本身就是 JSON 字串)
formatter = logging.Formatter('%(message)s')
handler.setFormatter(formatter)

logger.addHandler(handler)

def save_local_log(stage, model, input_data, output_data, explanation, order_id=None):
    """
    將 AI 紀錄寫入本地 JSONL 檔案
    """
    record = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "stage": stage,
        "model": model,
        "input": input_data,
        "output": output_data,
        "explanation": explanation,
        "order_id": order_id
    }
    
    # 轉成 JSON 字串並寫入一行
    try:
        json_line = json.dumps(record, ensure_ascii=False)
        logger.info(json_line)
    except Exception as e:
        print(f"❌ 本地 Log 寫入失敗: {e}")