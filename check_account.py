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
        
        # 3. 盈虧與資金
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

# --- 查看帳戶詳情 (含槓桿) ---
def check_account_detail(client):
    print(f"\n🔍 正在獲取 {config.SYMBOL} 帳戶詳情...")
    res = client.get_account_detail(coin="USDT")
    
    # 檢查是否包含 account 物件
    if res and 'account' in res:
        acc = res['account']
        collateral_list = res.get('collateral', [])
        
        print("\n" + "=" * 50)
        print(f"📄 帳戶詳細資訊報告 (Symbol: {config.SYMBOL})")
        print("=" * 50)

        # 1. 手續費設定 (Fee Settings)
        print(f"\n[1] 💸 手續費設定")
        
        # 預設手續費
        def_fee = acc.get('defaultFeeSetting', {})
        print(f"  • 預設 Taker 費率: {def_fee.get('taker_fee_rate', 'N/A')}")
        print(f"  • 預設 Maker 費率: {def_fee.get('maker_fee_rate', 'N/A')}")
        
        # 針對當前交易對的手續費
        fee_settings = acc.get('feeSetting', [])
        target_fee = next((f for f in fee_settings if f.get('symbol') == config.SYMBOL), None)
        if target_fee:
            print(f"  • {config.SYMBOL} Taker: {target_fee.get('taker_fee_rate')}")
            print(f"  • {config.SYMBOL} Maker: {target_fee.get('maker_fee_rate')}")
        else:
            print(f"  • {config.SYMBOL} 專屬設定: 未找到 (使用預設)")

        # 2. 槓桿與模式 (Leverage & Mode)
        print(f"\n[2] ⚙️ 槓桿與倉位模式 ({config.SYMBOL})")
        
        # 槓桿設定
        lev_settings = acc.get('leverageSetting', [])
        target_lev = next((l for l in lev_settings if l.get('symbol') == config.SYMBOL), {})
        
        print(f"  • 全倉槓桿 (Cross): x{target_lev.get('cross_leverage', 'N/A')}")
        print(f"  • 逐倉長倉 (Long):  x{target_lev.get('isolated_long_leverage', 'N/A')}")
        print(f"  • 逐倉短倉 (Short): x{target_lev.get('isolated_short_leverage', 'N/A')}")

        # 模式設定
        mode_settings = acc.get('modeSetting', [])
        target_mode = next((m for m in mode_settings if m.get('symbol') == config.SYMBOL), {})
        
        m_mode = target_mode.get('marginMode', 'N/A')
        p_mode = target_mode.get('positionModeEnum', 'N/A')
        print(f"  • 保證金模式: {m_mode} ({'全倉' if m_mode == 'SHARED' else '逐倉'})")
        print(f"  • 持倉模式:   {p_mode}")

        # 3. 資金與抵押品詳情 (Collateral - USDT)
        print(f"\n[3] 💰 資金詳情 (USDT)")
        usdt_assets = next((c for c in collateral_list if c.get('coin') == 'USDT'), {})
        
        if usdt_assets:
            print(f"  • 當前餘額 (Amount):      {usdt_assets.get('amount')}")
            print(f"  • 凍結金額 (Legacy):      {usdt_assets.get('legacy_amount')}")
            print(f"  • 累計充值 (Deposit):     {usdt_assets.get('cum_deposit_amount')}")
            print(f"  • 累計提現 (Withdraw):    {usdt_assets.get('cum_withdraw_amount')}")
            print(f"  • 累計已付資金費:         {usdt_assets.get('cum_position_funding_amount')}")
            print(f"  • 累計強平手續費:         {usdt_assets.get('cum_position_liquidate_fee_amount')}")
            print(f"  • 累計已實現盈虧(多):     {usdt_assets.get('cum_position_close_long_amount')}")
            print(f"  • 累計已實現盈虧(空):     {usdt_assets.get('cum_position_close_short_amount')}")
        else:
            print("  • 無 USDT 資產資料")

        # 4. 其他帳戶資訊
        print(f"\n[4] ℹ️ 其他資訊")
        print(f"  • 帳戶建立時間: {timestamp_to_str(acc.get('createdTime'))}")
        print(f"  • 最後更新時間: {timestamp_to_str(acc.get('updatedTime'))}")
        
        print("=" * 50)
    else:
        print(f"❌ 無法獲取詳細資訊，API 回傳內容: {res}")

# --- 調整槓桿 ---
def modify_leverage(client):
    print(f"\n🔧 準備調整 {config.SYMBOL} 的槓桿設定")
    print("注意：此操作預設使用「全倉模式 (Cross)」進行調整。")
    
    new_lev = input(f"請輸入新的槓桿倍數 (例如 10, 20): ").strip()
    
    if not new_lev.isdigit():
        print("⚠️ 請輸入有效的整數數字！")
        return

    try:
        # 呼叫 API 調整槓桿
        res = client.set_leverage(symbol=config.SYMBOL, leverage=int(new_lev), margin_mode=1)
        
        if res and res.get('code') == '00000':
            print(f"✅ 成功！{config.SYMBOL} 槓桿已調整為 x{new_lev}")
        else:
            print(f"❌ 調整失敗: {res.get('msg', '未知錯誤')}")
            # 如果失敗，通常是因為有持倉或掛單，提示使用者
            print("💡 提示：若有未平倉位或掛單，交易所通常禁止調整槓桿。")
    except Exception as e:
        print(f"❌ 發生錯誤: {e}")

