#!/usr/bin/env python3
"""
Telegram Bot for Binance Trading Bot Account Overview - Hourly Reports
"""

import os
import csv
import logging
import asyncio
import schedule
import time
from datetime import datetime, timedelta
from typing import Dict
from binance.um_futures import UMFutures
from telegram import Bot
import dotenv

dotenv.load_dotenv()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


class BinanceAccountAnalyzer:
    """Analyze Binance account data and transaction logs"""

    def __init__(self, api_key: str, api_secret: str):
        self.client = UMFutures(api_key, api_secret)

    def get_account_overview(self) -> Dict:
        """Get current account balance, unrealized PnL, positions"""
        try:
            account_positions = self.client.get_position_risk()
            # Get current positions
            positions = []

            for position in account_positions:
                if float(position['positionAmt']) != 0:  # Only active positions
                    positions.append({
                        'symbol': position['symbol'],
                        'size': float(position['positionAmt']),
                        'unrealized_pnl': float(position['unRealizedProfit']),
                        'entry_price': float(position['entryPrice']),
                        'mark_price': float(position['markPrice']),
                        'liquidation_price': float(position['liquidationPrice'])
                    })

            # Get account information
            account_info = self.client.account()

            # Get account balance
            total_balance = 0
            for asset in account_info['assets']:
                if float(asset['walletBalance']) > 0:
                    total_balance += float(asset['walletBalance'])
                    total_balance += float(asset['unrealizedProfit'])

            # Calculate total unrealized PnL
            total_unrealized_pnl = sum(pos['unrealized_pnl'] for pos in positions)

            return {
                'total_balance': total_balance,
                'total_unrealized_pnl': total_unrealized_pnl,
                'positions': positions
            }

        except Exception as e:
            logger.error(f"Error getting account overview: {e}")
            return {
                'total_balance': 0,
                'total_unrealized_pnl': 0,
                'positions': []
            }


class TransactionLogAnalyzer:
    """Analyze transaction log CSV files"""

    def __init__(self):
        pass

    def analyze_transactions(self, symbol: str, time_period: timedelta) -> Dict:
        """Analyze transaction log for given symbol and time period"""
        csv_file = f"{symbol}_transactions_log.csv"

        if not os.path.exists(csv_file):
            return {
                'num_trades': 0,
                'realized_pnl': 0.0,
                'total_volume': 0.0
            }

        # Calculate cutoff time
        cutoff_time = datetime.now() - time_period

        num_trades = 0
        realized_pnl = 0.0
        total_volume = 0.0

        try:
            with open(csv_file, 'r') as file:
                reader = csv.reader(file)
                for row in reader:
                    if len(row) < 8:  # Need at least 8 columns
                        continue

                    # Parse timestamp (column 0)
                    try:
                        timestamp_str = row[0]
                        # Handle different timestamp formats
                        if 'T' in timestamp_str and '+' in timestamp_str:
                            # ISO format with timezone
                            timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                        else:
                            # Try parsing as regular datetime
                            timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
                    except Exception:
                        continue

                    # Check if within time period
                    if timestamp < cutoff_time:
                        continue

                    # Parse transaction data
                    try:
                        # CSV format: datetime, symbol, orderid, order_type, counter_order, price, amount, status
                        counter_order = row[4]  # Counter order ID (if filled, this has a value)
                        price = float(row[5]) if row[5] else 0
                        amount = float(row[6]) if row[6] else 0
                        status = row[7] if len(row) > 7 else ''

                        # Only count FILLED transactions
                        if status == 'FILLED':
                            num_trades += 1
                            # Volume = price * amount
                            total_volume += abs(price * amount)

                            # Realized PnL: if counter_order has a value, it's a realized trade
                            if counter_order and counter_order.strip():
                                # This is a realized trade (OPEN with counter order or CLOSE with counter order)
                                realized_pnl += 0.5 * amount

                    except (ValueError, IndexError):
                        continue

        except Exception as e:
            logger.error(f"Error analyzing transaction log {csv_file}: {e}")

        return {
            'num_trades': num_trades,
            'realized_pnl': realized_pnl,
            'total_volume': total_volume
        }


