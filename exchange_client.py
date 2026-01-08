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

    # --- 工具函數 ---

    def _map_interval(self, interval):
        """將 WebSocket 用的 interval 字串映射為 REST API 格式"""
        mapping = {
            "MINUTE_1": "1m",
            "MINUTE_5": "5m",
            "MINUTE_15": "15m",
            "MINUTE_30": "30m",
            "HOUR_1": "1h",
            "HOUR_4": "4h",
            "HOUR_12": "12h"
        }
        return mapping.get(interval, "1m") # 預設 1m

    # --- K 線與行情 ---
    
    def get_server_time(self):
        return self._send_request("GET", "/capi/v2/market/time", "?symbol=" + config.SYMBOL)

    def get_history_candles(self, symbol, granularity, start_time=None, end_time=None, limit=100):
        """獲取歷史 K 線"""
        endpoint = "/capi/v2/market/historyCandles"
        query = f"?symbol={symbol}&granularity={granularity}&limit={limit}"
        if end_time: query += f"&endTime={end_time}"
        elif start_time: query += f"&startTime={start_time}"
        
        response = self._send_request("GET", endpoint, query)
        
        # 兼容 List 或 Dict 回傳格式
        if isinstance(response, list): return response
        if isinstance(response, dict) and "data" in response: return response["data"]
        return []

    # --- 帳戶與訂單查詢 (根據 PDF 文件實作) ---

    def get_account_assets(self):
        """查詢帳戶資產"""
        return self._send_request("GET", "/capi/v2/account/assets")

    def get_open_orders(self, symbol=None, order_id=None, start_time=None, end_time=None, limit=100, page=1):
        """
        查詢當前掛單 (Get Current Orders)
        Ref: get_current_order.pdf
        """
        symbol = symbol or config.SYMBOL
        endpoint = "/capi/v2/order/current"
        query = f"?symbol={symbol}&limit={limit}&page={page}"
        
        if order_id: query += f"&orderId={order_id}"
        if start_time: query += f"&startTime={start_time}"
        if end_time: query += f"&endTime={end_time}"
        
        response = self._send_request("GET", endpoint, query)
        if response and "data" in response:
            return response["data"]
        return []

    def get_history_orders(self, symbol=None, page_size=20, create_date=None, end_create_date=None):
        """
        查詢歷史訂單 (Get History Orders)
        Ref: get_history_order.pdf
        注意: 查詢範圍必須 <= 90 天
        """
        symbol = symbol or config.SYMBOL
        endpoint = "/capi/v2/order/history"
        query = f"?symbol={symbol}&pageSize={page_size}"
        
        # PDF 參數名為 createDate, endCreateDate
        if create_date: query += f"&createDate={create_date}"
        if end_create_date: query += f"&endCreateDate={end_create_date}"
        
        response = self._send_request("GET", endpoint, query)
        if response and "data" in response:
            data = response["data"]
            # 兼容分頁結構
            if isinstance(data, dict) and "list" in data:
                return data["list"]
            return data
        return []

    def get_fills(self, symbol=None, order_id=None, start_time=None, end_time=None, limit=100):
        """
        查詢成交明細 (Get Fills)
        Ref: get_fills.pdf
        """
        symbol = symbol or config.SYMBOL
        endpoint = "/capi/v2/order/fills"
        query = f"?symbol={symbol}&limit={limit}"
        
        if order_id: query += f"&orderId={order_id}"
        if start_time: query += f"&startTime={start_time}"
        if end_time: query += f"&endTime={end_time}"
        
        response = self._send_request("GET", endpoint, query)
        if response and "data" in response:
            data = response["data"]
            if isinstance(data, dict) and "list" in data:
                return data["list"]
            return data
        return []

    def get_order_detail(self, order_id):
        """
        查詢單筆訂單詳情 (Get Order Info)
        Ref: get_order_info.pdf
        """
        endpoint = "/capi/v2/order/detail"
        query = f"?orderId={order_id}"
        
        response = self._send_request("GET", endpoint, query)
        if response and "data" in response:
            return response["data"]
        return None

    # --- 交易執行 ---

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

    def cancel_all_orders(self):
        """撤銷所有訂單"""
        endpoint = "/capi/v2/order/cancelAllOrders"
        body = {"symbol": config.SYMBOL} 
        return self._send_request("POST", endpoint, body_dict=body)

    def cancel_batch_orders(self, order_ids=None, client_oids=None):
        """
        批量撤單 (Batch Cancel)
        Ref: batch_cancel_order.pdf
        """
        endpoint = "/capi/v2/order/cancel_batch_orders"
        body = {}
        if order_ids: body["ids"] = order_ids
        if client_oids: body["cids"] = client_oids
            
        return self._send_request("POST", endpoint, body_dict=body)

    def upload_ai_log(self, stage, model, input_data, output_data, explanation, order_id=None):
        if not getattr(config, 'ENABLE_AI_LOG', True):
            print(f"🚫 [AI Log 跳過] Config 已關閉上傳")
            return None

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