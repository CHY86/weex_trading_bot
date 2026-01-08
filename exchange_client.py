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

    # --- [關鍵新增] 通用資料提取器 ---
    def _extract_data(self, response):
        """
        自動判斷 API 回傳的是 List 還是包在 Dict 裡的 data
        """
        if response is None:
            return []
            
        # 情況 1: 直接回傳 List (如 account/assets, order/current)
        if isinstance(response, list):
            return response
            
        # 情況 2: 回傳 Dict
        if isinstance(response, dict):
            # 優先檢查是否有 'data' (標準結構)
            if 'data' in response:
                data = response['data']
                # 如果 data 裡面還有 list (如 order/fills 有時會這樣)，再拆一層
                if isinstance(data, dict) and 'list' in data:
                    return data['list']
                return data
            
            # 檢查是否有 'list' (如 order/fills)
            if 'list' in response:
                return response['list']
                
            # 如果都沒有，可能它本身就是資料物件 (如 batch cancel result)
            return response
            
        return []

    def _map_interval(self, interval):
        mapping = {
            "MINUTE_1": "1m", "MINUTE_5": "5m", "MINUTE_15": "15m", "MINUTE_30": "30m",
            "HOUR_1": "1h", "HOUR_4": "4h", "HOUR_12": "12h", "DAY_1": "1d", "WEEK_1": "1w"
        }
        return mapping.get(interval, "1m")

    # --- API 功能實作 ---

    def get_server_time(self):
        return self._send_request("GET", "/capi/v2/market/time", "?symbol=" + config.SYMBOL)

    def get_history_candles(self, symbol, granularity, start_time=None, end_time=None, limit=100):
        endpoint = "/capi/v2/market/historyCandles"
        query = f"?symbol={symbol}&granularity={granularity}&limit={limit}"
        if end_time: query += f"&endTime={end_time}"
        elif start_time: query += f"&startTime={start_time}"
        
        response = self._send_request("GET", endpoint, query)
        # K線有時直接回傳 List，有時包在 data，使用 _extract_data 統一處理
        return self._extract_data(response)

    def get_account_assets(self):
        """查詢帳戶資產 (修正: 直接回傳 List)"""
        response = self._send_request("GET", "/capi/v2/account/assets")
        return self._extract_data(response)

    def get_all_positions(self, symbol=None):
        """
        查詢當前倉位 (Get All Positions)
        Ref: Get_all_position.pdf
        Endpoint: /capi/v2/account/position/allPosition
        """
        endpoint = "/capi/v2/account/position/allPosition"
        
        # 根據文件，此 API 不需要參數 (Request parameters: NONE)
        response = self._send_request("GET", endpoint)
        all_positions = self._extract_data(response)
        
        # 如果使用者有指定 symbol，我們在 Client 端幫忙過濾
        if symbol and all_positions:
            # 轉換成小寫比對比較保險，或者直接比對
            return [p for p in all_positions if p.get('symbol') == symbol]
            
        return all_positions

    def get_open_orders(self, symbol=None, order_id=None, start_time=None, end_time=None, limit=100, page=0):
        """查詢當前掛單 (修正: 根據 PDF 直接回傳 List)"""
        symbol = symbol or config.SYMBOL
        endpoint = "/capi/v2/order/current"
        query = f"?symbol={symbol}&limit={limit}&page={page}"
        if order_id: query += f"&orderId={order_id}"
        
        response = self._send_request("GET", endpoint, query)
        return self._extract_data(response)

    def get_history_orders(self, symbol=None, page_size=20, create_date=None, end_create_date=None):
        """查詢歷史訂單"""
        symbol = symbol or config.SYMBOL
        endpoint = "/capi/v2/order/history"
        query = f"?symbol={symbol}&pageSize={page_size}"
        if create_date: query += f"&createDate={create_date}"
        
        response = self._send_request("GET", endpoint, query)
        return self._extract_data(response)

    def get_fills(self, symbol=None, limit=100):
        """查詢成交明細"""
        symbol = symbol or config.SYMBOL
        endpoint = "/capi/v2/order/fills"
        query = f"?symbol={symbol}&limit={limit}"
        
        response = self._send_request("GET", endpoint, query)
        return self._extract_data(response)

    def get_order_detail(self, order_id):
        endpoint = "/capi/v2/order/detail"
        query = f"?orderId={order_id}"
        response = self._send_request("GET", endpoint, query)
        return self._extract_data(response)

    def get_account_detail(self, coin="USDT"):
        """獲取帳戶詳細資訊（含槓桿、餘額等）"""
        params = {"coin": coin}
        return self._send_request("GET", "/capi/v2/account/getAccount", params)

    def set_leverage(self, symbol, leverage, margin_mode=1):
        """
        調整槓桿數字
        marginMode: 1 (全倉 Cross), 3 (逐倉 Isolated)
        """
        data = {
            "symbol": symbol,
            "marginMode": margin_mode,
            "longLeverage": str(leverage),
            "shortLeverage": str(leverage)
        }
        return self._send_request("POST", "/capi/v2/account/leverage", data)

    # --- 交易執行 (保持不變) ---
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

    def cancel_batch_orders(self, order_ids=None):
        endpoint = "/capi/v2/order/cancel_batch_orders"
        body = {}
        if order_ids: body["ids"] = order_ids
        return self._send_request("POST", endpoint, body_dict=body)

    def upload_ai_log(self, stage, model, input_data, output_data, explanation, order_id=None):
        if not getattr(config, 'ENABLE_AI_LOG', True): return None
        endpoint = "/capi/v2/order/uploadAiLog"
        save_local_log(stage, model, input_data, output_data, explanation, order_id)
        body = {
            "stage": str(stage), "model": str(model),
            "input": input_data, "output": output_data, "explanation": str(explanation)
        }
        if order_id: body["orderId"] = str(order_id)
        return self._send_request("POST", endpoint, body_dict=body)