class HourlyReporter:
    """Send hourly account overview reports via Telegram"""

    def __init__(self, token: str, chat_id: str, api_key: str, api_secret: str):
        self.token = token
        self.chat_id = chat_id
        self.bot = Bot(token=token)
        self.account_analyzer = BinanceAccountAnalyzer(api_key, api_secret)
        self.transaction_analyzer = TransactionLogAnalyzer()

    async def send_hourly_report(self):
        """Send hourly account overview report"""
        try:
            logger.info("Generating hourly report...")

            # Get account overview from Binance
            account_data = self.account_analyzer.get_account_overview()

            # Analyze transaction logs for all available symbols
            transaction_data = {}
            for filename in os.listdir('.'):
                if filename.endswith('_transactions_log.csv'):
                    symbol = filename.replace('_transactions_log.csv', '')
                    # Analyze last 1 hour for hourly reports
                    transaction_data[symbol] = self.transaction_analyzer.analyze_transactions(
                        symbol, timedelta(hours=1)
                    )

            # Get 24-hour totals for summary
            transaction_data_24h = {}
            for filename in os.listdir('.'):
                if filename.endswith('_transactions_log.csv'):
                    symbol = filename.replace('_transactions_log.csv', '')
                    transaction_data_24h[symbol] = self.transaction_analyzer.analyze_transactions(
                        symbol, timedelta(hours=24)
                    )

            # Format response message
            response = self._format_hourly_report(account_data, transaction_data, transaction_data_24h)

            # Send message
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=response,
                parse_mode='Markdown'
            )

            logger.info("Hourly report sent successfully")

        except Exception as e:
            logger.error(f"Error sending hourly report: {e}")

    def _format_hourly_report(self, account_data: Dict, transaction_data: Dict, transaction_data_24h: Dict) -> str:
        """Format the hourly report message"""
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        response = f"🕐 *Hourly Report - {current_time}*\n\n"

        # Account balance and PnL
        response += f"💰 *Account Balance:* ${account_data['total_balance']:.2f}\n"
        response += f"📈 *Unrealized PnL:* ${account_data['total_unrealized_pnl']:.2f}\n\n"

        # Current positions
        if account_data['positions']:
            response += "📋 *Current Positions:*\n"
            for pos in account_data['positions']:
                pnl_color = "🟢" if pos['unrealized_pnl'] >= 0 else "🔴"
                response += f"{pnl_color} {pos['symbol']}: {pos['size']:.4f} @ ${pos['entry_price']:.2f}\n"
                response += f"   Mark: ${pos['mark_price']:.2f} | PnL: ${pos['unrealized_pnl']:.2f}\n\n"
        else:
            response += "📋 *Current Positions:* None\n\n"

        # Trading activity (last 1 hour)
        if transaction_data:
            response += "📈 *Trading Activity (Last 1h):*\n"
            total_trades = 0
            total_realized_pnl = 0.0
            total_volume = 0.0

            for symbol, data in transaction_data.items():
                if data['num_trades'] > 0:
                    total_trades += data['num_trades']
                    total_realized_pnl += data['realized_pnl']
                    total_volume += data['total_volume']

                    pnl_color = "🟢" if data['realized_pnl'] >= 0 else "🔴"
                    response += f"{pnl_color} {symbol}:\n"
                    response += f"   Trades: {data['num_trades']}\n"
                    response += f"   Realized PnL: ${data['realized_pnl']:.2f}\n"
                    response += f"   Volume: ${data['total_volume']:.2f}\n\n"

            if total_trades > 0:
                response += "📊 *Totals (1h):*\n"
                response += f"   Total Trades: {total_trades}\n"
                response += f"   Total Realized PnL: ${total_realized_pnl:.2f}\n"
                response += f"   Total Volume: ${total_volume:.2f}\n"
            else:
                response += "No trading activity in the last hour.\n"

            # Add 24-hour totals
            total_trades_24h = 0
            total_realized_pnl_24h = 0.0
            total_volume_24h = 0.0

            for symbol, data in transaction_data_24h.items():
                if data['num_trades'] > 0:
                    total_trades_24h += data['num_trades']
                    total_realized_pnl_24h += data['realized_pnl']
                    total_volume_24h += data['total_volume']

            if total_trades_24h > 0:
                response += "\n📊 *Totals (24h):*\n"
                response += f"   Total Trades: {total_trades_24h}\n"
                response += f"   Total Realized PnL: ${total_realized_pnl_24h:.2f}\n"
                response += f"   Total Volume: ${total_volume_24h:.2f}\n"
        else:
            response += "📈 *Trading Activity:* No transaction logs found.\n"

        return response

    def run_scheduler(self):
        """Run the hourly scheduler"""
        # Schedule hourly reports
        schedule.every().hour.at(":00").do(self._run_async_report)

        logger.info("Hourly reporter started. Reports will be sent every hour at :00")

        # Send initial report
        asyncio.run(self.send_hourly_report())

        # Keep the scheduler running
        while True:
            schedule.run_pending()
            time.sleep(60)  # Check every minute

    def _run_async_report(self):
        """Wrapper to run async function in scheduler"""
        asyncio.run(self.send_hourly_report())


def main():
    """Main function"""
    # Get environment variables
    telegram_token = os.getenv('TELEGRAM_BOT_TOKEN')
    telegram_chat_id = os.getenv('TELEGRAM_CHAT_ID')
    binance_api_key = os.getenv('API_KEY')
    binance_api_secret = os.getenv('API_SECRET')

    if not telegram_token:
        logger.error("TELEGRAM_BOT_TOKEN environment variable not set")
        return

    if not telegram_chat_id:
        logger.error("TELEGRAM_CHAT_ID environment variable not set")
        return

    if not binance_api_key or not binance_api_secret:
        logger.error("API_KEY and API_SECRET environment variables not set")
        return

    # Create and run hourly reporter
    reporter = HourlyReporter(telegram_token, telegram_chat_id, binance_api_key, binance_api_secret)
    reporter.run_scheduler()


if __name__ == "__main__":
    main()
