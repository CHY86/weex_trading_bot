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
            
            # --- [除錯修正] 檢查狀態碼，若非 200 則印出詳細錯誤 ---
            if response.status_code != 200:
                print(f"⚠️ API Error [{response.status_code}]: {response.text}")
            # --------------------------------------------------

            return response.json()
        except Exception as e:
            # 這裡會印出真正的問題 (例如: 404 Not Found)
            print(f"❌ API Request Failed. URL: {full_url}")
            print(f"❌ Response Text: {response.text if 'response' in locals() else 'No Response'}")
            print(f"❌ Error Detail: {e}")
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

    def place_order(self, side, size, price=None, match_price="0", order_type="0", 
                    client_oid=None, preset_take_profit=None, preset_stop_loss=None, margin_mode=None, extra_params=None):
        """
        下單核心函數

        Args:
            side (int): 1:開多, 2:開空, 3:平多, 4:平空
            size (str): 數量
            price (str): 價格 (限價單必填)
            match_price (str): '0'=限價(Limit), '1'=市價(Market)
            order_type (str): 訂單策略 -> '0'=普通, '1'=Post-Only(只做Maker), '2'=FOK(全成或全撤), '3'=IOC(立即成交否則撤銷)
            client_oid (str, optional): 自訂訂單ID
            preset_take_profit (str, optional): 止盈價
            preset_stop_loss (str, optional): 止損價
            margin_mode (int, optional): 1=全倉, 3=逐倉
            extra_params (dict, optional): 其他進階參數
        """
        endpoint = "/capi/v2/order/placeOrder"

        # 1. 產生或使用外部傳入的 ID
        client_oid = client_oid or self.id_gen.generate()

        # 2. 防呆檢查：限價單必須有價格
        # match_price 為 "0" 代表限價單
        if str(match_price) == "0" and not price:
            raise ValueError("❌ 錯誤: 限價單 (match_price='0') 必須輸入價格 (price)")

        # 3. 建構 Payload
        body = {
            "symbol": config.SYMBOL,
            "client_oid": str(client_oid),
            "size": str(size),
            "type": str(side),
            "order_type": str(order_type),   # 控制 FOK/IOC
            "match_price": str(match_price), # 控制 Limit/Market
        }

        if price:
            body["price"] = str(price)
        
        # 4. 處理選填參數 (轉為 API 格式 key)
        if preset_take_profit:
            body["presetTakeProfitPrice"] = str(preset_take_profit)
        if preset_stop_loss:
            body["presetStopLossPrice"] = str(preset_stop_loss)
        if margin_mode:
            body["marginMode"] = int(margin_mode)

        # 5. 合併額外參數
        if extra_params and isinstance(extra_params, dict):
            body.update(extra_params)

        print(f"🚀 下單: 方向={side} | 數量={size} | 價格={price} | 模式={match_price}")
        return self._send_request("POST", endpoint, body_dict=body)

    def cancel_all_orders(self):
        """撤銷所有訂單"""
        endpoint = "/capi/v2/order/cancelAllOrders"
        body = {"cancelOrderType": "normal"} # normal 撤銷限價單
        return self._send_request("POST", endpoint, body_dict=body)
    
    def upload_ai_log(self, stage, model, input_data, output_data, explanation, order_id=None):
        """
        上傳 AI 決策日誌
        
        Args:
            stage (str): AI 參與的階段 (例如: "Strategy Generation", "Signal Validation")
            model (str): 使用的模型名稱 (例如: "GPT-4", "Llama-3-70b")
            input_data (dict/str): 餵給 AI 的輸入資料 (Prompt, K線數據等)
            output_data (dict/str): AI 輸出的原始結果 (預測值, 建議方向等)
            explanation (str): AI 的推論解釋 (自然語言摘要)
            order_id (str, optional): 關聯的訂單 ID (若有下單則必填). Defaults to None.
        """
        endpoint = "/capi/v2/order/uploadAiLog" 
        
        # 1. [新增] 先寫入本地檔案 (雙重保險)
        save_local_log(stage, model, input_data, output_data, explanation, order_id)

        # 2. 準備上傳 API 的 Body        
        body = {
            "stage": str(stage),
            "model": str(model),
            "input": input_data,   # 這裡直接傳入 Python 物件，_send_request 會自動轉 JSON
            "output": output_data,
            "explanation": str(explanation)
        }
        
        if order_id:
            body["orderId"] = str(order_id)
            
        print(f"📝 上傳 AI Log: [{stage}] {explanation[:30]}...")
        return self._send_request("POST", endpoint, body_dict=body)