import time
import json
import hmac
import hashlib
import base64
import requests
from threading import Lock
from datetime import datetime
import config  # 匯入設定檔

class ClientOrderIdGenerator:
    """生成唯一的訂單 ID，避免重複下單"""
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
        # 確保 body 是字串格式
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
        
        # 處理 Body
        body_str = ""
        if body_dict:
            body_str = json.dumps(body_dict)
            
        # 生成簽名
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
            
            # 回傳 JSON 格式
            return response.json()
        except Exception as e:
            print(f"❌ API Request Error: {e}")
            return None

    # --- 封裝好的功能函數 ---

    def get_server_time(self):
        return self._send_request("GET", "/capi/v2/market/time", "?symbol=" + config.SYMBOL)

    def get_account_assets(self):
        """查詢帳戶資產"""
        return self._send_request("GET", "/capi/v2/account/assets")

    def get_open_orders(self):
        """查詢當前掛單"""
        return self._send_request("GET", "/capi/v2/order/current", f"?symbol={config.SYMBOL}")

    def place_order(self, side, size, price=None, order_type="limit"):
        """
        下單核心函數
        side: 1=開多, 2=平多, 3=開空, 4=平空 (根據 WEEX 定義)
        """
        endpoint = "/capi/v2/order/placeOrder"
        
        # 根據 WEEX 定義: 0=Limit(限價), 1=Market(市價)
        # 注意: 這裡簡化邏輯，你可能需要根據文件微調 type 定義
        o_type = "0" if order_type == "limit" else "1"
        
        body = {
            "symbol": config.SYMBOL,
            "client_oid": self.id_gen.generate(),
            "size": str(size),
            "type": str(side), 
            "order_type": o_type, 
            "match_price": "1", # 1: 只做 Maker (視需求調整)
            "price": str(price) if price else ""
        }
        
        print(f"🚀 正在下單: {side} | 數量: {size} | 價格: {price}")
        return self._send_request("POST", endpoint, body_dict=body)

    def cancel_all_orders(self):
        """撤銷所有訂單"""
        endpoint = "/capi/v2/order/cancelAllOrders"
        body = {"cancelOrderType": "normal"} # normal 撤銷限價單
        return self._send_request("POST", endpoint, body_dict=body)