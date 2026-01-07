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
        
        self.request_path = "/v2/ws/public"
        self.url = f"wss://ws-contract.weex.com{self.request_path}"
        
        self.ws = None
        self.wst = None
        self.keep_alive_thread = None # [新增] 心跳線程

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

    # [新增] 主動發送心跳的函數
    def _keep_alive(self):
        """每 20 秒發送一次 ping 以維持連線"""
        while self.ws and self.ws.sock and self.ws.sock.connected:
            try:
                self.ws.send('ping')
                # print("💓 Sent ping") # 除錯用，確認穩定後可註解掉
            except Exception as e:
                print(f"⚠️ Ping 發送失敗: {e}")
                break
            time.sleep(20) # 建議 15-20 秒一次，避免超時

    def on_open(self, ws):
        print(f"✅ WebSocket 連線已建立，正在訂閱 {self.intervals}...")
        
        # 1. 發送訂閱
        for interval in self.intervals:
            channel_name = f"kline.LAST_PRICE.{self.symbol}.{interval}"
            subscribe_payload = {
                "event": "subscribe",
                "channel": channel_name
            }
            ws.send(json.dumps(subscribe_payload))
            print(f"📡 已發送訂閱: {channel_name}")
            
        # 2. [新增] 啟動心跳線程
        self.keep_alive_thread = threading.Thread(target=self._keep_alive)
        self.keep_alive_thread.daemon = True # 設定為守護線程，主程式結束時它也會結束
        self.keep_alive_thread.start()

    def on_message(self, ws, message):
        try:
            # [修正] 優先處理純字串訊息 (Ping/Pong)
            if message == 'ping':
                ws.send('pong')
                return
            if message == 'pong':
                # ping 的回應，直接忽略
                return

            # 解析 JSON
            data = json.loads(message)
            
            # 處理訂閱確認
            event = data.get('event')
            if event == 'subscribe' or event == 'subscribed':
                print(f"✅ 訂閱成功: {data.get('channel')}")
                return

            # 處理 K線/行情數據
            if 'data' in data and 'channel' in data:
                channel = data['channel']
                market_data = data['data']
                
                interval = channel.split('.')[-1]

                if isinstance(market_data, list) and len(market_data) > 0:
                    market_data = market_data[0]
                
                if isinstance(market_data, dict):
                    # 嘗試抓取 close (收盤價/最新價)
                    # 你的範例格式可能是 close 或 c
                    price = float(market_data.get('close') or market_data.get('c', 0))
                    self.callback(interval, price)
            
        except json.JSONDecodeError:
            pass # 忽略無法解析的非 JSON 訊息
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