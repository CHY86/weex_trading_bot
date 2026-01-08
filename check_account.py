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
        
        # 處理止盈止損顯示 (若無設定則顯示 -)
        tp = o.get('presetTakeProfitPrice')
        sl = o.get('presetStopLossPrice')
        tp_str = tp if tp and float(tp) > 0 else '-'
        sl_str = sl if sl and float(sl) > 0 else '-'

        data_list.append({
            "時間": timestamp_to_str(o.get('createTime') or o.get('cTime')),
            "方向": side_str,
            "委託價": o.get('price'),
            "均價": o.get('price_avg') or o.get('priceAvg', '-'),
            "已成/總量": f"{o.get('filled_qty', 0)} / {o.get('size')}",
            "止盈": tp_str,
            "止損": sl_str,
            "手續費": o.get('fee', 0),
            "盈虧": o.get('totalProfits', 0),
            "狀態": status
        })
    print(pd.DataFrame(data_list).to_string(index=False))

# --- [新增] 顯示倉位函式 ---
def show_positions(client):
    print(f"\n📊 [當前持倉詳情] (交易對: {config.SYMBOL})")
    
    positions = client.get_all_positions(symbol=config.SYMBOL)
    
    if not positions:
        print("✅ 目前沒有持倉。")
        return

    data_list = []
    for p in positions:
        # 1. 基礎資訊
        side = p.get('side', '') 
        if side == 'LONG': side = '🟢 多'
        elif side == 'SHORT': side = '🔴 空'
        
        leverage = p.get('leverage', '-')
        size = p.get('hold_vol') or p.get('size') or p.get('current_amount') or 0
        
        # 2. 價格資訊
        open_price = float(p.get('open_avg_price', 0) or p.get('open_price', 0))
        liqz_price = p.get('liquidate_price', '-')
        
        # 3. 盈虧與資金 (根據 PDF 補充更多欄位)
        unrealized = float(p.get('unrealized_pnl', 0)) # 未結盈虧
        margin_size = p.get('marginSize', 0)           # 持倉保證金
        funding_fee = p.get('funding_fee', 0)          # 待結算資金費
        cum_funding = p.get('cum_funding_fee', 0)      # 累計已付資金費
        
        # 4. 時間與模式
        create_time = timestamp_to_str(p.get('created_time') or p.get('cTime'))
        mode = p.get('margin_mode', '-') # SHARED/ISOLATED
        if mode == 'SHARED': mode = '全倉'
        elif mode == 'ISOLATED': mode = '逐倉'

        data_list.append({
            "方向": side,
            "槓桿": f"x{leverage}",
            "數量": size,
            "均價": open_price,
            "強平": liqz_price,
            "保證金": margin_size,
            "未結盈虧": f"{unrealized:.2f}",
            "資金費": funding_fee,
            "累計資金費": cum_funding,
            "模式": mode,
            "開倉時間": create_time
        })
        
    if data_list:
        df = pd.DataFrame(data_list)
        print(df.to_string(index=False))
    else:
        print("✅ 無持倉。")

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