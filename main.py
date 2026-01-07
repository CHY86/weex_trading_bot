import time
import pandas as pd
import pandas_ta as ta  # 需要 pip install pandas_ta
from datetime import datetime, timedelta

from exchange_client import WeexClient
from market_stream import MarketStream
import config
from ai_logger import save_local_log

# --- 參數設定 (方案 B) ---
SYMBOL = config.SYMBOL
INTERVALS = ["MINUTE_1", "HOUR_4"]  # 同時監聽 1分 (即時) 和 4小時 (趨勢)
RSI_PERIOD = 14
BB_LENGTH = 20
BB_STD = 2.0
COOLDOWN_HOURS = 4  # 交易冷卻時間
last_heartbeat_time = 0 # 上次心跳時間
last_refresh_hour = -1 # 上次更新的小時

class StrategyManager:
    def __init__(self, client):
        self.client = client
        self.history_4h = pd.DataFrame()
        self.last_trade_time = datetime.min
        self.prev_4h_high = 0.0
        self.prev_4h_low = 0.0
        
        # 初始化數據
        self.refresh_history()

    def refresh_history(self):
        print("🔄 正在初始化/更新 4H 歷史數據...")
        
        # 計算當前時間的 Unix 毫秒 (作為 endTime)
        now_ms = int(time.time() * 1000)
        
        # 呼叫我們剛寫好的 get_history_candles
        # 注意: WebSocket 用的 "HOUR_4" 要轉成 API 用的 "4h"
        raw_klines = self.client.get_history_candles(
            symbol=SYMBOL, 
            granularity="4h",  # 根據文件，這裡要傳 "4h"
            end_time=now_ms,   # 截止到現在
            limit=100          # 根據文件，最大 100
        )
        
        if not raw_klines:
            print("⚠️ 無法獲取 K 線數據")
            return

        # 轉為 DataFrame 處理 (根據文件回傳格式 index[0]~index[6])
        # [time, open, high, low, close, volume, quote_vol]
        df = pd.DataFrame(raw_klines, columns=['time', 'open', 'high', 'low', 'close', 'vol', 'quote_vol'])
        
        # 轉換型別
        df['close'] = df['close'].astype(float)
        df['high'] = df['high'].astype(float)
        df['low'] = df['low'].astype(float)
        
        # 排序 (API 有時回傳是倒序或正序，通常是時間遞增，但保險起見排一下)
        df = df.sort_values('time').reset_index(drop=True)
        
        # 計算指標
        df['RSI'] = ta.rsi(df['close'], length=RSI_PERIOD)
        bb = ta.bbands(df['close'], length=BB_LENGTH, std=BB_STD)
        df = pd.concat([df, bb], axis=1) # 合併指標
        
        # 儲存
        self.history_4h = df
        
        # 紀錄關鍵價位 (上一個「已完成」的 4H K線)
        # Assuming the last one in list is current (unclosed), so we take -2
        if len(df) >= 2:
            last_completed = df.iloc[-2]
            self.prev_4h_high = last_completed['high']
            self.prev_4h_low = last_completed['low']
            print(f"📊 策略基準更新: 上一根 4H 高點={self.prev_4h_high}, RSI={last_completed['RSI']:.2f}")

    def on_tick(self, interval, current_price):
        """處理 WebSocket 進來的每一筆價格"""
        
        # 我們主要用 MINUTE_1 的即時價格來觸發判斷，但參考 HOUR_4 的架構
        if interval != "MINUTE_1": 
            return # 4H 的推送可能很久才一次，我們用 1M 來即時監控
            
        now = datetime.now()
        
        # 0. 冷卻期檢查 (避免過度操作)
        if (now - self.last_trade_time).total_seconds() < COOLDOWN_HOURS * 3600:
            return 

        # 1. 取得最新指標數值 (使用歷史數據的最後一筆作為估算)
        if self.history_4h.empty:
            return
        
        latest_metrics = self.history_4h.iloc[-1]
        bb_upper = latest_metrics.get(f'BBU_{BB_LENGTH}_{BB_STD}', 999999)
        bb_mid = latest_metrics.get(f'BBM_{BB_LENGTH}_{BB_STD}', 0)
        rsi_val = latest_metrics.get('RSI', 50)

        # --- 策略邏輯 (方案 B) ---
        
        # 條件 A: 價格突破上一個 4H 高點 (假突破潛力區)
        is_breakout = current_price > self.prev_4h_high
        
        # 條件 B: 震盪過濾 (RSI 超買 或 觸及布林上軌 -> 暗示回調機率大)
        is_overextended = (rsi_val > 70) or (current_price > bb_upper)
        
        # 觸發做空 (Mean Reversion)
        if is_breakout and is_overextended:
            self.execute_trade_logic(current_price, "SHORT", "Volatility Breakout + Overbought")

    def execute_trade_logic(self, price, direction, reason):
        print(f"⚡ 觸發交易訊號: {direction} @ {price} | 原因: {reason}")
        
        # 1. 記錄 AI Log (Signal Generation)
        self.client.upload_ai_log(
            stage="Signal Generation",
            model="PlanB_Algo_v1",
            input_data={"price": price, "prev_4h_high": self.prev_4h_high},
            output_data={"decision": direction},
            explanation=f"Detected breakout above {self.prev_4h_high} with overextended indicators."
        )
        
        # 2. 執行下單 (帶止損止盈)
        # 止盈: 震盪區域往上一點 (這裡設為進場價回調 1.5% 或布林中軌)
        tp_price = int(price * 0.985) 
        sl_price = int(price * 1.02)  # 止損 2%

        try:
            order = self.client.place_order(
                side=2, # 開空
                size="0.01", # 請根據資金管理調整
                match_price="1", # 市價進場
                preset_take_profit=str(tp_price),
                preset_stop_loss=str(sl_price),
                margin_mode=1 # 全倉
            )
            
            if order and 'data' in order and 'orderId' in order['data']:
                self.last_trade_time = datetime.now()
                print(f"✅ 下單成功! OrderID: {order['data']['orderId']}")
                
                # 3. 記錄 AI Log (Execution)
                self.client.upload_ai_log(
                    stage="Execution",
                    model="PlanB_Algo_v1",
                    input_data={"order": "MARKET SHORT"},
                    output_data=order,
                    explanation="Executed short per Plan B logic.",
                    order_id=order['data']['orderId']
                )
        except Exception as e:
            print(f"❌ 下單失敗: {e}")

