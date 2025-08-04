#!/usr/bin/env python3
"""
Binance Futures Trading Bot
"""

import os
import json
import sys
import time
import threading
import csv
import logging
import argparse
from datetime import datetime
from dataclasses import dataclass
from typing import Optional, List, Dict, Any
import pytz
from binance.um_futures import UMFutures
from binance.websocket.um_futures.websocket_client import UMFuturesWebsocketClient
import dotenv

dotenv.load_dotenv()


@dataclass
class TradingConfig:
    """Configuration class for trading parameters."""
    symbol: str = 'ETHUSDC'
    quantity: float = 0.01
    take_profit: float = 1
    direction: str = 'BUY'
    max_orders: int = 75
    wait_time: int = 30

    @property
    def close_order_side(self) -> str:
        """Get the close order side based on bot direction."""
        return 'BUY' if self.direction == "SELL" else 'SELL'


@dataclass
class OrderMonitor:
    """Thread-safe order monitoring state."""
    order_id: Optional[str] = None
    filled: bool = False
    filled_price: Optional[float] = None
    filled_qty: float = 0.0

    def reset(self):
        """Reset the monitor state."""
        self.order_id = None
        self.filled = False
        self.filled_price = None
        self.filled_qty = 0.0


class TradingLogger:
    """Enhanced logging with structured output and error handling."""

    def __init__(self, symbol: str, log_to_console: bool = False):
        self.symbol = symbol
        self.log_file = f"{symbol}_transactions_log.csv"
        self.debug_log_file = f"{symbol}_bot_activity.log"
        self.logger = self._setup_logger(log_to_console)

    def _setup_logger(self, log_to_console: bool) -> logging.Logger:
        """Setup the logger with proper configuration."""
        logger = logging.getLogger(f"trading_bot_{self.symbol}")
        logger.setLevel(logging.INFO)

        # Prevent duplicate handlers
        if logger.handlers:
            return logger

        formatter = logging.Formatter(
            "%(asctime)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )

        # File handler
        file_handler = logging.FileHandler(self.debug_log_file, mode='a')
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

        # Console handler
        if log_to_console:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setFormatter(formatter)
            logger.addHandler(console_handler)

        return logger

    def log(self, message: str, level: str = "INFO"):
        """Log a message with the specified level."""
        getattr(self.logger, level.lower())(message)

    def log_transaction(self, transaction_id: str, tx_type: str, price: float,
                        amount: float, status: str, counter_order_id: Optional[str] = None):
        """Log a transaction to CSV file with error handling."""
        try:
            with open(self.log_file, mode='a', newline='') as file:
                writer = csv.writer(file)
                writer.writerow([
                    datetime.now(pytz.timezone('Europe/Paris')).isoformat(),
                    self.symbol,
                    transaction_id,
                    tx_type,
                    counter_order_id or "",
                    round(price, 6),
                    round(amount, 6),
                    status
                ])
        except Exception as e:
            self.log(f"Failed to log transaction: {e}", "ERROR")


class BinanceClient:
    """Enhanced Binance client with retry logic and error handling."""

    def __init__(self, api_key: str, api_secret: str):
        self.client = UMFutures(key=api_key, secret=api_secret)
        self._listen_key = None
        self._ws_client = None

    def get_listen_key(self) -> str:
        """Get or refresh the listen key."""
        if not self._listen_key:
            self._listen_key = self.client.new_listen_key()["listenKey"]
        return self._listen_key

    def renew_listen_key(self):
        """Renew the listen key."""
        try:
            self.client.renew_listen_key(listenKey=self._listen_key)
        except Exception:
            # If renewal fails, get a new key
            self._listen_key = None
            self.get_listen_key()

    def get_active_close_orders(self, symbol: str, close_order_side: str,
                                retries: int = 3, delay: float = 1.0) -> List[str]:
        """Get active close orders with retry logic."""
        for attempt in range(retries):
            try:
                open_orders = self.client.get_orders(symbol=symbol)
                return [
                    order.get('orderId')
                    for order in open_orders
                    if order.get('side') == close_order_side
                ]
            except Exception:
                if attempt < retries - 1:
                    time.sleep(delay * (attempt + 1))  # Exponential backoff
                else:
                    raise

    def place_open_order(self, symbol: str, qty: float, side: str,
                         price_match: str = 'QUEUE', time_in_force: str = "GTC") -> Dict[str, Any]:
        """Place an open order."""
        return self.client.new_order(
            symbol=symbol,
            side=side,
            positionSide='BOTH',
            type='LIMIT',
            quantity=qty,
            priceMatch=price_match,
            timeInForce=time_in_force
        )

    def place_close_order_with_fallback(self, symbol: str, qty: float, price: float, side: str) -> Dict[str, Any]:
        """Place a close order with fallback to queue 1 post only order."""
        try:
            return self.client.new_order(
                symbol=symbol,
                side=side,
                positionSide='BOTH',
                type='LIMIT',
                quantity=qty,
                price=str(round(price, 3)),
                reduceOnly="true",
                timeInForce='GTX'  # POST ONLY ORDER
            )
        except Exception:
            # Fallback to regular queue 1 post only order
            return self.client.new_order(
                symbol=symbol,
                side=side,
                positionSide='BOTH',
                type='LIMIT',
                quantity=qty,
                priceMatch='QUEUE',
                reduceOnly="true",
                timeInForce='GTC'
            )

    def cancel_order(self, symbol: str, order_id: str) -> Dict[str, Any]:
        """Cancel an order with error handling."""
        return self.client.cancel_order(symbol=symbol, orderId=order_id)


class WebSocketManager:
    """Manages WebSocket connections with automatic reconnection."""

    def __init__(self, client: BinanceClient, logger: TradingLogger,
                 order_monitor: OrderMonitor, config: TradingConfig, fill_event: threading.Event):
        self.client = client
        self.logger = logger
        self.order_monitor = order_monitor
        self.config = config
        self.fill_event = fill_event
        self.ws_client = None
        self.cumulative_pnl = 0.0
        self.start_time = time.time()
        self._running = False

    def start(self):
        """Start the WebSocket connection."""
        self._running = True
        listen_key = self.client.get_listen_key()
        self.ws_client = UMFuturesWebsocketClient(on_message=self._handle_message)
        self.ws_client.user_data(listen_key=listen_key)

    def stop(self):
        """Stop the WebSocket connection."""
        self._running = False
        if self.ws_client:
            self.ws_client.stop()

    def _handle_message(self, _, raw_msg: str):
        """Handle incoming WebSocket messages."""
        try:
            msg = json.loads(raw_msg)
            if 'e' not in msg or msg.get('e') != 'ORDER_TRADE_UPDATE':
                return

            order = msg['o']
            if order['s'] != self.config.symbol:
                return

            # Handle order updates
            if order['i'] == self.order_monitor.order_id:
                self._handle_order_update(order)
            elif (order["S"] == self.config.close_order_side and
                  order["X"] == "FILLED"):
                self._handle_close_order_fill(order)

        except Exception as e:
            self.logger.log(f"Error handling WebSocket message: {e}", "ERROR")

    def _handle_order_update(self, order: Dict[str, Any]):
        """Handle order status updates."""
        status = order['X']
        if status == 'FILLED':
            self.order_monitor.filled = True
            self.order_monitor.filled_price = float(order['ap'])
            self.order_monitor.filled_qty = float(order['z'])
            self.logger.log(f"{datetime.now().isoformat()} [{order['i']}] Order filled: "
                            f"{self.order_monitor.filled_qty} @ {self.order_monitor.filled_price}")
            # Set the fill event to notify the main thread that the order was filled
            self.fill_event.set()

        elif status == 'PARTIALLY_FILLED':
            self.order_monitor.filled_qty = float(order['z'])
            self.order_monitor.filled_price = float(order['ap'])
            self.logger.log(f"{datetime.now().isoformat()} [{order['i']}] Order partially filled: "
                            f"{self.order_monitor.filled_qty} @ {self.order_monitor.filled_price}")

    def _handle_close_order_fill(self, order: Dict[str, Any]):
        """Handle close order fills."""
        self.logger.log_transaction(
            order["i"], "CLOSE", float(order['ap']), float(order['q']), "FILLED"
        )

        self.cumulative_pnl += self.config.take_profit * float(order['q'])
        self.logger.log(f"{datetime.now().isoformat()} Cumulative realized PnL: {self.cumulative_pnl}")


class TradingBot:
    """Main trading bot class with all trading logic."""

    def __init__(self, config: TradingConfig):
        self.config = config
        self.logger = TradingLogger(config.symbol)
        self.order_monitor = OrderMonitor()
        self.fill_event = threading.Event()

        # Validate API credentials
        api_key = os.getenv("API_KEY")
        api_secret = os.getenv("API_SECRET")

        if not api_key or not api_secret:
            raise ValueError("API_KEY and API_SECRET environment variables must be set")

        self.client = BinanceClient(api_key, api_secret)
        self.ws_manager = WebSocketManager(self.client, self.logger,
                                           self.order_monitor, self.config, self.fill_event)

        # Trading state
        self.last_open_order_time = 0
        self.skip_waiting_time = False
        self.close_order = {"orderId": None}
        self.order_status = None
        self.active_close_orders = []
        self.last_log_time = time.time()

    def _refresh_listen_key_thread(self):
        """Background thread to refresh the listen key."""
        while True:
            try:
                time.sleep(30 * 60)  # 30 minutes
                self.client.renew_listen_key()
                self.logger.log("Refreshed listenKey")
            except Exception as e:
                self.logger.log(f"Error renewing listen key: {e}", "ERROR")

    def _calculate_wait_time(self) -> int:
        """Calculate the current wait time based on active orders."""
        if len(self.active_close_orders) < self.config.max_orders / 3:
            self.logger.log(f"Skipping waiting time for active close orders: "
                            f"{len(self.active_close_orders)}/{self.config.max_orders}")
            return 0
        return self.config.wait_time

    def _place_and_monitor_open_order(self) -> bool:
        """Place an order and monitor its execution."""
        try:
            # Place the order
            order = self.client.place_open_order(
                self.config.symbol,
                self.config.quantity,
                self.config.direction
            )
            self.logger.log(f"{datetime.now().isoformat()} [{order['orderId']}] New order placed for opening position")

            # Setup monitoring
            self.order_monitor.reset()
            self.order_monitor.order_id = order["orderId"]
            self.fill_event.clear()
            self.last_open_order_time = time.time()

            # Wait for fill or timeout
            self.fill_event.wait(timeout=10)

            # Handle order result
            return self._handle_order_result(order)

        except Exception as e:
            self.logger.log(f"Error placing order: {e}", "ERROR")
            return False

    def _handle_order_result(self, order: Dict[str, Any]) -> bool:
        """Handle the result of an order placement."""
        canceled_order = None

        if not self.order_monitor.filled:
            try:
                canceled_order = self.client.cancel_order(
                    self.config.symbol, order["orderId"]
                )
                self.logger.log(f"{datetime.now().isoformat()} [{order['orderId']}] "
                                f"Order not filled or partially filled. Order Cancelled")
            except Exception:
                self.logger.log(f"{datetime.now().isoformat()} [{order['orderId']}] "
                                f"Tried cancelling order, but order already filled")
                self.order_monitor.filled = True
                self.order_monitor.filled_qty = self.config.quantity
                self.order_monitor.filled_price = float(order["price"])

        # Process the result
        if self.order_monitor.filled:
            filled_amount = float(order["origQty"])
            self._place_close_order(filled_amount, self.order_monitor.filled_price)
            self.order_status = "FILLED"
        else:
            filled_amount = float(canceled_order.get("executedQty", 0))

            if filled_amount > 0:
                self._place_close_order(filled_amount, self.order_monitor.filled_price)
                self.order_status = "PARTIALLY_FILLED"
            else:
                self.order_status = "CANCELLED"
                self.close_order = {"orderId": None}
                self.active_close_orders.append(0)

        # Log the transaction
        self.logger.log_transaction(
            order["orderId"], "OPEN", float(order["price"]),
            filled_amount, self.order_status, self.close_order["orderId"]
        )

        return True

    def _place_close_order(self, qty: float, price: float):
        """Place a close order."""
        close_order = self.client.place_close_order_with_fallback(
            self.config.symbol,
            qty=qty,
            price=price + self.config.take_profit,
            side=self.config.close_order_side
        )
        self.logger.log(f"{datetime.now().isoformat()} [{close_order['orderId']}] "
                        f"Close order placed: {qty} @ {price + self.config.take_profit}")

        self.close_order = close_order
        self.active_close_orders.append(close_order["orderId"])

    def _update_skip_waiting_logic(self):
        """Update the skip waiting time logic."""
        # If we have a close order ID but it's no longer in active orders,
        # it means the close order was filled - skip waiting to place next order
        if (self.close_order["orderId"] is not None and
                self.close_order["orderId"] not in self.active_close_orders):
            self.skip_waiting_time = True
            self.logger.log(f"{datetime.now().isoformat()} [{self.close_order['orderId']}] "
                            f"Skipping waiting time. Close order filled")
        # If the open order was cancelled, skip waiting to retry immediately
        elif self.order_status == "CANCELLED":
            self.skip_waiting_time = True
        # Otherwise maintain normal waiting period between orders
        else:
            self.skip_waiting_time = False

    def _log_status_periodically(self):
        """Log status information periodically."""
        if time.time() - self.last_log_time > 300:
            self.logger.log(f"Active close orders: {self.active_close_orders}")
            self.last_log_time = time.time()

    def run(self):
        """Main trading loop."""
        try:
            # Start WebSocket
            self.ws_manager.start()

            # Start refresh listen key thread
            refresh_listen_key_thread = threading.Thread(
                target=self._refresh_listen_key_thread, daemon=True
            )
            refresh_listen_key_thread.start()

            # Initialize active orders
            self.active_close_orders = self.client.get_active_close_orders(
                self.config.symbol, self.config.close_order_side
            )

            # Main trading loop
            while True:
                current_time = time.time()
                wait_time = self._calculate_wait_time()

                # Place new orders if conditions are met
                if len(self.active_close_orders) < self.config.max_orders:
                    if (current_time - self.last_open_order_time >= wait_time or
                            self.skip_waiting_time):
                        self._place_and_monitor_open_order()

                # Update active orders
                latest_active_orders = self.client.get_active_close_orders(
                    self.config.symbol, self.config.close_order_side
                )

                # Update skip waiting logic
                self._update_skip_waiting_logic()

                # Update active orders list
                self.active_close_orders = latest_active_orders

                # Periodic logging
                self._log_status_periodically()

                # wait 10 seconds if we have reached max orders
                if len(self.active_close_orders) >= self.config.max_orders:
                    time.sleep(10)
                    continue
                else:
                    time_since_last_open_order = time.time() - self.last_open_order_time
                    # wait if we have not reached max orders and we are not skipping waiting time
                    if not self.skip_waiting_time and time_since_last_open_order < wait_time:
                        sleep_time = min(10, wait_time - time_since_last_open_order)
                        time.sleep(sleep_time)

        except KeyboardInterrupt:
            self.logger.log("Bot stopped by user")
        except Exception as e:
            self.logger.log(f"Critical error: {e}", "ERROR")
            import traceback
            self.logger.log(traceback.format_exc(), "ERROR")
            raise
        finally:
            self.ws_manager.stop()


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description='Binance Futures Trading Bot')
    parser.add_argument('--symbol', type=str, default='ETHUSDC',
                        help='Trading pair symbol (default: ETHUSDC)')
    parser.add_argument('--quantity', type=float, default=0.01,
                        help='Order quantity (default: 1)')
    parser.add_argument('--take-profit', type=float, default=1,
                        help='Take profit in USDC (default: 1)')
    parser.add_argument('--direction', type=str, default='BUY',
                        help='Direction of the bot (default: BUY)')
    parser.add_argument('--max-orders', type=int, default=75,
                        help='Maximum number of active orders (default: 5)')
    parser.add_argument('--wait-time', type=int, default=30,
                        help='Wait time between orders in seconds (default: 300)')
    return parser.parse_args()


def main():
    """Main entry point."""
    args = parse_arguments()

    # Create configuration
    config = TradingConfig(
        symbol=args.symbol,
        quantity=args.quantity,
        take_profit=args.take_profit,
        direction=args.direction,
        max_orders=args.max_orders,
        wait_time=args.wait_time
    )

    # Create and run the bot
    bot = TradingBot(config)
    bot.run()


if __name__ == "__main__":
    main()
