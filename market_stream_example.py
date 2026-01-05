# 情境 1: 普通限價單 (Limit Order) - 最常用
# 在價格 95000 開多 (Open Long) 0.1 顆 BTC
client.place_order(
    side=1,            # 1: 開多
    size="0.1", 
    price="95000", 
    match_price="0"    # 0: 限價
)

# 情境 2: 市價單 (Market Order) - 需搶單時用
# 直接市價平空 (Close Short) 0.1 顆 (不需價格)
client.place_order(
    side=4,            # 4: 平空
    size="0.1", 
    match_price="1"    # 1: 市價
)

# 情境 3: 帶止損的限價單 (Limit with Stop Loss)
# 開空 (Open Short) 0.5 顆，價格 98000，若漲到 99000 自動止損
client.place_order(
    side=2, 
    size="0.5", 
    price="98000", 
    match_price="0",
    preset_stop_loss="99000", # 預設止損
    margin_mode=1             # 1: 全倉模式
)

# 情境 4: FOK 快單 (Fill Or Kill) - 高頻交易用
# 全部成交否則取消，且只掛單 (Post-Only)
client.place_order(
    side=1, 
    size="10", 
    price="94500", 
    match_price="0",   # 限價
    order_type="2"     # 2: FOK (Fill or Kill)
)