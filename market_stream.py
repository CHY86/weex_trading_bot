import websocket
import threading
import time
import json
import hmac
import hashlib
import base64
import config

class MarketStream:
    def __init__(self, symbol, intervals, on_price_update_callback):
        self.api_key = config.API_KEY
        self.api_secret = config.SECRET_KEY
        self.api_passphrase = config.PASSPHRASE
        
        self.symbol = symbol
        self.intervals = intervals
        self.callback = on_price_update_callback
        
        # 請確認 URL 是否正確，部分合約 WS 需要加上 /v2/ws/public
        self.request_path = "/v2/ws/public"
        self.url = f"wss://ws-contract.weex.com{self.request_path}"
        
        self.ws = None
        self.wst = None

    def generate_headers(self):
        timestamp = str(int(time.time() * 1000))
        message = timestamp + self.request_path
        signature = hmac.new(
            self.api_secret.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).digest()
        signature_b64 = base64.b64encode(signature).decode('utf-8')
        
        return {
            "User-Agent": "PythonClient/1.0",
            "ACCESS-KEY": self.api_key,
            "ACCESS-PASSPHRASE": self.api_passphrase,
            "ACCESS-TIMESTAMP": timestamp,
            "ACCESS-SIGN": signature_b64
        }

    def on_open(self, ws):
        print(f"✅ WebSocket 連線已建立，正在訂閱 {self.intervals}...")
        
        # 發送訂閱請求
        for interval in self.intervals:
            channel_name = f"kline.LAST_PRICE.{self.symbol}.{interval}"
            subscribe_payload = {
                "event": "subscribe",
                "channel": channel_name
            }
            ws.send(json.dumps(subscribe_payload))
            print(f"📡 已發送訂閱: {channel_name}")

    def on_message(self, ws, message):
        try:
            # 1. 嘗試解析 JSON
            data = json.loads(message)
            
            # 2. [關鍵修正] 處理伺服器的主動 Ping
            # 格式: {"event":"ping","time":"1693208170000"}
            if isinstance(data, dict) and data.get('event') == 'ping':
                server_time = data.get('time')
                pong_payload = {
                    "event": "pong",
                    "time": server_time
                }
                ws.send(json.dumps(pong_payload))
                # print(f"💓 已回應 Pong: {server_time}") # 除錯時可打開
                return

            # 3. 處理訂閱確認 (event: subscribe 或 subscribed)
            event = data.get('event')
            if event == 'subscribe' or event == 'subscribed':
                print(f"✅ 訂閱成功: {data.get('channel')}")
                return

            # 4. 處理 K線/行情數據
            if 'data' in data and 'channel' in data:
                channel = data['channel']
                market_data = data['data']
                
                # 解析週期 (從 channel 字串中取出 MINUTE_1 或 HOUR_4)
                interval = channel.split('.')[-1]

                if isinstance(market_data, list) and len(market_data) > 0:
                    market_data = market_data[0]
                
                if isinstance(market_data, dict):
                    # 嘗試抓取 close (收盤價/最新價)
                    price = float(market_data.get('close') or market_data.get('c', 0))
                    self.callback(interval, price)
            
        except json.JSONDecodeError:
            # 萬一收到純字串訊息 (雖然根據您的描述應該都是 JSON)
            if message == 'ping':
                ws.send('pong')
        except Exception as e:
            print(f"解析錯誤: {e} (收到: {str(message)[:100]}...)")

    def on_error(self, ws, error):
        print(f"⚠️ WS Error: {error}")

    def on_close(self, ws, close_status_code, close_msg):
        print("⚠️ WS 連線中斷，5秒後重連...")
        time.sleep(5)
        self.start()

    def start(self):
        try:
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