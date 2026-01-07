import time
import json
import hmac
import hashlib
import base64
import requests
from threading import Lock
from datetime import datetime
import config
from ai_logger import save_local_log

# ... (ClientOrderIdGenerator 保持不變) ...
class ClientOrderIdGenerator:
    def __init__(self, machine_id: int):
        self.machine_id = f"{machine_id:02d}"
        self.lock = Lock()
        self.last_ms = 0
        self.seq = 0

    def generate(self) -> str:
        now_ms = int(time.time() * 1000)
        with self.lock:
            if now_ms == self.last_ms:
                self.seq += 1
            else:
                self.last_ms = now_ms
                self.seq = 0
            seq = self.seq % 100_000
        prefix = datetime.fromtimestamp(now_ms / 1000).strftime("%Y%m%d%H%M%S")
        ms = f"{now_ms % 1000:03d}"
        return f"{prefix}{ms}{self.machine_id}{seq:05d}"

class WeexClient:
    def __init__(self):
        self.base_url = config.REST_URL
        self.api_key = config.API_KEY
        self.secret_key = config.SECRET_KEY
        self.passphrase = config.PASSPHRASE
        self.id_gen = ClientOrderIdGenerator(machine_id=1)

    def _generate_signature(self, timestamp, method, request_path, query_string="", body=""):
        message = timestamp + method.upper() + request_path + query_string + body
        signature = hmac.new(
            self.secret_key.encode('utf-8'), 
            message.encode('utf-8'), 
            hashlib.sha256
        ).digest()
        return base64.b64encode(signature).decode('utf-8')

    def _send_request(self, method, endpoint, query_params="", body_dict=None):
        timestamp = str(int(time.time() * 1000))
        request_path = endpoint
        
        body_str = ""
        if body_dict:
            body_str = json.dumps(body_dict)
            
        signature = self._generate_signature(timestamp, method, request_path, query_params, body_str)

        headers = {
            "ACCESS-KEY": self.api_key,
            "ACCESS-SIGN": signature,
            "ACCESS-TIMESTAMP": timestamp,
            "ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json",
            "locale": "en-US"
        }

        full_url = self.base_url + request_path + query_params
        
        try:
            if method == "GET":
                response = requests.get(full_url, headers=headers)
            else:
                response = requests.post(full_url, headers=headers, data=body_str)
            
            if response.status_code != 200:
                print(f"⚠️ API Error [{response.status_code}]: {response.text}")

            return response.json()
        except Exception as e:
            print(f"❌ API Request Failed: {e}")
            return None

    # --- [修正] 歷史 K 線功能 (根據官方文件) ---

    def get_history_candles(self, symbol, granularity, start_time=None, end_time=None, limit=100):
        # 注意: 根據文件，endpoint 區分大小寫
        endpoint = "/capi/v2/market/historyCandles"
        
        query = f"?symbol={symbol}&granularity={granularity}&limit={limit}"
        
        if end_time:
            query += f"&endTime={end_time}"
        elif start_time:
            query += f"&startTime={start_time}"
            
        # 取得完整回應
        response = self._send_request("GET", endpoint, query)
        
        # [修正點] 針對回傳格式進行彈性處理
        # 情況 A: 回傳直接是 List [[time, open...], ...] (根據 HTML 文件)
        if isinstance(response, list):
            return response
            
        # 情況 B: 回傳是 Dict 且有 "data" (標準 API 格式)
        if isinstance(response, dict) and "data" in response:
            return response["data"]
            
        # 情況 C: 錯誤或無資料
        print(f"⚠️ 警告: K 線回傳格式不如預期或為空: {str(response)[:100]}")
        return []

    # ... (其他原有的下單函數保持不變) ...
    def get_server_time(self):
        return self._send_request("GET", "/capi/v2/market/time", "?symbol=" + config.SYMBOL)

    def get_account_assets(self):
        return self._send_request("GET", "/capi/v2/account/assets")
        
    def place_order(self, side, size, price=None, match_price="0", order_type="0", 
                    client_oid=None, preset_take_profit=None, preset_stop_loss=None, margin_mode=None, extra_params=None):
        endpoint = "/capi/v2/order/placeOrder"
        client_oid = client_oid or self.id_gen.generate()
        if str(match_price) == "0" and not price:
            raise ValueError("Limit order requires price")
            
        body = {
            "symbol": config.SYMBOL,
            "client_oid": str(client_oid),
            "size": str(size),
            "type": str(side),
            "order_type": str(order_type),
            "match_price": str(match_price),
        }
        if price: body["price"] = str(price)
        if preset_take_profit: body["presetTakeProfitPrice"] = str(preset_take_profit)
        if preset_stop_loss: body["presetStopLossPrice"] = str(preset_stop_loss)
        if margin_mode: body["marginMode"] = int(margin_mode)
        if extra_params: body.update(extra_params)
        
        print(f"🚀 下單: 方向={side} | 數量={size} | 價格={price}")
        return self._send_request("POST", endpoint, body_dict=body)

    def upload_ai_log(self, stage, model, input_data, output_data, explanation, order_id=None):
        endpoint = "/capi/v2/order/uploadAiLog"
        save_local_log(stage, model, input_data, output_data, explanation, order_id)
        body = {
            "stage": str(stage),
            "model": str(model),
            "input": input_data,
            "output": output_data,
            "explanation": str(explanation)
        }
        if order_id: body["orderId"] = str(order_id)
        print(f"📝 上傳 AI Log: {explanation[:30]}...")
        return self._send_request("POST", endpoint, body_dict=body)