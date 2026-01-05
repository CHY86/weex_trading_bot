import unittest
from unittest.mock import MagicMock
import json

# 模擬 config 模組，避免讀取真實檔案
class MockConfig:
    SYMBOL = "cmt_btcusdt"
    REST_URL = "https://mock.api"
    API_KEY = "mock_key"
    SECRET_KEY = "mock_secret"
    PASSPHRASE = "mock_pass"

import sys
# 將模擬的 config 注入 sys.modules，這樣 exchange_client 匯入時就會用到它
sys.modules['config'] = MockConfig

# 匯入你的 WeexClient (假設檔案名為 exchange_client.py)
from exchange_client import WeexClient

class TestWeexOrder(unittest.TestCase):
    def setUp(self):
        self.client = WeexClient()
        # 覆寫 _send_request 方法，讓它直接回傳 payload 而不是發送請求
        self.client._send_request = MagicMock(side_effect=lambda method, endpoint, query_params="", body_dict=None: body_dict)

    def test_limit_buy(self):
        """測試 1: 普通限價開多"""
        print("\n--- 測試 1: 普通限價開多 ---")
        
        # 執行下單
        body = self.client.place_order(side=1, size="0.5", price="50000", match_price="0")
        
        # 驗證 Body 內容
        print(f"Generated Body: {json.dumps(body, indent=2)}")
        self.assertEqual(body['type'], "1")           # 開多
        self.assertEqual(body['match_price'], "0")    # 限價
        self.assertEqual(body['price'], "50000")      # 價格
        self.assertEqual(body['order_type'], "0")     # 普通單

    def test_market_sell(self):
        """測試 2: 市價平多"""
        print("\n--- 測試 2: 市價平多 ---")
        
        body = self.client.place_order(side=3, size="1.0", match_price="1")
        
        print(f"Generated Body: {json.dumps(body, indent=2)}")
        self.assertEqual(body['type'], "3")           # 平多
        self.assertEqual(body['match_price'], "1")    # 市價
        self.assertNotIn('price', body)               # 市價單不應有 price 欄位 (或 API 允許忽略)

    def test_fok_order_with_sl(self):
        """測試 3: 帶止損的 FOK 單"""
        print("\n--- 測試 3: 帶止損的 FOK 單 ---")
        
        body = self.client.place_order(
            side=2, 
            size="2.0", 
            price="60000", 
            match_price="0", 
            order_type="2",           # FOK
            preset_stop_loss="61000", 
            margin_mode=1
        )
        
        print(f"Generated Body: {json.dumps(body, indent=2)}")
        self.assertEqual(body['order_type'], "2")             # FOK
        self.assertEqual(body['presetStopLossPrice'], "61000") # 止損
        self.assertEqual(body['marginMode'], 1)               # 全倉

if __name__ == '__main__':
    # 這裡我們需要先「更新」你的 place_order 到 WeexClient 類別中
    # (因為你原本的檔案可能還是舊的，這邊動態替換成新版函式以供測試)
    
    def new_place_order(self, side, size, price=None, match_price="0", order_type="0", 
                        client_oid=None, preset_take_profit=None, preset_stop_loss=None, margin_mode=None, extra_params=None):
        # ... (這裡貼上融合優化版的程式碼) ...
        # 為節省篇幅，這裡直接模擬上面討論的邏輯
        client_oid = client_oid or self.id_gen.generate()
        if str(match_price) == "0" and not price:
            raise ValueError("Limit order requires price")
            
        body = {
            "symbol": MockConfig.SYMBOL,
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
        
        return self._send_request("POST", "/capi/v2/order/placeOrder", body_dict=body)

    # 動態替換 (Monkey Patch)
    WeexClient.place_order = new_place_order

    # 執行測試
    unittest.main()