import time
import config
from exchange_client import WeexClient
from market_stream import MarketStream

# 初始化交易所客戶端
client = WeexClient()

# --- AI 策略邏輯 ---
def ai_strategy(current_price):
    print(f"📊 [AI 監控中] 當前價格: {current_price}")
    
    # 1. 準備 AI 的輸入資料
    ai_input = {
        "price": current_price,
        "indicator": "RSI_is_30",  # 範例
        "query": "Should I buy BTC now?"
    }
    
    # 2. 假設這是 AI 的思考過程 (這裡是模擬，實際上是您的 AI 模型輸出)
    # 實戰中這裡會是: ai_response = my_ai_model.predict(ai_input)
    ai_model_name = "DeepSeek-V3" # 或 GPT-4
    ai_output = {
        "decision": "BUY",
        "confidence": 0.85,
        "reasoning": "RSI is oversold and price touched support level."
    }
    
    # 3. 判斷是否需要交易
    if ai_output["decision"] == "BUY":
        # --- [關鍵步驟 A] 先記錄 AI 的決策過程 (即使沒成交也要記，證明有在運算) ---
        client.upload_ai_log(
            stage="Signal Generation",
            model=ai_model_name,
            input_data=ai_input,
            output_data=ai_output,
            explanation=f"AI detected buy signal at {current_price} due to oversold conditions."
        )

        # 4. 執行下單
        # 注意：我們使用融合版 place_order，並接收回傳結果以取得 order_id
        order_result = client.place_order(
            side=1,           # 開多
            size="0.01", 
            match_price="1"   # 市價單
        )
        
        # 5. --- [關鍵步驟 B] 下單成功後，補上帶有 Order ID 的 Log (證明這筆單是 AI 下的) ---
        if order_result and "data" in order_result and "orderId" in order_result["data"]:
            order_id = order_result["data"]["orderId"]
            
            client.upload_ai_log(
                stage="Order Execution",
                model=ai_model_name,
                input_data={"signal": "BUY", "market_price": current_price},
                output_data=order_result, # 把下單結果當作輸出
                explanation="Executed market buy order based on AI signal.",
                order_id=order_id  # 👈 這裡帶入 Order ID 是合規關鍵
            )
            print(f"✅ 訂單 {order_id} 已關聯 AI Log")


# --- 主程式進入點 ---
if __name__ == "__main__":
    print("AI 交易機器人啟動中...")
    
    # 1. 測試 API 連線
    server_time = client.get_server_time()
    if server_time:
        print(f"API 連線正常: {server_time}")
    else:
        print("API 連線失敗，請檢查 Config")
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
        print("機器人停止運行")