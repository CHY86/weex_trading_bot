import time
import pandas as pd
from datetime import datetime
from exchange_client import WeexClient
import config

pd.set_option('display.max_columns', None)
pd.set_option('display.width', 1000)
pd.set_option('display.unicode.east_asian_width', True)

def timestamp_to_str(ts):
    if not ts: return "-"
    try:
        return datetime.fromtimestamp(int(ts) / 1000).strftime('%Y-%m-%d %H:%M:%S')
    except:
        return str(ts)

def show_assets(client):
    print("\n💰 [帳戶資金概況]")
    try:
        # [修正] 這裡取得的 res 現在會直接是一個 List
        # 例如: [{'coinName': 'USDT', 'available': '...', ...}, {...}]
        res = client.get_account_assets()
        
        target_coin = "USDT"
        found = False
        
        if isinstance(res, list):
            for asset in res:
                # 根據您的錯誤訊息，key 是 'coinName'
                if asset.get('coinName') == target_coin:
                    found = True
                    equity = float(asset.get('equity', 0))
                    available = float(asset.get('available', 0))
                    frozen = float(asset.get('frozen', 0))
                    unrealized = float(asset.get('unrealizePnl', 0)) # 注意: API 拼寫可能是 unrealizePnl
                    
                    print(f"--------------------------------------------------")
                    print(f"🪙  幣種: {target_coin}")
                    print(f"💵 總權益 (Equity):   {equity:.4f}")
                    print(f"✅ 可用餘額 (Avail):  {available:.4f}")
                    print(f"🔒 凍結保證金 (Lock): {frozen:.4f}")
                    print(f"📈 未結盈虧 (PnL):    {unrealized:.4f}")
                    print(f"--------------------------------------------------")
                    break
        
        if not found:
            print(f"⚠️ 找不到 {target_coin} 資產資料 (API回傳: {res})")
            
    except Exception as e:
        print(f"❌ 發生錯誤: {e}")

def show_open_orders(client):
    print(f"\n📋 [當前掛單/持倉] (交易對: {config.SYMBOL})")
    orders = client.get_open_orders(symbol=config.SYMBOL)
    
    if not orders:
        print("✅ 目前沒有未完成的訂單。")
        return

    data_list = []
    for o in orders:
        side_map = {'1': '開多', '2': '開空', '3': '平多', '4': '平空'}
        side_str = side_map.get(str(o.get('type')), str(o.get('type')))
        
        data_list.append({
            "時間": timestamp_to_str(o.get('createTime') or o.get('cTime')),
            "方向": side_str,
            "價格": o.get('price'),
            "數量": o.get('size'),
            "已成交": o.get('filled_qty', 0),
            "訂單ID": o.get('order_id') or o.get('orderId')
        })
    
    df = pd.DataFrame(data_list)
    print(df.to_string(index=False))

def show_history_orders(client):
    print(f"\n📜 [歷史訂單 - 最近 20 筆] (交易對: {config.SYMBOL})")
    orders = client.get_history_orders(symbol=config.SYMBOL, page_size=20)
    
    if not orders:
        print("📭 查無歷史紀錄。")
        return

    data_list = []
    for o in orders:
        side_map = {'1': '開多', '2': '開空', '3': '平多', '4': '平空'}
        side_str = side_map.get(str(o.get('type')), str(o.get('type')))
        status = o.get('status', o.get('state', '-'))
        
        data_list.append({
            "時間": timestamp_to_str(o.get('createTime') or o.get('cTime')),
            "方向": side_str,
            "委託價": o.get('price'),
            "成交均價": o.get('price_avg') or o.get('priceAvg', '-'),
            "數量": o.get('size'),
            "盈虧": o.get('totalProfits', 0),
            "狀態": status
        })
        
    df = pd.DataFrame(data_list)
    print(df.to_string(index=False))

def main():
    client = WeexClient()
    while True:
        print("\n" + "="*30)
        print("   🤖 WEEX 帳戶監控助手")
        print("="*30)
        print("1. 💰 查詢資金 (Assets)")
        print("2. 📋 查詢當前掛單 (Open Orders)")
        print("3. 📜 查詢歷史訂單 (History)")
        print("Q. 🚪 離開 (Quit)")
        
        choice = input("\n請輸入選項 (1-3/Q): ").upper().strip()
        
        if choice == '1': show_assets(client)
        elif choice == '2': show_open_orders(client)
        elif choice == '3': show_history_orders(client)
        elif choice == 'Q': break
        else: print("⚠️ 無效輸入")
        
        input("\n按 Enter 鍵繼續...")

if __name__ == "__main__":
    main()