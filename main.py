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

    # --- [保留] 動態取得布林上軌欄位名 ---
    def _get_bbu_col_name(self, df):
        """
        自動尋找 BBU 開頭的欄位，避免 2.0 與 2 的命名差異問題
        """
        if df is None or df.empty:
            return None
        # 找出所有開頭是 BBU_ 的欄位
        cols = [c for c in df.columns if str(c).startswith('BBU_')]
        if cols:
            return cols[0] # 回傳找到的第一個
        return None

    def refresh_history(self):
        """根據 Config 設定的週期抓取歷史數據"""
        print(f"🔄 正在更新 {SYMBOL} {STRATEGY_INTERVAL} 歷史數據...")
        
        now_ms = int(time.time() * 1000)
        
        limit_count = 100 
        
        raw_klines = self.client.get_history_candles(
            symbol=SYMBOL, 
            granularity=self.client._map_interval(STRATEGY_INTERVAL),
            end_time=now_ms,
            limit=limit_count
        )
        
        if not raw_klines:
            print("⚠️ 無法獲取 K 線數據，等待下次更新")
            return

        # 整理數據
        df = pd.DataFrame(raw_klines, columns=['time', 'open', 'high', 'low', 'close', 'vol', 'quote_vol'])
        df['time'] = df['time'].astype(int) # 確保時間是整數
        df['close'] = df['close'].astype(float)
        df['high'] = df['high'].astype(float)
        df['low'] = df['low'].astype(float)
        df = df.sort_values('time').reset_index(drop=True)
        
        # 計算技術指標
        df['RSI'] = ta.rsi(df['close'], length=config.RSI_PERIOD)
        bb = ta.bbands(df['close'], length=config.BB_LENGTH, std=config.BB_STD)
        df = pd.concat([df, bb], axis=1)
        
        self.history_df = df
        
        # --- [保留] 智慧判斷取哪一根 
        if len(df) >= 2:
            # 1. 算出「當下時間點」理論上的 K 線開盤時間
            now = datetime.now()
            interval_minutes = 0
            current_candle_start = now
            
            # 解析週期計算時間
            if "MINUTE" in STRATEGY_INTERVAL:
                interval_minutes = int(STRATEGY_INTERVAL.split('_')[1])
                # 捨去餘數算法: 例如 14:29, 5分K -> 29%5=4 -> 29-4=25 -> 14:25
                current_candle_start = now.replace(second=0, microsecond=0)
                current_candle_start = current_candle_start - timedelta(minutes=current_candle_start.minute % interval_minutes)
            elif "HOUR" in STRATEGY_INTERVAL:
                interval_hours = int(STRATEGY_INTERVAL.split('_')[1])
                current_candle_start = now.replace(minute=0, second=0, microsecond=0)
                current_candle_start = current_candle_start - timedelta(hours=current_candle_start.hour % interval_hours)
            
            # 轉成毫秒時間戳
            current_candle_ts = int(current_candle_start.timestamp() * 1000)
            
            # 取得 API 回傳的最後一根 K 線時間
            last_kline_ts = int(df.iloc[-1]['time'])

            # 2. 比對邏輯
            idx_used = -1 # 預設取倒數第一根
            
            if last_kline_ts == current_candle_ts:
                # 情況 A: API 給了正在跑的那根 (例如 14:25) -> 取上一根 (-2)
                last_completed = df.iloc[-2]
                idx_used = -2
            else:
                # 情況 B: API 只給到已結算的 (例如 14:20) -> 取最後一根 (-1)
                last_completed = df.iloc[-1]
                idx_used = -1

            # 設定策略基準
            self.prev_high = last_completed['high']
            self.prev_low = last_completed['low']
            rsi_val = last_completed['RSI']
            
            # 取得布林上軌
            bb_col = self._get_bbu_col_name(df)
            bb_upper_val = last_completed[bb_col] if bb_col else 0
            
            # 轉換時間顯示方便除錯
            kline_time_str = datetime.fromtimestamp(int(last_completed['time'])/1000).strftime('%H:%M')
            
            print(f"📊 [{STRATEGY_INTERVAL}] 策略基準 (取idx {idx_used}, K線時間{kline_time_str}): {SYMBOL} 前高={self.prev_high}, RSI={rsi_val:.2f} (閥值:{config.RSI_OVERBOUGHT}), BB上軌={bb_upper_val:.2f}")

    def on_tick(self, interval, current_price):
        if interval != "MINUTE_1": 
            return
            
        now = datetime.now()
        
        # 冷卻時間檢查
        if (now - self.last_trade_time).total_seconds() < config.COOLDOWN_HOURS * 3600:
            return 

        if self.history_df.empty:
            return
        
        # --- 計算即時指標 ---
        closes = self.history_df['close'].copy()
        # 建立包含當前價格的臨時序列
        temp_series = pd.concat([closes, pd.Series([current_price])], ignore_index=True)
        
        # 1. 計算即時 RSI
        rsi_series = ta.rsi(temp_series, length=config.RSI_PERIOD)
        if rsi_series is None or len(rsi_series) == 0:
            return
        real_time_rsi = rsi_series.iloc[-1]

        # 2. [修正] 計算即時布林通道 (使用 temp_series 重算)
        bb_df = ta.bbands(temp_series, length=config.BB_LENGTH, std=config.BB_STD)
        
        # 動態取得上軌
        bb_col = self._get_bbu_col_name(bb_df)
        bb_upper = bb_df.iloc[-1][bb_col] if bb_col else 999999

        # --- 策略邏輯 ---
        is_breakout = current_price > self.prev_high
        is_overextended = (real_time_rsi > config.RSI_OVERBOUGHT) or (current_price > bb_upper)
        
        if is_breakout and is_overextended:
            reason = f"RSI({real_time_rsi:.2f}) > {config.RSI_OVERBOUGHT} & Price > BB_Up({bb_upper:.2f})"
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
    """
    判斷是否該更新歷史資料
    (增加 2 秒延遲，確保交易所已結算 K 線)
    """
    now = datetime.now()
    minutes = now.minute
    hours = now.hour
    seconds = now.second  # [新增] 取得當前秒數
    
    # 解析 Config (e.g., "MINUTE_30" -> type="MINUTE", val=30)
    parts = STRATEGY_INTERVAL.split('_')
    p_type = parts[0]
    p_val = int(parts[1])
    
    is_time_to_refresh = False
    
    # 邏輯: 必須整除 (時間到了) 且 秒數 >= 2 (給交易所一點時間)
    # 且 秒數 < 10 (避免過了太久還在重複觸發，雖然有 last_refresh_time 保護)
    
    if p_type == "MINUTE":
        if (minutes % p_val == 0) and (2 <= seconds <= 10):
            is_time_to_refresh = True
            
    elif p_type == "HOUR":
        if (hours % p_val == 0) and (minutes == 0) and (2 <= seconds <= 10):
            is_time_to_refresh = True
            
    # 保護機制：距離上次更新至少要過 60 秒 (避免同一分鐘內重複更新)
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
            current_rsi = 0
            current_bb_upper = 0
            
            if not strategy.history_df.empty:
                closes = strategy.history_df['close'].copy()
                temp_series = pd.concat([closes, pd.Series([price])], ignore_index=True)
                
                # 1. 重算即時 RSI
                rsi_s = ta.rsi(temp_series, length=config.RSI_PERIOD)
                if rsi_s is not None:
                    current_rsi = rsi_s.iloc[-1]
                
                # 2. [修正] 重算即時 BB 上軌
                bb_df = ta.bbands(temp_series, length=config.BB_LENGTH, std=config.BB_STD)
                bb_col = strategy._get_bbu_col_name(bb_df)
                if bb_col:
                    current_bb_upper = bb_df.iloc[-1][bb_col]

            print(f"💓 [監控中] {SYMBOL} {config.STRATEGY_INTERVAL} | 現價: {price} | RSI: {current_rsi:.2f} (閥值:{config.RSI_OVERBOUGHT}) | BB上軌: {current_bb_upper:.2f}")            
            last_heartbeat_time = time.time()

        if should_refresh_data(last_update_time):
            print(f"🔄 週期({config.STRATEGY_INTERVAL})結算或定時更新...")
            strategy.refresh_history()
            last_update_time = time.time()

    stream = MarketStream(SYMBOL, INTERVALS, callback_wrapper)
    stream.start()

    while True:
        time.sleep(1)