import time
import pandas as pd
import pandas_ta as ta
import json
from datetime import datetime, timedelta
from openai import OpenAI  # [修改] 匯入 OpenAI
from exchange_client import WeexClient
from market_stream import MarketStream
import config
from ai_logger import save_local_log

DECISION_AI = "AI_ASSISTED"
DECISION_RULE = "RULE_BASED"


# 初始化 OpenAI Client
ai_client = OpenAI(api_key=config.OPENAI_API_KEY)

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
        self.last_ai_req_time = 0  # [新增] AI 請求冷卻計時器
        self.prev_high = 0.0
        self.prev_low = 0.0
        
        # 初始化數據
        self.refresh_history()

    def check_risk_limits(self):
        """[新增] 風險檢查：避免訂單過多或倉位過大"""
        # 1. 檢查掛單數量
        open_orders = self.client.get_open_orders(config.SYMBOL)
        if len(open_orders) >= config.MAX_OPEN_ORDERS:
            print(f"🚫 [風控攔截] 掛單過多 ({len(open_orders)} 張)，停止下單。")
            return False

        # 2. 檢查持倉數量
        positions = self.client.get_all_positions(config.SYMBOL)
        valid_positions = [p for p in positions if float(p.get('hold_vol', 0) or p.get('size', 0)) > 0]
        if len(valid_positions) >= config.MAX_POSITIONS:
            print(f"🚫 [風控攔截] 已有倉位 ({len(valid_positions)} 個)，停止下單。")
            return False
            
        return True

    # --- 動態取得布林上軌欄位名 ---
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

    def consult_ai_agent(self, market_data):
        """諮詢 OpenAI GPT-4o-mini (傳入歷史 K 線增強分析深度)"""
        if not config.ENABLE_AI_DECISION:
            return {"action": "GO", "confidence": 1.0, "explanation": "Manual logic"}

        # 1. 準備最近 30 筆 K 線數據
        try:
            # 複製最近 30 筆數據以免影響原始資料
            recent_df = self.history_df.tail(30).copy()
            
            # 轉換時間戳為易讀格式 (HH:MM)
            recent_df['time_str'] = pd.to_datetime(recent_df['time'], unit='ms').dt.strftime('%H:%M')
            
            # 找出布林上軌欄位名稱
            bb_cols = [c for c in recent_df.columns if str(c).startswith(f'BBU_{config.BB_LENGTH}')]
            bb_col = bb_cols[0] if bb_cols else 'close' # 防呆
            
            # 篩選要給 AI 看的欄位
            cols_to_show = ['time_str', 'open', 'high', 'low', 'close', 'RSI', bb_col]
            
            # 轉為字串表格 (類似 CSV 格式)
            history_str = recent_df[cols_to_show].to_string(index=False)
            
        except Exception as e:
            print(f"⚠️ 數據整理失敗: {e}")
            history_str = "歷史數據提取失敗"

        # 2. 建構深度 Prompt
        system_prompt = """
        你是一位在加密貨幣市場擁有 20 年經驗的資深量化交易員。
        你擅長識別價格行為 (Price Action)、K線型態 (Candlestick Patterns) 與假突破 (Fakeouts)。
        你的任務是根據提供的歷史數據與當前快照，判斷是否進行「做多 (LONG)」操作。
        """

        user_prompt = f"""
        交易對: {config.SYMBOL} ({config.STRATEGY_INTERVAL})
        
        【當前市場快照】
        - 現價: {market_data['price']}
        - 即時 RSI: {market_data['rsi']:.2f}
        - 布林通道上軌: {market_data['bb_upper']:.2f}
        
        【最近 30 根 K 線數據 (包含 RSI 與 BB上軌)】
        {history_str}
        
        【分析要求】
        1. 觀察最近的價格趨勢：是急漲、緩漲還是高檔震盪？
        2. 尋找疲弱訊號：是否有長上影線 (Wicks)、吞噬形態 (Engulfing) 或 RSI 背離？
        3. 判斷布林通道：價格是否過度偏離上軌 (Mean Reversion 機會)？
        
        請以 JSON 格式回傳決策：
        - "action": "LONG" (建議做多) 或 "WAIT" (風險過高或訊號不明)
        - "confidence": 0.0 ~ 1.0 (信心分數)
        - "explanation": 100字以內的中文分析。**請不要只報數字**，請描述你看到的結構（例如：「連續三根紅K後出現十字星，且RSI高檔鈍化，顯示多頭力竭...」）。
        """

        try:
            response = ai_client.chat.completions.create(
                model=config.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.6, # 稍微降低隨機性，讓分析更專注
                max_tokens=300
            )
            
            content = response.choices[0].message.content
            clean_json = content.replace('```json', '').replace('```', '').strip()
            
            # 解析並列印 AI 回覆
            ai_decision = json.loads(clean_json)

            # 上傳 AI Log (如果啟用)
            self.client.upload_ai_log(
                stage="Decision Making",
                model=config.OPENAI_MODEL,
                input_data={
                    "prompt": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                    "market_snapshot": {
                        "price": market_data['price'],
                        "rsi": market_data['rsi'],
                        "bb_upper": market_data['bb_upper'],
                        "historical_klines": history_str
                    }
                },
                output_data={
                    "action": ai_decision["action"],
                    "confidence": ai_decision["confidence"],
                    "explanation": ai_decision["explanation"]
                },
                explanation=ai_decision["explanation"]
            )

            print(f"🤖 [AI 深度分析] {json.dumps(ai_decision, ensure_ascii=False)}")
            
            return ai_decision
                
        except Exception as e:
            print(f"❌ OpenAI 諮詢出錯: {e}")
            return {"action": "WAIT", "confidence": 0, "explanation": f"API Error: {str(e)}"}

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


    def is_range_market(self):
        """判斷目前市場是否處於盤整區間 (布林通道寬度小於 5%)"""
        if self.history_df.empty:
            return False

        df = self.history_df.iloc[-1]

        bb_upper = df.get(self._get_bbu_col_name(self.history_df), None)
        bb_lower_cols = [c for c in self.history_df.columns if str(c).startswith('BBL_')]
        bb_lower = df[bb_lower_cols[0]] if bb_lower_cols else None
        bb_mid_cols = [c for c in self.history_df.columns if str(c).startswith('BBM_')]
        bb_mid = df[bb_mid_cols[0]] if bb_mid_cols else None

        if not bb_upper or not bb_lower or not bb_mid:
            print("⚠️ 無法取得布林通道數據以判斷盤整區間")
            return False

        bb_width = (bb_upper - bb_lower) / bb_mid
        print("is_range_market debug:")
        print("bb_upper:", bb_upper, "bb_lower:", bb_lower, "bb_mid:", bb_mid, "bb_width:", bb_width,"是否為盤整區間:", bb_width < 0.05)
        return bb_width < 0.05
    
    def check_range_reversion(self, price, real_time_rsi):
        """判斷是否符合盤整區間反轉進場條件"""
        df = self.history_df.iloc[-1]

        # 取得 BB 下軌
        bb_lower_cols = [c for c in self.history_df.columns if str(c).startswith('BBL_')]
        if not bb_lower_cols:
            return False
        bb_lower = df[bb_lower_cols[0]]

        # 條件 1：價格接近下軌但未有效跌破
        near_lower_band = bb_lower < price < bb_lower * 1.005

        # 條件 2：RSI 已低於中性區，且開始回升
        rsi_recovering = real_time_rsi > 40
        print("check_range_reversion debug:")
        print(f"price={price}, bb_lower={bb_lower}, near_lower_band={near_lower_band}, real_time_rsi={real_time_rsi}, rsi_recovering={rsi_recovering}, 是否符合反轉條件:", near_lower_band and rsi_recovering)
        return near_lower_band and rsi_recovering


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



        # --- 策略邏輯 ---
        # 判斷市場狀態
        is_range = self.is_range_market()

        # --- 1. 區間盤：抄底策略 ---
        if is_range:
            if self.check_range_reversion(current_price, real_time_rsi):
                if not self.check_risk_limits():
                    return

                print("📉 區間盤抄底訊號成立，執行回歸交易")
                self.execute_trade_with_decision(
                price=current_price,
                decision_source=DECISION_RULE,
                strategy_name="range_reversion",
                extra_context={
                    "rsi": real_time_rsi,
                    "market_regime": "range"
                }
                )
                return

        # --- 2. 趨勢盤：假突破做多策略 ---
        # 取得布林通道上軌
        bb_upper_col = f'BBU_{config.BB_LENGTH}_{config.BB_STD}.0'
        bb_upper = self.history_df.iloc[-1].get(bb_upper_col, 999999)
        is_valid_breakout = current_price > self.prev_high * 1.001  # 假突破過濾
        is_overextended = (real_time_rsi > config.RSI_OVERBOUGHT) or (current_price > bb_upper * 1.001)
        
        if is_valid_breakout and is_overextended:
            # 1. 風控檢查 (新增)
            if not self.check_risk_limits(): return

            # [新增] AI API 頻率限制 (解決 429 錯誤)
            # 限制每 20 秒最多呼叫一次
            if (time.time() - self.last_ai_req_time) < 20:
                print(f"⏳ 條件成立但 AI 冷卻中 (避免 Rate Limit)...")
                return
            
            # 更新 API 呼叫時間
            self.last_ai_req_time = time.time()

            # 2. AI 最終決策
            ai_res = self.consult_ai_agent({"price": current_price, "rsi": real_time_rsi, "bb_upper": bb_upper})
            
            if ai_res["action"] == "LONG" and ai_res["confidence"] >= config.AI_CONFIDENCE_THRESHOLD:
                print(f"   - 當前價格: {current_price}, RSI: {real_time_rsi:.2f}, BB上軌: {bb_upper:.2f}")
                print(f"✅ 條件符合且 AI 建議做多，準備下單...")
                print(f"   - AI 分析: {ai_res['explanation']}")
                
                # 2. 執行下單
                self.execute_trade_with_decision(
                price=current_price,
                decision_source=DECISION_AI,
                strategy_name="breakout_momentum_ai",
                extra_context={
                    "prev_high": self.prev_high,
                    "rsi": real_time_rsi,
                    "bb_upper": bb_upper,
                    "ai_confidence": ai_res["confidence"]
                }
            )

    def execute_trade_with_decision(
    self,
    price,
    decision_source,
    strategy_name,
    extra_context=None
    ):
        """
        統一交易執行入口，並記錄決策來源（AI / 規則）
        """

        # === 1. 下單（沿用原本的 execute_trade 內容） ===
        order_result = self.execute_trade(price=price)

        if not order_result:
            return None

        order_id = order_result.get("order_id") \
            if isinstance(order_result, dict) else None

        # === 2. 統一寫本機決策 log（不管 AI / 非 AI） ===
        log_payload = {
            "strategy": strategy_name,
            "decision_source": decision_source,
            "symbol": config.SYMBOL,
            "price": price,
            "timestamp": int(time.time() * 1000)
        }

        if extra_context:
            log_payload["context"] = extra_context

        save_local_log(
            stage="Trade Execution",
            model=decision_source,
            input_data=log_payload,
            output_data={
                "order_id": order_id,
                "action": "OPEN_LONG"
            },
            explanation=(
                "Trade executed automatically based on AI-assisted decision."
                if decision_source == DECISION_AI
                else
                "Trade executed automatically based on predefined rule-based strategy."
            )
        )

        return order_result

    def execute_trade(self, price):
        tp = str(int(price * 1.02))
        sl = str(int(price * 0.985))

        try:
            self.client.place_order(side=1, size="0.01", match_price="1", 
                                          preset_take_profit=tp, preset_stop_loss=sl, margin_mode=1)
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