# --- 一鍵平倉---
def close_all_positions_ui(client):
    print(f"\n🚨 [危險操作] 一鍵平倉 (Market Close All)")
    print(f"1. 僅平倉當前交易對 ({config.SYMBOL})")
    print(f"2. 平倉帳戶內【所有】交易對 (ALL Symbols)")
    print("0. 取消")
    
    choice = input("請選擇範圍 (1/2/0): ").strip()
    
    target_symbol = None
    if choice == '1':
        target_symbol = config.SYMBOL
        print(f"⚠️  警告：即將以【市價】平倉 {target_symbol} 的所有持倉！")
    elif choice == '2':
        target_symbol = None
        print(f"⚠️  警告：即將以【市價】平倉【整個帳戶】的所有持倉！")
    else:
        print("已取消。")
        return

    # 二次確認防止誤觸
    confirm = input("請輸入 'YES' 確認執行: ")
    if confirm == 'YES':
        print("🚀 正在發送平倉請求...")
        res = client.close_all_positions(symbol=target_symbol)
        
        # 解析回傳結果 (API 回傳的是一個 List)
        if isinstance(res, list):
            print("\n✅ 執行結果:")
            for item in res:
                pid = item.get('positionId')
                is_success = item.get('success')
                err_msg = item.get('errorMessage')
                oid = item.get('successOrderId')
                
                status_icon = "🟢 成功" if is_success else "🔴 失敗"
                detail = f"Order ID: {oid}" if is_success else f"原因: {err_msg}"
                print(f"  • 持倉ID {pid}: {status_icon} | {detail}")
                
        elif isinstance(res, dict) and 'msg' in res:
             # 若 API 直接回傳錯誤物件
             print(f"❌ API 回傳訊息: {res.get('msg')}")
        else:
             print(f"❓ 未知回傳格式: {res}")
    else:
        print("❌ 未輸入 YES，操作取消。")

def cancel_all_orders_ui(client):
    print(f"\n🗑️  [操作] 撤銷所有掛單 (Cancel All Orders)")
    print(f"1. 僅撤銷當前交易對 ({config.SYMBOL}) 的普通掛單")
    print(f"2. 撤銷帳戶內【所有】交易對的普通掛單")
    print("0. 取消")
    
    choice = input("請選擇範圍 (1/2/0): ").strip()
    
    target_symbol = None
    if choice == '1':
        target_symbol = config.SYMBOL
        print(f"⚠️  準備撤銷 {target_symbol} 的所有普通掛單...")
    elif choice == '2':
        target_symbol = None
        print(f"⚠️  準備撤銷【所有交易對】的普通掛單...")
    else:
        print("已取消。")
        return

    # 二次確認
    confirm = input("請輸入 'YES' 確認執行: ")
    if confirm == 'YES':
        print("🚀 正在發送撤單請求...")
        # 預設撤銷 normal (普通限價/市價單)
        res = client.cancel_all_orders(symbol=target_symbol, cancel_order_type="normal")
        
        # 解析回傳結果
        if isinstance(res, list):
            if not res:
                print("✅ 指令已發送 (無回傳內容，可能無掛單可撤)")
            else:
                print(f"\n✅ 成功撤銷 {len(res)} 筆訂單:")
                for item in res:
                    oid = item.get('orderId')
                    is_success = item.get('success')
                    status_icon = "🟢 成功" if is_success else "🔴 失敗"
                    print(f"  • OrderID {oid}: {status_icon}")
                    
        elif isinstance(res, dict) and 'msg' in res:
             print(f"❌ API 回傳訊息: {res.get('msg')}")
        else:
             print(f"❓ API 回傳格式: {res}")
    else:
        print("❌ 未輸入 YES，操作取消。")

def main():
    client = WeexClient()
    while True:
        print("\n" + "="*30)
        print("   🤖 WEEX 帳戶監控助手")
        print("="*30)
        print("1. 💰 查詢資金 (Assets)")
        print("2. 📋 查詢當前掛單 (Open Orders)")
        print("3. 📜 查詢歷史訂單 (History)")
        print("4. 📊 查詢當前倉位 (Positions)")
        print("5. ℹ️  查看帳戶詳情 & 槓桿")
        print("6. 🔧 調整槓桿倍數 ")
        print("7. 🚨 一鍵全平倉 (Close All) [NEW]")
        print("8. 🗑️  撤銷所有掛單 (Cancel Orders) [NEW]")
        print("Q. 🚪 離開 (Quit)")
        
        choice = input("\n請輸入選項 (1-6/Q): ").upper().strip()
        
        if choice == '1': show_assets(client)
        elif choice == '2': show_open_orders(client)
        elif choice == '3': show_history_orders(client)
        elif choice == '4': show_positions(client)
        elif choice == '5': check_account_detail(client)
        elif choice == '6': modify_leverage(client)
        elif choice == '7': close_all_positions_ui(client)
        elif choice == '8': cancel_all_orders_ui(client)
        elif choice == 'Q': break
        else: print("⚠️ 無效輸入")
        
        input("\n按 Enter 鍵繼續...")

if __name__ == "__main__":
    main()