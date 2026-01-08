import time
import pandas as pd
from datetime import datetime
from exchange_client import WeexClient
import config

# 設定 pandas 顯示選項
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
        res = client.get_account_assets()
        target_coin = "USDT"
        found = False
        
        if isinstance(res, list):
            for asset in res:
                if asset.get('coinName') == target_coin:
                    found = True
                    equity = float(asset.get('equity', 0))
                    available = float(asset.get('available', 0))
                    frozen = float(asset.get('frozen', 0))
                    unrealized = float(asset.get('unrealizePnl', 0))
                    
                    print(f"--------------------------------------------------")
                    print(f"🪙  幣種: {target_coin}")
                    print(f"💵 總權益 (Equity):   {equity:.4f}")
                    print(f"✅ 可用餘額 (Avail):  {available:.4f}")
                    print(f"🔒 凍結保證金 (Lock): {frozen:.4f}")
                    print(f"📈 未結盈虧 (PnL):    {unrealized:.4f}")
                    print(f"--------------------------------------------------")
                    break
        
        if not found:
            print(f"⚠️ 找不到 {target_coin} 資產資料")
    except Exception as e:
        print(f"❌ 發生錯誤: {e}")

def show_open_orders(client):
    print(f"\n📋 [當前掛單] (交易對: {config.SYMBOL})")
    orders = client.get_open_orders(symbol=config.SYMBOL)
    if not orders:
        print("✅ 無掛單。")
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
            "已成": o.get('filled_qty', 0),
            "訂單ID": o.get('order_id') or o.get('orderId')
        })
    print(pd.DataFrame(data_list).to_string(index=False))

def show_history_orders(client):
    print(f"\n📜 [歷史訂單 - 近20筆] (交易對: {config.SYMBOL})")
    orders = client.get_history_orders(symbol=config.SYMBOL, page_size=20)
    if not orders:
        print("📭 無歷史紀錄。")
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
    print(pd.DataFrame(data_list).to_string(index=False))

# --- [新增] 顯示倉位函式 ---
def show_positions(client):
    print(f"\n📊 [當前持倉] (交易對: {config.SYMBOL})")
    
    # 呼叫 API (只過濾出 config.SYMBOL 的倉位)
    positions = client.get_all_positions(symbol=config.SYMBOL)
    
    if not positions:
        print("✅ 目前沒有持倉。")
        return

    data_list = []
    for p in positions:
        # 根據 Get_all_position.pdf 解析欄位
        # 注意: 如果持倉量是 0，通常代表沒倉位 (有些交易所會回傳空倉資料)
        # 這裡我們假設 API 回傳的就是有意義的倉位
        
        # 方向
        side = p.get('side', '') # LONG / SHORT
        if side == 'LONG': side = '🟢 多單'
        elif side == 'SHORT': side = '🔴 空單'
        
        # 槓桿
        leverage = p.get('leverage', '-')
        
        # 開倉均價
        open_price = float(p.get('open_avg_price', 0) or p.get('open_price', 0))
        
        # 未結盈虧
        unrealized = float(p.get('unrealized_pnl', 0))
        
        # 預估強平價
        liqz_price = p.get('liquidate_price', '-')
        
        # 持倉數量 (這欄位名稱各家不同，常見有 hold_vol, size, current_amount)
        # 根據 snippet，可能是 hold_vol 或 cum_open_size - cum_close_size
        # 這裡嘗試讀取常見欄位
        size = p.get('hold_vol') or p.get('size') or p.get('current_amount') or 0
        
        data_list.append({
            "方向": side,
            "槓桿": f"x{leverage}",
            "數量": size,
            "開倉價": open_price,
            "未結盈虧 (UPnL)": unrealized,
            "強平價": liqz_price,
            "模式": p.get('margin_mode', '-')
        })
        
    if data_list:
        df = pd.DataFrame(data_list)
        print(df.to_string(index=False))
    else:
        print("✅ 目前沒有持倉 (API 回傳空列表)。")

def main():
    client = WeexClient()
    while True:
        print("\n" + "="*30)
        print("   🤖 WEEX 帳戶監控助手")
        print("="*30)
        print("1. 💰 查詢資金 (Assets)")
        print("2. 📋 查詢當前掛單 (Open Orders)")
        print("3. 📜 查詢歷史訂單 (History)")
        print("4. 📊 查詢當前倉位 (Positions) [NEW]")
        print("Q. 🚪 離開 (Quit)")
        
        choice = input("\n請輸入選項 (1-4/Q): ").upper().strip()
        
        if choice == '1': show_assets(client)
        elif choice == '2': show_open_orders(client)
        elif choice == '3': show_history_orders(client)
        elif choice == '4': show_positions(client)
        elif choice == 'Q': break
        else: print("⚠️ 無效輸入")
        
        input("\n按 Enter 鍵繼續...")

if __name__ == "__main__":
    main()