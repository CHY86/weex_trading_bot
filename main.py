import time
import config
from exchange_client import WeexClient
from market_stream import MarketStream

# 初始化交易所客戶端
client = WeexClient()

# --- 你的 AI 策略邏輯 ---
def ai_strategy(current_price):
    """
    這是核心策略函數。
    每當 WebSocket 收到最新價格，這裡就會被觸發一次。
    """
    print(f"📊 [AI 監控中] 當前價格: {current_price}")
    
    # === 範例策略：簡單的價格突破策略 ===
    # 假設我們在測試，當價格 > 100000 時開空，< 90000 時開多 (舉例)
    # 實戰中請替換成你的 AI 模型預測結果
    
    # 範例：查詢目前帳戶餘額 (不要每次都查，會太慢，建議設間隔)
    assets = client.get_account_assets()
    print(assets)

    # 範例：觸發下單 (請小心使用，這是真實下單！)
    # client.place_order(side=1, size="0.001", price=str(current_price - 10))

# --- 主程式進入點 ---
if __name__ == "__main__":
    print("🤖 AI 交易機器人啟動中...")
    
    # 1. 測試 API 連線
    server_time = client.get_server_time()
    if server_time:
        print(f"✅ API 連線正常: {server_time}")
    else:
        print("❌ API 連線失敗，請檢查 Config")
        exit()

    # 2. 啟動 WebSocket 監聽行情
    # 注意：我們把 ai_strategy 函數傳進去，讓 WebSocket 有資料時通知它
    stream = MarketStream(symbol=config.SYMBOL, on_price_update_callback=ai_strategy)
    stream.start()

    # 3. 保持主程式運行 (因為 WebSocket 是在背景執行緒)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("🛑 機器人停止運行")