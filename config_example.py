# config_example.py
API_KEY = "YOUR_API_KEY_HERE"
SECRET_KEY = "YOUR_SECRET_KEY_HERE"
PASSPHRASE = "YOUR_PASSPHRASE_HERE"
# ...其他設定保留

# WEEX 合約 API 地址
REST_URL = "https://api-contract.weex.com"
WS_URL = "wss://ws-contract.weex.com/v2/ws/public"  # 公共行情流

# 交易對設定
SYMBOL = "cmt_btcusdt"  # 你的 AI 要交易的幣種

# 策略使用的 K 線時間維度
# 可選值: MINUTE_1, MINUTE_5, MINUTE_15, MINUTE_30, HOUR_1, HOUR_4, HOUR_12
STRATEGY_INTERVAL = "MINUTE_5"

# RSI 設定
RSI_PERIOD = 14       # 計算週期 (標準為14)
RSI_OVERBOUGHT = 70   # 超買閥值 (超過此值做空)

# 布林通道設定
BB_LENGTH = 20
BB_STD = 2.0

# 風控設定
COOLDOWN_HOURS = 2    # 交易冷卻時間(小時)

# 系統設定
ENABLE_AI_LOG = True  # 是否上傳 AI Log

#  OpenAI 設定 ---
OPENAI_API_KEY = "您的_OPENAI_API_KEY"  # 請填入您的 sk-....
OPENAI_MODEL = "gpt-4.1-mini-2025-04-14" # 使用 Group 2 的高額度模型

# AI 
AI_CONFIDENCE_THRESHOLD = 0.6
AI_COOLDOWN_SECONDS = 60
AI_TEMPERATURE = 0.4  # 控制回應的隨機性 (0.0 - 1.0
AI_MAX_TOKENS = 400   # 回應的最大 token 數量

# 風控設定 (保留)
MAX_OPEN_ORDERS = 10
MAX_POSITIONS = 1
MAX_POSITION_SIZE = 1  # 最大持倉數量 (例如最多持有 0.1 BTC)
DEFAULT_ORDER_SIZE = "0.05"  # 預設下單數量
ORDER_SIZE_BY_STRATEGY = {
    "range_reversion": "0.04",
    "breakout_momentum_ai": "0.05",
}