# --- 主程式 ---
if __name__ == "__main__":
    client = WeexClient()
    strategy = StrategyManager(client)
    
    # 定期更新歷史數據的線程 (簡單用 time check 模擬)
    last_update_time = time.time()
    print(client)
    def callback_wrapper(interval, price):
        global last_update_time, last_refresh_hour, last_heartbeat_time
    
        # 1. 傳遞給策略 (保持原樣)
        strategy.on_tick(interval, price)
        
        # --- [新增] 每 30 秒印一次心跳，證明機器人活著 ---
        if time.time() - last_heartbeat_time > 30:
            print(f"💓 [系統執行中] 監控中... {interval} 最新價格: {price} | RSI: {strategy.history_4h.iloc[-1]['RSI']:.2f} (上個4H)")
            last_heartbeat_time = time.time()
        # ------------------------------------------------
        
        # 2. [優化] 智慧更新邏輯
        current_time = datetime.now()
        current_hour = current_time.hour
        
        # 條件 A: 剛跨過 4 小時的整點 (例如 00:00, 04:00, 08:00...)
        # 這樣可以確保 K 線一收盤，我們馬上更新指標
        is_4h_close = (current_hour % 4 == 0) and (current_hour != last_refresh_hour)
        
        # 條件 B: 保護機制，每 15 分鐘還是更新一次 (避免 WebSocket 漏失或其他異常)
        is_periodic_check = (time.time() - last_update_time > 900)

        if is_4h_close or is_periodic_check:
            print(f"🔄 觸發數據更新: 4H換線={is_4h_close}, 定時檢查={is_periodic_check}")
            strategy.refresh_history()
            
            last_update_time = time.time()
            if is_4h_close:
                last_refresh_hour = current_hour

    # 啟動 WebSocket (監聽多個週期)
    stream = MarketStream(SYMBOL, INTERVALS, callback_wrapper)
    stream.start()

    while True:
        time.sleep(1)