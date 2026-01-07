import time
import pandas as pd
import pandas_ta as ta
from datetime import datetime, timedelta

from exchange_client import WeexClient
from market_stream import MarketStream
import config
from ai_logger import save_local_log


# 仍然保留這兩個方便調用的常數，但指向 Config
SYMBOL = config.SYMBOL
STRATEGY_INTERVAL = config.STRATEGY_INTERVAL

# 始終訂閱 MINUTE_1 (監控用) + 策略設定的週期 (分析用)
INTERVALS = ["MINUTE_1", STRATEGY_INTERVAL] 

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
        
        now_ms = int(time.time() * 1000)
        raw_klines = self.client.get_history_candles(
            symbol=SYMBOL, 
            granularity=self.client._map_interval(STRATEGY_INTERVAL),
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
        
        # 計算技術指標
        df['RSI'] = ta.rsi(df['close'], length=config.RSI_PERIOD)
        bb = ta.bbands(df['close'], length=config.BB_LENGTH, std=config.BB_STD)
        df = pd.concat([df, bb], axis=1)
        
        self.history_df = df
        
        # 更新策略基準
        if len(df) >= 2:
            last_completed = df.iloc[-2]
            self.prev_high = last_completed['high']
            self.prev_low = last_completed['low']
            rsi_val = last_completed['RSI']
            print(f"📊 [{STRATEGY_INTERVAL}] 策略基準: 前高={self.prev_high}, RSI={rsi_val:.2f}")

    def on_tick(self, interval, current_price):
        if interval != "MINUTE_1": 
            return
            
        now = datetime.now()
        
        # 冷卻時間檢查
        if (now - self.last_trade_time).total_seconds() < config.COOLDOWN_HOURS * 3600:
            return 

        if self.history_df.empty:
            return
        
        # --- 計算即時 RSI ---
        closes = self.history_df['close'].copy()
        temp_series = pd.concat([closes, pd.Series([current_price])], ignore_index=True)
        

        rsi_series = ta.rsi(temp_series, length=config.RSI_PERIOD)
        if rsi_series is None or len(rsi_series) == 0:
            return
            
        real_time_rsi = rsi_series.iloc[-1]

        # 取得布林通道上軌
        latest_history = self.history_df.iloc[-1]
        bb_upper_col = f'BBU_{config.BB_LENGTH}_{config.BB_STD}'
        bb_upper = latest_history.get(bb_upper_col, 999999)

        # --- 策略邏輯 ---
        is_breakout = current_price > self.prev_high
        

        is_overextended = (real_time_rsi > config.RSI_OVERBOUGHT) or (current_price > bb_upper)
        
        if is_breakout and is_overextended:
            reason = f"RSI({real_time_rsi:.2f}) > {config.RSI_OVERBOUGHT} & Price > BB_Up"
            self.execute_trade_logic(current_price, "SHORT", reason, real_time_rsi)

    def execute_trade_logic(self, price, direction, reason, rsi_val):
        print(f"⚡ 觸發交易訊號: {direction} @ {price} | 原因: {reason}")
        
        self.client.upload_ai_log(
            stage="Signal Generation",
            model="PlanB_Algo_v1",
            input_data={"price": price, "rsi": rsi_val},
            output_data={"decision": direction},
            explanation=reason
        )
        
        # 下單邏輯 (帶止損止盈)
        tp_price = int(price * 0.985) 
        sl_price = int(price * 1.02)

        try:
            order = self.client.place_order(
                side=2, # 開空
                size="0.01",
                match_price="1", # 市價
                preset_take_profit=str(tp_price),
                preset_stop_loss=str(sl_price),
                margin_mode=1
            )
            
            if order and 'data' in order and 'orderId' in order['data']:
                self.last_trade_time = datetime.now()
                print(f"✅ 下單成功! OrderID: {order['data']['orderId']}")
                
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

# --- 智慧判斷換線邏輯 ---
def should_refresh_data(last_refresh_time):
    now = datetime.now()
    minutes = now.minute
    hours = now.hour
    
    parts = STRATEGY_INTERVAL.split('_')
    p_type = parts[0]
    p_val = int(parts[1])
    
    is_time_to_refresh = False
    
    if p_type == "MINUTE":
        if minutes % p_val == 0:
            is_time_to_refresh = True
    elif p_type == "HOUR":
        if hours % p_val == 0 and minutes == 0:
            is_time_to_refresh = True
            
    if is_time_to_refresh and (time.time() - last_refresh_time > 60):
        return True
        
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

    stream = MarketStream(SYMBOL, INTERVALS, callback_wrapper)
    stream.start()

    while True:
        time.sleep(1)