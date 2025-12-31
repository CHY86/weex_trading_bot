import websocket
import threading
import time
import json
import hmac
import hashlib
import base64
import config

class MarketStream:
    def __init__(self, symbol, on_price_update_callback):
        # [修正點 1] 變數名稱統一：這裡定義的名稱必須與 generate_headers 裡用的一樣
        self.api_key = config.API_KEY
        self.api_secret = config.SECRET_KEY      # 修正：對應下方 self.api_secret
        self.api_passphrase = config.PASSPHRASE  # 修正：對應下方 self.api_passphrase
        
        self.symbol = symbol
        self.callback = on_price_update_callback
        
        # 使用需要驗證的公共頻道路徑
        self.request_path = "/v2/ws/public"
        self.url = f"wss://ws-contract.weex.com{self.request_path}"
        
        self.ws = None
        self.wst = None

    def generate_headers(self):
        """生成 API 驗證所需的 Headers"""
        timestamp = str(int(time.time() * 1000))
        
        # 簽名訊息 = timestamp + requestPath
        message = timestamp + self.request_path
        
        # [修正點 2] 確保這裡引用的變數在 __init__ 中已正確定義
        signature = hmac.new(
            self.api_secret.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).digest()
        
        signature_b64 = base64.b64encode(signature).decode('utf-8')
        
        headers = {
            "User-Agent": "PythonClient/1.0",
            "ACCESS-KEY": self.api_key,
            "ACCESS-PASSPHRASE": self.api_passphrase,
            "ACCESS-TIMESTAMP": timestamp,
            "ACCESS-SIGN": signature_b64
        }
        return headers

    def on_open(self, ws):
        print(f"✅ WebSocket 連線已建立 (身分驗證通過)")
        
        # [訂閱請求]
        # 使用你指定的 channel 格式
        subscribe_payload = {
            "event": "subscribe",
            "channel": f"kline.LAST_PRICE.{self.symbol}.MINUTE_1"
        }
        
        json_str = json.dumps(subscribe_payload)
        ws.send(json_str)
        print(f"已發送訂閱: {json_str}")

    def on_message(self, ws, message):
        try:
            data = json.loads(message)
            
            # 1. 處理 Ping (維持連線)
            if data == 'ping':
                ws.send('pong')
                return
            
            # 2. 處理訂閱確認
            if data.get('event') == 'subscribe':
                print(f"✅ 訂閱成功: {data}")
                return

            # 3. 處理 K線/行情數據
            # 這裡增加一些容錯邏輯來解析 data
            if 'data' in data:
                market_data = data['data']
                
                # 情況 A: data 是一個 list (有些 API 回傳格式)
                if isinstance(market_data, list) and len(market_data) > 0:
                    market_data = market_data[0]
                
                # 情況 B: data 是一個 dict
                if isinstance(market_data, dict):
                    # 嘗試抓取 close (收盤價/最新價)
                    # 你的範例格式可能是 close 或 c
                    if 'close' in market_data:
                        price = float(market_data['close'])
                        self.callback(price)
                    elif 'c' in market_data:
                        price = float(market_data['c'])
                        self.callback(price)
            
        except Exception as e:
            # 暫時只印出錯誤，不中斷程式
            print(f"解析錯誤: {e} (收到: {message[:100]}...)")

    def on_error(self, ws, error):
        print(f"⚠️ WS Error: {error}")

    def on_close(self, ws, close_status_code, close_msg):
        print("⚠️ WS 連線中斷，5秒後重連...")
        time.sleep(5)
        self.start()

    def start(self):
        try:
            # 1. 生成簽名
            auth_headers = self.generate_headers()
            
            websocket.enableTrace(False)
            self.ws = websocket.WebSocketApp(
                self.url,
                on_open=self.on_open,
                on_message=self.on_message,
                on_error=self.on_error,
                on_close=self.on_close,
                header=auth_headers
            )

            self.wst = threading.Thread(target=self.ws.run_forever)
            self.wst.daemon = True
            self.wst.start()
        except Exception as e:
            print(f"❌ 啟動失敗: {e}")