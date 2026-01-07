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
        # 只在 1分鐘線來的時候做即時檢查
        if interval != "MINUTE_1": 
            return
            
        now = datetime.now()
        
        # 冷卻期檢查
        if (now - self.last_trade_time).total_seconds() < config.COOLDOWN_HOURS * 3600:
            return 

        # 確保有歷史數據
        if self.history_df.empty:
            return
        
        # --- [關鍵修正] 計算「即時」RSI ---
        # 原理：取出歷史的 Close 列表，加上「當前價格」作為最新一根 K 線的 Close，算出即時 RSI
        
        # 1. 複製歷史收盤價
        closes = self.history_df['close'].copy()
        
        # 2. 暫時將當前價格附加到序列末尾 (模擬當前 K 線)
        # 使用 pd.concat 效率較好
        temp_series = pd.concat([closes, pd.Series([current_price])], ignore_index=True)
        
        # 3. 計算即時 RSI
        rsi_series = ta.rsi(temp_series, length=config.RSI_PERIOD)
        if rsi_series is None or len(rsi_series) == 0:
            return
            
        real_time_rsi = rsi_series.iloc[-1] # 取最新算出來的那個值

        # 4. 取得布林通道上軌 (布林帶變化較慢，暫時沿用歷史數據的預估值，或是也可以像 RSI 一樣重算)
        # 為了效能，這裡暫時沿用上一根完整的布林上軌，或者您可以比照 RSI 方式重算 BB
        latest_history = self.history_df.iloc[-1]
        bb_upper = latest_history.get(f'BBU_{config.BB_LENGTH}_{config.BB_STD}', 999999)

        # --- 策略邏輯 ---
        
        # 1. 價格突破 Config 設定週期的前高
        is_breakout = current_price > self.prev_high
        
        # 2. 震盪過濾 (使用 Config 的 RSI 閥值 + 即時 RSI)
        is_overextended = (real_time_rsi > config.RSI_OVERBOUGHT) or (current_price > bb_upper)
        
        # 觸發條件
        if is_breakout and is_overextended:
            # 準備 Log 用的資料
            reason = f"RSI({real_time_rsi:.2f}) > {config.RSI_OVERBOUGHT} & Price > BB_Up"
            self.execute_trade_logic(current_price, "SHORT", reason, real_time_rsi)

    def execute_trade_logic(self, price, direction, reason, rsi_val):
        print(f"⚡ 觸發交易訊號: {direction} @ {price} | 原因: {reason}")
        
        # 上傳 Log (現在會受 Config 開關控制)
        self.client.upload_ai_log(
            stage="Signal Generation",
            model="PlanB_Algo_v1",
            input_data={"price": price, "rsi": rsi_val},
            output_data={"decision": direction},
            explanation=reason
        )

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
        
        strategy.on_tick(interval, price)
        
        # 心跳顯示 (每 30 秒)
        if time.time() - last_heartbeat_time > 30:
            # 為了顯示正確的心跳，我們也做一個簡單的即時運算 (僅供顯示)
            current_rsi = 0
            if not strategy.history_df.empty:
                closes = strategy.history_df['close'].copy()
                temp_series = pd.concat([closes, pd.Series([price])], ignore_index=True)
                rsi_s = ta.rsi(temp_series, length=config.RSI_PERIOD)
                if rsi_s is not None:
                    current_rsi = rsi_s.iloc[-1]

            print(f"💓 [監控中] {config.STRATEGY_INTERVAL} | 現價: {price} | 即時RSI: {current_rsi:.2f} (閥值:{config.RSI_OVERBOUGHT})")
            last_heartbeat_time = time.time()

        if should_refresh_data(last_update_time):
            print(f"🔄 週期({config.STRATEGY_INTERVAL})結算或定時更新...")
            strategy.refresh_history()
            last_update_time = time.time()

    # 啟動 WebSocket
    # 注意：這裡會訂閱 ["MINUTE_1", "MINUTE_30"] (如果 Config 是 30分)
    stream = MarketStream(SYMBOL, INTERVALS, callback_wrapper)
    stream.start()

    while True:
        time.sleep(1)