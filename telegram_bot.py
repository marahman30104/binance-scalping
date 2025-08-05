#!/usr/bin/env python3
"""
Telegram Bot for Binance Trading Bot Account Overview - Hourly Reports
"""

import os
import csv
import logging
import time
import requests
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List
import pytz
from binance.um_futures import UMFutures
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
    """Analyze transaction log CSV files using pandas"""

    def __init__(self):
        # Get timezone from environment variable, default to UTC
        timezone_name = os.getenv('TIMEZONE', 'UTC')
        self.timezone = pytz.timezone(timezone_name)

    def _load_transaction_df(self, symbol: str) -> pd.DataFrame:
        """Load transaction log CSV as pandas DataFrame"""
        csv_file = f"{symbol}_transactions_log.csv"
        
        if not os.path.exists(csv_file):
            return pd.DataFrame()
        
        try:
            # Read CSV with pandas
            df = pd.read_csv(csv_file)
            
            # Ensure we have the required columns
            if len(df.columns) < 8:
                logger.warning(f"CSV file {csv_file} has insufficient columns")
                return pd.DataFrame()
            
            # Rename columns for clarity (assuming format: datetime, symbol, orderid, order_type, counter_order, price, amount, status)
            df.columns = ['datetime', 'symbol', 'orderid', 'order_type', 'counter_order', 'price', 'amount', 'status']
            
            # Convert datetime column
            df['datetime'] = pd.to_datetime(df['datetime'], errors='coerce')
            
            # Convert numeric columns
            df['price'] = pd.to_numeric(df['price'], errors='coerce')
            df['amount'] = pd.to_numeric(df['amount'], errors='coerce')
            
            # Filter only FILLED transactions
            df = df[df['status'] == 'FILLED'].copy()
            
            return df
            
        except Exception as e:
            logger.error(f"Error loading transaction log {csv_file}: {e}")
            return pd.DataFrame()

    def get_last_trade_time(self, symbol: str) -> datetime:
        """Get the last trade time for a specific symbol using pandas"""
        df = self._load_transaction_df(symbol)
        
        if df.empty:
            return None
        
        # Get the latest datetime
        last_trade_time = df['datetime'].max()
        
        if pd.isna(last_trade_time):
            return None
            
        # Convert to timezone-aware datetime if needed
        if last_trade_time.tz is None:
            last_trade_time = self.timezone.localize(last_trade_time)
            
        return last_trade_time

    def analyze_transactions(self, symbol: str, time_period: timedelta) -> Dict:
        """Analyze transaction log for given symbol and time period using pandas"""
        df = self._load_transaction_df(symbol)
        
        if df.empty:
            return {
                'num_trades': 0,
                'realized_pnl': 0.0,
                'total_volume': 0.0
            }

        # Calculate cutoff time in timezone
        now_with_timezone = datetime.now(self.timezone)
        cutoff_time = now_with_timezone - time_period

        # Filter transactions within time period
        df_filtered = df[df['datetime'] >= cutoff_time].copy()
        
        if df_filtered.empty:
            return {
                'num_trades': 0,
                'realized_pnl': 0.0,
                'total_volume': 0.0
            }

        # Calculate metrics
        num_trades = len(df_filtered)
        total_volume = (df_filtered['price'] * df_filtered['amount']).abs().sum()
        
        # Calculate realized PnL (trades with counter_order)
        realized_trades = df_filtered[df_filtered['counter_order'].notna() & (df_filtered['counter_order'] != '')]
        realized_pnl = (realized_trades['amount'] * 0.5).sum()  # Assuming 0.5 multiplier for realized trades
        
        # Get last trade time
        last_trade_time = df_filtered['datetime'].max()
        if pd.isna(last_trade_time):
            last_trade_time = None

        return {
            'num_trades': num_trades,
            'realized_pnl': realized_pnl,
            'total_volume': total_volume,
            'last_trade_time': last_trade_time
        }

    def get_all_trading_symbols(self) -> List[str]:
        """Get all symbols that have transaction logs"""
        symbols = []
        for filename in os.listdir('.'):
            if filename.endswith('_transactions_log.csv'):
                symbol = filename.replace('_transactions_log.csv', '')
                symbols.append(symbol)
        return symbols


class TelegramBot:
    """Simple Telegram bot using REST API"""
    
    def __init__(self, token: str):
        self.token = token
        self.base_url = f"https://api.telegram.org/bot{token}"
    
    def send_message(self, chat_id: str, text: str, parse_mode: str = None) -> bool:
        """Send message using Telegram REST API"""
        try:
            url = f"{self.base_url}/sendMessage"
            data = {
                'chat_id': chat_id,
                'text': text
            }
            if parse_mode:
                data['parse_mode'] = parse_mode
                
            response = requests.post(url, data=data, timeout=10)
            response.raise_for_status()
            
            result = response.json()
            if result.get('ok'):
                logger.info("Message sent successfully")
                return True
            else:
                logger.error(f"Failed to send message: {result}")
                return False
                
        except Exception as e:
            logger.error(f"Error sending Telegram message: {e}")
            return False


