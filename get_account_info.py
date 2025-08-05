import os
from binance.um_futures import UMFutures
from dotenv import load_dotenv

load_dotenv()

client = UMFutures(
    key=os.getenv('API_KEY'),
    secret=os.getenv('API_SECRET')
)

# Get account info
account_info = client.account()

# Get account balance
total_balance = 0
for asset in account_info['assets']:
    if float(asset['walletBalance']) > 0:
        total_balance += float(asset['walletBalance'])
        total_balance += float(asset['unrealizedProfit'])

print(f"Total balance: {total_balance}")


# Get positions
position_risk = client.get_position_risk()

print("Positions:")
for position in position_risk:
    print(f"{position['symbol']}: {position['positionAmt']}")
    print(f"Unrealized PnL: {position['unRealizedProfit']}")

# Get open orders
order_amount = {}
open_orders = client.get_orders()
for order in open_orders:
    if order['symbol'] not in order_amount:
        order_amount[order['symbol']] = 0
    order_amount[order['symbol']] += float(order['origQty'])

print(f"Order amount: {order_amount}")
