#!/usr/bin/env python3

import os
import json
import sys
import time
import threading
from datetime import datetime
from binance.um_futures import UMFutures
from binance.websocket.um_futures.websocket_client import UMFuturesWebsocketClient
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from rich.live import Live
from rich.align import Align
import argparse

from dotenv import load_dotenv
load_dotenv()

# Initialize Rich console
console = Console()


class TradingDashboard:
    def __init__(self, api_key=None, api_secret=None):
        self.api_key = api_key or os.getenv("API_KEY")
        self.api_secret = api_secret or os.getenv("API_SECRET")

        if not self.api_key or not self.api_secret:
            console.print("[red]Error: API_KEY and API_SECRET environment variables must be set[/red]")
            sys.exit(1)

        self.client = UMFutures(key=self.api_key, secret=self.api_secret)
        self.listen_key = self.client.new_listen_key()["listenKey"]

        # Dashboard state
        self.account_info = {}
        self.positions = []
        self.open_orders = []
        self.recent_trades = []
        self.pnl_history = []
        self.last_update = None
        self.last_full_sync_time = None
        self.websocket_client = None

        # Statistics
        self.total_pnl = 0
        self.daily_pnl = 0
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0

        # Start websocket connection
        self.start_websocket()

        # Start keep-alive thread
        self.keep_alive_thread = threading.Thread(target=self._keep_alive, daemon=True)
        self.keep_alive_thread.start()

    def start_websocket(self):
        """Start websocket connection for real-time updates"""
        def handle_message(_, raw_msg):
            try:
                msg = json.loads(raw_msg)
                if msg.get('e') == 'ORDER_TRADE_UPDATE':
                    self._handle_order_update(msg['o'])
                elif msg.get('e') == 'ACCOUNT_UPDATE':
                    self._handle_account_update(msg)
            except Exception as e:
                console.print(f"[red]Websocket error: {e}[/red]")

        self.websocket_client = UMFuturesWebsocketClient(on_message=handle_message)
        self.websocket_client.user_data(listen_key=self.listen_key)

        # Also subscribe to mark price streams for all symbols we're tracking
        self._subscribe_to_mark_price_streams()

        # Start a thread to periodically update mark price subscriptions
        self.mark_price_update_thread = threading.Thread(target=self._update_mark_price_subscriptions, daemon=True)
        self.mark_price_update_thread.start()

    def _subscribe_to_mark_price_streams(self):
        """Subscribe to mark price streams for symbols we're tracking"""
        try:
            # Get symbols from positions and orders
            symbols = set()
            for pos in self.positions:
                symbols.add(pos['symbol'].lower())
            for order in self.open_orders:
                symbols.add(order['symbol'].lower())

            # Subscribe to mark price streams
            if symbols:
                streams = [f"{symbol}@markPrice" for symbol in symbols]
                self.websocket_client.mark_price_stream(
                    id=1,
                    callback=self._handle_mark_price_update,
                    streams=streams
                )
        except Exception as e:
            console.print(f"[yellow]Failed to subscribe to mark price streams: {e}[/yellow]")

    def _handle_mark_price_update(self, msg):
        """Handle mark price updates"""
        try:
            if isinstance(msg, dict) and 'data' in msg:
                data = msg['data']
                symbol = data.get('s', '')
                mark_price = float(data.get('p', 0))

                # Update mark price in positions
                for pos in self.positions:
                    if pos['symbol'] == symbol:
                        pos['mark_price'] = mark_price
                        # Recalculate unrealized PnL
                        if pos['position_amt'] != 0:
                            price_diff = mark_price - pos['entry_price']
                            pos['unrealized_pnl'] = price_diff * pos['position_amt']
                        break
        except Exception as e:
            console.print(f"[red]Failed to handle mark price update: {e}[/red]")

    def _update_mark_price_subscriptions(self):
        """Periodically update mark price subscriptions based on current positions and orders"""
        while True:
            try:
                time.sleep(60)  # Check every minute

                # Get current symbols
                current_symbols = set()
                for pos in self.positions:
                    current_symbols.add(pos['symbol'].lower())
                for order in self.open_orders:
                    current_symbols.add(order['symbol'].lower())

                # If symbols changed, resubscribe
                if hasattr(self, '_subscribed_symbols') and self._subscribed_symbols != current_symbols:
                    self._subscribe_to_mark_price_streams()

                self._subscribed_symbols = current_symbols

            except Exception as e:
                console.print(f"[yellow]Failed to update mark price subscriptions: {e}[/yellow]")

    def _keep_alive(self):
        """Keep websocket connection alive"""
        while True:
            time.sleep(30 * 60)  # 30 minutes
            try:
                self.client.renew_listen_key(listenKey=self.listen_key)
                console.print("[green]Refreshed listenKey[/green]")
            except Exception as e:
                console.print(f"[red]Failed to refresh listenKey: {e}[/red]")

    def _handle_order_update(self, order):
        """Handle order trade updates"""
        self.last_update = datetime.now()

        # Update the specific order in our local data
        order_symbol = order.get('s', '')
        order_id = order.get('i', '')
        order_status = order.get('X', '')

        # Remove filled/cancelled orders from open orders
        if order_status in ['FILLED', 'CANCELED', 'REJECTED', 'EXPIRED']:
            self.open_orders = [o for o in self.open_orders if o['order_id'] != order_id]
        else:
            # Update existing order or add new one
            order_data = {
                'order_id': order_id,
                'symbol': order_symbol,
                'side': order.get('S', ''),
                'type': order.get('o', ''),
                'quantity': float(order.get('q', 0)),
                'price': float(order.get('p', 0)),
                'status': order_status,
                'time': datetime.now()
            }

            # Update existing order or add new one
            found = False
            for i, existing_order in enumerate(self.open_orders):
                if existing_order['order_id'] == order_id:
                    self.open_orders[i] = order_data
                    found = True
                    break

            if not found:
                self.open_orders.append(order_data)

    def _handle_account_update(self, msg):
        """Handle account updates"""
        self.last_update = datetime.now()
        # Update positions based on account update
        if 'a' in msg and 'P' in msg['a']:
            positions_update = msg['a']['P']
            for pos_update in positions_update:
                symbol = pos_update.get('s', '')
                position_amt = float(pos_update.get('pa', 0))

                # Update or add position
                found = False
                for i, existing_pos in enumerate(self.positions):
                    if existing_pos['symbol'] == symbol:
                        self.positions[i]['position_amt'] = position_amt
                        if position_amt == 0:
                            # Remove closed positions
                            self.positions.pop(i)
                        found = True
                        break

                if not found and position_amt != 0:
                    # Add new position (we'll get full details from API later)
                    self.positions.append({
                        'symbol': symbol,
                        'position_amt': position_amt,
                        'entry_price': 0,
                        'mark_price': 0,
                        'unrealized_pnl': 0,
                        'liquidation_price': 0,
                        'leverage': '',
                        'margin_type': ''
                    })

    def get_wallet_balance(self, account):
        """Get wallet balance"""
        wallet_balance = 0
        assets = account.get('assets', [])
        for asset in assets:
            wallet_balance += float(asset.get('walletBalance', 0))
        return wallet_balance

    def get_margin_balance(self, account):
        """Get margin balance"""
        margin_balance = 0
        assets = account.get('assets', [])
        for asset in assets:
            margin_balance += float(asset.get('marginBalance', 0))
        return margin_balance

    def get_available_balance(self, account):
        """Get available balance"""
        available_balance = 0
        assets = account.get('assets', [])
        for asset in assets:
            available_balance += float(asset.get('availableBalance', 0))
        return available_balance

    def get_max_withdraw_amount(self, account):
        """Get max withdraw amount"""
        return float(account.get('maxWithdrawAmount', 0))

    def update_account_info(self):
        """Update account information"""
        try:
            account = self.client.account()

            wallet_balance = self.get_wallet_balance(account)
            available_balance = self.get_available_balance(account)
            max_withdraw_amount = self.get_max_withdraw_amount(account)
            # Handle the case where some fields might not exist
            self.account_info = {
                'total_wallet_balance': wallet_balance,
                'total_unrealized_pnl': float(account.get('totalUnrealizedProfit', 0)),
                'available_balance': available_balance,
                'max_withdraw_amount': max_withdraw_amount,
                'update_time': int(time.time() * 1000)  # Use current timestamp in milliseconds
            }
        except Exception as e:
            console.print(f"[red]Failed to update account info: {e}[/red]")

    def update_positions(self):
        """Update position information"""
        try:
            positions = self.client.get_position_risk()
            self.positions = [
                {
                    'symbol': pos.get('symbol', ''),
                    'position_amt': float(pos.get('positionAmt', 0)),
                    'entry_price': float(pos.get('entryPrice', 0)),
                    'mark_price': float(pos.get('markPrice', 0)),
                    'unrealized_pnl': float(pos.get('unRealizedProfit', 0)),
                    'liquidation_price': float(pos.get('liquidationPrice', 0)),
                    'leverage': pos.get('leverage', ''),
                    'margin_type': pos.get('marginType', '')
                }
                for pos in positions if float(pos.get('positionAmt', 0)) != 0
            ]
        except Exception as e:
            console.print(f"[red]Failed to update positions: {e}[/red]")

    def update_open_orders(self):
        """Update open orders for all symbols"""
        try:
            # Get all open orders across all symbols
            orders = self.client.get_orders()
            self.open_orders = [
                {
                    'order_id': order.get('orderId', ''),
                    'symbol': order.get('symbol', ''),
                    'side': order.get('side', ''),
                    'type': order.get('type', ''),
                    'quantity': float(order.get('origQty', 0)),
                    'price': float(order.get('price', 0)),
                    'status': order.get('status', ''),
                    'time': datetime.fromtimestamp(order.get('time', 0) / 1000)
                }
                for order in orders
            ]
        except Exception as e:
            console.print(f"[red]Failed to update open orders: {e}[/red]")

    def update_recent_trades(self):
        """Update recent trades for all symbols"""
        try:
            # Get unique symbols from open orders and positions
            symbols = set()

            # Add symbols from open orders
            for order in self.open_orders:
                symbols.add(order['symbol'])

            # Add symbols from positions
            for position in self.positions:
                symbols.add(position['symbol'])

            # If no symbols found, try to get some common trading pairs
            if not symbols:
                symbols = {'BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'ADAUSDT', 'SOLUSDT'}

            # Get recent trades for each symbol
            all_trades = []
            for symbol in symbols:
                try:
                    trades = self.client.get_account_trades(symbol=symbol, limit=20)
                    all_trades.extend(trades)
                except Exception as e:
                    console.print(f"[yellow]Failed to get trades for {symbol}: {e}[/yellow]")
                    continue

            # Sort trades by time (most recent first) and take the latest 50
            all_trades.sort(key=lambda x: x.get('time', 0), reverse=True)
            recent_trades = all_trades[:50]

            self.recent_trades = [
                {
                    'trade_id': trade.get('id', ''),
                    'order_id': trade.get('orderId', ''),
                    'symbol': trade.get('symbol', ''),
                    'side': trade.get('side', ''),
                    'quantity': float(trade.get('qty', 0)),
                    'price': float(trade.get('price', 0)),
                    'realized_pnl': float(trade.get('realizedPnl', 0)),
                    'time': datetime.fromtimestamp(trade.get('time', 0) / 1000)
                }
                for trade in recent_trades
            ]

            # Calculate statistics
            self._calculate_statistics()

        except Exception as e:
            console.print(f"[red]Failed to update recent trades: {e}[/red]")

    def _calculate_statistics(self):
        """Calculate trading statistics"""
        if not self.recent_trades:
            return

        self.total_trades = len(self.recent_trades)
        self.winning_trades = len([t for t in self.recent_trades if t['realized_pnl'] > 0])
        self.losing_trades = len([t for t in self.recent_trades if t['realized_pnl'] < 0])

        total_pnl = sum(t['realized_pnl'] for t in self.recent_trades)
        self.total_pnl = total_pnl

        # Calculate daily PnL
        today = datetime.now().date()
        daily_trades = [t for t in self.recent_trades if t['time'].date() == today]
        self.daily_pnl = sum(t['realized_pnl'] for t in daily_trades)

    def create_account_panel(self):
        """Create account information panel"""
        if not self.account_info:
            return Panel("Loading account info...", title="Account Information")

        info = self.account_info
        last_update = datetime.now().strftime('%H:%M:%S')
        last_sync = self.last_full_sync_time.strftime('%H:%M:%S') if self.last_full_sync_time else 'Never'

        # Create a table for two-column layout
        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_column("Left")
        table.add_column("Right")

        table.add_row(
            f"Wallet Balance: ${info['total_wallet_balance']:,.2f}",
            f"Available Balance: ${info['available_balance']:,.2f}"
        )
        table.add_row(
            f"Unrealized PnL: ${info['total_unrealized_pnl']:,.2f}",
            f"Max Withdraw: ${info['max_withdraw_amount']:,.2f}"
        )
        table.add_row(
            f"Last Update: {last_update}",
            f"Last Sync: {last_sync}"
        )

        color = "green" if info['total_unrealized_pnl'] >= 0 else "red"
        return Panel(table, title="Account Information", border_style=color)

    def create_positions_panel(self):
        """Create positions panel"""
        if not self.positions:
            return Panel("No open positions", title="Positions")

        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Symbol")
        table.add_column("Size")
        table.add_column("Entry Price")
        table.add_column("Mark Price")
        table.add_column("Unrealized PnL")
        table.add_column("Liquidation Price")

        for pos in self.positions:
            pnl_color = "green" if pos['unrealized_pnl'] >= 0 else "red"
            table.add_row(
                pos['symbol'],
                f"{pos['position_amt']:.4f}",
                f"${pos['entry_price']:.2f}",
                f"${pos['mark_price']:.2f}",
                f"[{pnl_color}]${pos['unrealized_pnl']:.2f}[/{pnl_color}]",
                f"${pos['liquidation_price']:.2f}"
            )

        return Panel(table, title="Open Positions")

    def create_orders_panel(self):
        """Create open orders panel"""
        if not self.open_orders:
            return Panel("No open orders", title="Open Orders")

        # Sort orders by price in ascending order (lowest price first)
        sorted_orders = sorted(self.open_orders, key=lambda x: x['price'], reverse=False)

        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("Symbol")
        table.add_column("Order ID")
        table.add_column("Side")
        table.add_column("Quantity")
        table.add_column("Price")
        table.add_column("Time")

        for order in sorted_orders:
            side_color = "green" if order['side'] == 'BUY' else "red"
            table.add_row(
                order['symbol'],
                str(order['order_id']),
                f"[{side_color}]{order['side']}[/{side_color}]",
                f"{order['quantity']:.4f}",
                f"${order['price']:.2f}",
                order['time'].strftime("%H:%M:%S")
            )

        return Panel(table, title="Open Orders")

    def create_statistics_panel(self):
        """Create trading statistics panel"""
        win_rate = (self.winning_trades/self.total_trades*100) if self.total_trades > 0 else 0
        content = f"""
[bold]Total PnL:[/bold] ${self.total_pnl:,.2f}
[bold]Daily PnL:[/bold] ${self.daily_pnl:,.2f}
[bold]Total Trades:[/bold] {self.total_trades}
[bold]Winning Trades:[/bold] {self.winning_trades}
[bold]Losing Trades:[/bold] {self.losing_trades}
[bold]Win Rate:[/bold] {win_rate:.1f}%
        """

        pnl_color = "green" if self.total_pnl >= 0 else "red"
        return Panel(content, title="Trading Statistics", border_style=pnl_color)

    def create_recent_trades_panel(self):
        """Create recent trades panel"""
        if not self.recent_trades:
            return Panel("No recent trades", title="Recent Trades")

        table = Table(show_header=True, header_style="bold yellow")
        table.add_column("Symbol")
        table.add_column("Time")
        table.add_column("Side")
        table.add_column("Quantity")
        table.add_column("Price")

        for trade in self.recent_trades[:10]:  # Show last 10 trades
            side_color = "green" if trade['side'] == 'BUY' else "red"
            table.add_row(
                trade['symbol'],
                trade['time'].strftime("%H:%M:%S"),
                f"[{side_color}]{trade['side']}[/{side_color}]",
                f"{trade['quantity']:.4f}",
                f"${trade['price']:.2f}"
            )

        return Panel(table, title="Recent Trades")

    def create_status_panel(self):
        """Create status panel"""
        status = "🟢 Connected" if self.last_update else "🔴 Disconnected"
        last_update_str = self.last_update.strftime("%H:%M:%S") if self.last_update else "Never"

        content = f"""
[bold]Status:[/bold] {status}
[bold]Monitoring:[/bold] Entire Account
[bold]Last Update:[/bold] {last_update_str}
[bold]Listen Key:[/bold] {self.listen_key[:20]}...
        """

        return Panel(content, title="Connection Status")

    def generate_layout(self):
        """Generate the dashboard layout"""
        layout = Layout()

        # Create header
        header = Panel(
            Align.center("[bold blue]Binance Futures Account Dashboard[/bold blue]"),
            border_style="blue"
        )

        # Create main content
        layout.split_column(
            Layout(header, size=3),
            Layout(name="main")
        )

        # Split main content into two columns
        layout["main"].split_row(
            Layout(name="left"),
            Layout(name="right")
        )

        # Left column - account info, positions, and trades stacked vertically
        layout["left"].split_column(
            Layout(name="account", ratio=1),
            Layout(name="positions", ratio=1),
            Layout(name="trades", ratio=2)
        )

        # Right column - only open orders
        layout["right"].update(self.create_orders_panel())

        # Assign panels to layout sections
        layout["account"].update(self.create_account_panel())
        layout["positions"].update(self.create_positions_panel())
        layout["trades"].update(self.create_recent_trades_panel())

        return layout

    def run_dashboard(self, refresh_rate=30):
        """Run the dashboard with live updates"""
        console.print("[bold green]Starting Binance Futures Account Dashboard...[/bold green]")
        console.print("[bold]Monitoring:[/bold] Entire Account")
        console.print("[bold]Mode:[/bold] WebSocket-based updates (reduced API calls)")
        console.print(f"[bold]Refresh rate:[/bold] {refresh_rate} seconds (for fallback updates)")
        console.print("Press Ctrl+C to exit\n")

        # Initial data load
        self.update_account_info()
        self.update_positions()
        self.update_open_orders()
        self.update_recent_trades()

        try:
            with Live(self.generate_layout(), refresh_per_second=1, screen=True) as live:
                last_full_update = time.time()

                while True:
                    current_time = time.time()

                    # Only do full API updates every refresh_rate seconds
                    # WebSocket handles real-time updates
                    if current_time - last_full_update >= refresh_rate:
                        try:
                            self.update_account_info()
                            self.update_positions()
                            self.update_open_orders()
                            self.update_recent_trades()
                            self.last_full_sync_time = datetime.now()
                            last_full_update = current_time
                        except Exception as e:
                            console.print(f"[yellow]Fallback update failed: {e}[/yellow]")

                    # Update layout (this happens every second for smooth display)
                    live.update(self.generate_layout())

                    # Short sleep to prevent excessive CPU usage
                    time.sleep(1)

        except KeyboardInterrupt:
            console.print("\n[bold yellow]Dashboard stopped by user[/bold yellow]")
        except Exception as e:
            console.print(f"\n[bold red]Dashboard error: {e}[/bold red]")
        finally:
            if self.websocket_client:
                self.websocket_client.stop()


def parse_arguments():
    parser = argparse.ArgumentParser(description='Binance Futures Account Dashboard')
    parser.add_argument('--refresh-rate', type=int, default=15,
                        help='Dashboard refresh rate in seconds (default: 5)')
    parser.add_argument('--api-key', type=str, default=None,
                        help='Binance API key (optional, can use environment variable)')
    parser.add_argument('--api-secret', type=str, default=None,
                        help='Binance API secret (optional, can use environment variable)')
    return parser.parse_args()


def main():
    args = parse_arguments()

    try:
        dashboard = TradingDashboard(
            api_key=args.api_key,
            api_secret=args.api_secret
        )
        dashboard.run_dashboard(refresh_rate=args.refresh_rate)
    except Exception as e:
        console.print(f"[bold red]Failed to start dashboard: {e}[/bold red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