class HourlyReporter:
    """Send hourly account overview reports via Telegram"""

    def __init__(self, token: str, chat_id: str, api_key: str, api_secret: str):
        self.token = token
        self.chat_id = chat_id
        self.bot = TelegramBot(token=token)
        self.account_analyzer = BinanceAccountAnalyzer(api_key, api_secret)
        self.transaction_analyzer = TransactionLogAnalyzer()
        self.last_alert_time = {}  # Track last alert time per symbol to avoid spam

    def check_trading_activity(self):
        """Check trading activity for all symbols and send alerts if no recent trades"""
        try:
            logger.info("Checking trading activity...")
            current_time = datetime.now()
            symbols = self.transaction_analyzer.get_all_trading_symbols()
            
            inactive_symbols = []
            
            for symbol in symbols:
                last_trade_time = self.transaction_analyzer.get_last_trade_time(symbol)
                
                if last_trade_time is None:
                    # No trades ever recorded for this symbol
                    inactive_symbols.append(f"{symbol} (no trades recorded)")
                    continue
                
                # Check if last trade was more than 10 minutes ago
                time_since_last_trade = current_time - last_trade_time.replace(tzinfo=None)
                
                if time_since_last_trade > timedelta(minutes=10):
                    # Check if we already sent an alert for this symbol recently (within last 30 minutes)
                    last_alert = self.last_alert_time.get(symbol)
                    if last_alert is None or (current_time - last_alert) > timedelta(minutes=30):
                        inactive_symbols.append(f"{symbol} (last trade: {last_trade_time.strftime('%H:%M:%S')})")
                        self.last_alert_time[symbol] = current_time
            
            if inactive_symbols:
                alert_message = self._format_trading_alert(inactive_symbols)
                success = self.bot.send_message(
                    chat_id=self.chat_id,
                    text=alert_message,
                    parse_mode='Markdown'
                )
                
                if success:
                    logger.info(f"Trading activity alert sent for {len(inactive_symbols)} symbols")
                else:
                    logger.error("Failed to send trading activity alert")
            else:
                logger.info("All symbols have recent trading activity")

        except Exception as e:
            logger.error(f"Error checking trading activity: {e}")

    def _format_trading_alert(self, inactive_symbols: List[str]) -> str:
        """Format the trading activity alert message"""
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        response = f"⚠️ *Trading Activity Alert - {current_time}*\n\n"
        response += f"🚨 *No trades detected in the last 10 minutes for:*\n\n"
        
        for symbol_info in inactive_symbols:
            response += f"• {symbol_info}\n"
        
        response += f"\n⏰ Check your trading bots and ensure they are running properly."
        
        return response

    def send_hourly_report(self):
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

            # Send message using REST API
            success = self.bot.send_message(
                chat_id=self.chat_id,
                text=response,
                parse_mode='Markdown'
            )

            if success:
                logger.info("Hourly report sent successfully")
            else:
                logger.error("Failed to send hourly report")

        except Exception as e:
            logger.error(f"Error sending hourly report: {e}")

    def _format_hourly_report(self, account_data: Dict, transaction_data: Dict, transaction_data_24h: Dict) -> str:
        """Format the hourly report message"""
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        response = f"🕐 *Scalp Trading Hourly Report - {current_time}*\n\n"

        # Account balance and PnL
        response += f"💰 *Account Balance:* ${account_data['total_balance']:,.2f}\n"
        response += f"📈 *Unrealized PnL:* ${account_data['total_unrealized_pnl']:,.2f}\n\n"

        # Current positions
        if account_data['positions']:
            response += "📋 *Current Positions:*\n"
            for pos in account_data['positions']:
                response += f"{pos['symbol']}: {pos['size']:.4f} @ ${pos['entry_price']:,.2f}\n"
                response += f"   Mark: ${pos['mark_price']:,.2f} | PnL: ${pos['unrealized_pnl']:,.2f}\n\n"
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

                    response += f"{symbol}:\n"
                    response += f"   Trades: {data['num_trades']}\n"
                    response += f"   Realized PnL: ${data['realized_pnl']:,.2f}\n"
                    response += f"   Volume: ${data['total_volume']:,.2f}\n"
                    response += f"   Last Trade: {data['last_trade_time'].strftime('%Y-%m-%d %H:%M:%S')}\n\n"

            if total_trades > 0:
                response += "📊 *Totals (1h):*\n"
                response += f"   Total Trades: {total_trades}\n"
                response += f"   Total Realized PnL: ${total_realized_pnl:,.2f}\n"
                response += f"   Total Volume: ${total_volume:,.2f}\n"
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
                response += f"   Total Realized PnL: ${total_realized_pnl_24h:,.2f}\n"
                response += f"   Total Volume: ${total_volume_24h:,.2f}\n"
        else:
            response += "📈 *Trading Activity:* No transaction logs found.\n"

        return response

    def run_scheduler(self):
        """Run the hourly scheduler with 10-minute trading activity checks"""
        logger.info("Scheduler started. Hourly reports at :00, trading activity checks every 10 minutes")

        # Send initial report
        try:
            self.send_hourly_report()
        except Exception as e:
            logger.error(f"Error sending initial report: {e}")

        # Initialize last activity check time
        last_activity_check = datetime.now()

        # Keep the scheduler running
        while True:
            current_time = datetime.now()
            
            # Check if it's time for hourly report (at :00)
            if current_time.minute == 0:
                try:
                    self.send_hourly_report()
                except Exception as e:
                    logger.error(f"Error sending hourly report: {e}")
            
            # Check trading activity every 10 minutes
            if (current_time - last_activity_check).total_seconds() >= 600:  # 10 minutes
                try:
                    self.check_trading_activity()
                    last_activity_check = current_time
                except Exception as e:
                    logger.error(f"Error checking trading activity: {e}")
            
            # Sleep for 1 minute before next check
            time.sleep(60)


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

    reporter = HourlyReporter(telegram_token, telegram_chat_id, binance_api_key, binance_api_secret)
    # Create and run hourly reporter
    reporter.run_scheduler()


if __name__ == "__main__":
    main()
