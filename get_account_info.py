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
usdc_order_amount = 0
usdt_order_amount = 0
open_orders = client.get_orders()
for order in open_orders:
    if order['side'] == 'BUY':
        print(order)
    else:
        if order['symbol'] == 'ETHUSDT':
            usdt_order_amount += float(order['origQty'])
        elif order['symbol'] == 'ETHUSDC':
            usdc_order_amount += float(order['origQty'])

print(f"USDC order amount: {usdc_order_amount}")
print(f"USDT order amount: {usdt_order_amount}")


# client.new_order(
#     symbol='ETHUSDT',
#     side='BUY',
#     positionSide='BOTH',
#     type='LIMIT',
#     quantity=0.189,
#     priceMatch='QUEUE',
#     timeInForce='GTC',
#     reduceOnly="false"
# )