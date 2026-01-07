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

# [新增] 是否上傳 AI Log (True=開啟, False=關閉)
ENABLE_AI_LOG = True

# [新增] RSI 超買/超賣閥值
RSI_OVERBOUGHT = 70 
RSI_PERIOD = 14