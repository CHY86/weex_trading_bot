import time
import pandas as pd
import pandas_ta as ta
from datetime import datetime, timedelta

from exchange_client import WeexClient
from market_stream import MarketStream
import config
from ai_logger import save_local_log

# --- [修改 1] 從 Config 讀取策略參數 ---
SYMBOL = config.SYMBOL
STRATEGY_INTERVAL = config.STRATEGY_INTERVAL  # e.g., "MINUTE_30"

# 始終訂閱 MINUTE_1 (監控用) + 策略設定的週期 (分析用)
INTERVALS = ["MINUTE_1", STRATEGY_INTERVAL] 

RSI_PERIOD = 14
BB_LENGTH = 20
BB_STD = 2.0
COOLDOWN_HOURS = 2 # 可以根據週期縮短冷卻時間

class StrategyManager:
    def __init__(self, client):
        self.client = client
        self.history_df = pd.DataFrame()
        self.last_trade_time = datetime.min
        self.prev_high = 0.0
        self.prev_low = 0.0
        
        # 初始化數據
        self.refresh_history()

    def refresh_history(self):
        """根據 Config 設定的週期抓取歷史數據"""
        print(f"🔄 正在更新 {STRATEGY_INTERVAL} 歷史數據...")
        
        # 呼叫 API (注意: 這裡會自動用 exchange_client 裡的 mapping 轉成 30m/1h/4h)
        # e.g. 抓取 100 根 K 線，對於 30分 K 來說是過去 50 小時，足夠算指標
        now_ms = int(time.time() * 1000)
        raw_klines = self.client.get_history_candles(
            symbol=SYMBOL, 
            granularity=self.client._map_interval(STRATEGY_INTERVAL), # 自動轉換
            end_time=now_ms,
            limit=100
        )
        
        if not raw_klines:
            print("⚠️ 無法獲取 K 線數據，等待下次更新")
            return

        # 整理數據
        df = pd.DataFrame(raw_klines, columns=['time', 'open', 'high', 'low', 'close', 'vol', 'quote_vol'])
        df['close'] = df['close'].astype(float)
        df['high'] = df['high'].astype(float)
        df['low'] = df['low'].astype(float)
        df = df.sort_values('time').reset_index(drop=True)
        
        # 計算指標
        df['RSI'] = ta.rsi(df['close'], length=RSI_PERIOD)
        bb = ta.bbands(df['close'], length=BB_LENGTH, std=BB_STD)
        df = pd.concat([df, bb], axis=1)
        
        self.history_df = df
        
        # 更新策略基準 (取上一根「已完成」的 K 線)
        if len(df) >= 2:
            last_completed = df.iloc[-2]
            self.prev_high = last_completed['high']
            self.prev_low = last_completed['low']
            rsi_val = last_completed['RSI']
            print(f"📊 [{STRATEGY_INTERVAL}] 策略基準: 前高={self.prev_high}, RSI={rsi_val:.2f}")

    def on_tick(self, interval, current_price):
        # 只在 1分鐘線來的時候做即時檢查 (反應最快)
        if interval != "MINUTE_1": 
            return
            
        now = datetime.now()
        
        # 冷卻期檢查
        if (now - self.last_trade_time).total_seconds() < COOLDOWN_HOURS * 3600:
            return 

        if self.history_df.empty:
            return
        
        # 取得最新指標 (來自歷史數據的預估)
        latest_metrics = self.history_df.iloc[-1]
        bb_upper = latest_metrics.get(f'BBU_{BB_LENGTH}_{BB_STD}', 999999)
        rsi_val = latest_metrics.get('RSI', 50)

        # --- 策略邏輯 ---
        # 1. 價格突破 Config 設定週期的前高
        is_breakout = current_price > self.prev_high
        
        # 2. 震盪過濾
        is_overextended = (rsi_val > 70) or (current_price > bb_upper)
        
        if is_breakout and is_overextended:
            self.execute_trade_logic(current_price, "SHORT", f"{STRATEGY_INTERVAL} Breakout")

    def execute_trade_logic(self, price, direction, reason):
        # ... (保持原有的下單邏輯) ...
        print(f"⚡ 觸發交易訊號: {direction} @ {price} | 原因: {reason}")
        # (略: 這裡放原本的 upload_ai_log 和 place_order 代碼)

# --- [修改 2] 智慧判斷換線邏輯 ---
def should_refresh_data(last_refresh_time):
    """
    根據 Config 的週期判斷是否該更新歷史資料
    支援: MINUTE_X, HOUR_X
    """
    now = datetime.now()
    minutes = now.minute
    hours = now.hour
    
    # 解析 Config (e.g., "MINUTE_30" -> type="MINUTE", val=30)
    parts = STRATEGY_INTERVAL.split('_')
    p_type = parts[0]
    p_val = int(parts[1])
    
    is_time_to_refresh = False
    
    if p_type == "MINUTE":
        # 如果是 30分K，則在 分鐘數 % 30 == 0 時更新 (e.g., 10:00, 10:30)
        if minutes % p_val == 0:
            is_time_to_refresh = True
    elif p_type == "HOUR":
        # 如果是 4小時K，則在 小時數 % 4 == 0 且 分鐘=0 時更新
        if hours % p_val == 0 and minutes == 0:
            is_time_to_refresh = True
            
    # 增加一個保護：距離上次更新至少要過 60 秒 (避免同一個整點重複更新)
    if is_time_to_refresh and (time.time() - last_refresh_time > 60):
        return True
        
    # 保底機制：超過 15 分鐘強制更新
    if time.time() - last_refresh_time > 900:
        return True
        
    return False

# --- 主程式 ---
if __name__ == "__main__":
    client = WeexClient()
    strategy = StrategyManager(client)
    
    last_update_time = time.time()
    last_heartbeat_time = 0

    def callback_wrapper(interval, price):
        global last_update_time, last_heartbeat_time
        
        # 1. 策略檢查
        strategy.on_tick(interval, price)
        
        # 2. 心跳顯示 (每 30 秒)
        if time.time() - last_heartbeat_time > 30:
            # 顯示當前策略採用的 RSI
            current_rsi = strategy.history_df.iloc[-1]['RSI'] if not strategy.history_df.empty else 0
            print(f"💓 [監控中] {STRATEGY_INTERVAL}策略 | 現價: {price} | RSI: {current_rsi:.2f}")
            last_heartbeat_time = time.time()

        # 3. [修改 3] 使用通用的檢查函式
        if should_refresh_data(last_update_time):
            print(f"🔄 週期({STRATEGY_INTERVAL})結算或定時更新...")
            strategy.refresh_history()
            last_update_time = time.time()

    # 啟動 WebSocket
    # 注意：這裡會訂閱 ["MINUTE_1", "MINUTE_30"] (如果 Config 是 30分)
    stream = MarketStream(SYMBOL, INTERVALS, callback_wrapper)
    stream.start()

    while True:
        time.sleep(1)