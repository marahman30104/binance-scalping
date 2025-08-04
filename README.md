# Binance Futures Arbitrage Bot

## Prerequisites

- Python 3.7 or higher
- Binance Futures account with API access
- API key with futures trading permissions

## Installation

1. **Clone the repository**:

```bash
git clone <repository-url>
cd binance-bot
```

2. **Install dependencies**:

```bash
pip install -r requirements.txt
```

3. **Set up environment variables**:
   Copy the example environment file and configure your API credentials:

```bash
cp .env.example .env
# Edit .env with your actual Binance API credentials
```

### Trading Parameters

The bot supports various trading parameters that can be configured via command line arguments:

- `--symbol`: Trading pair (e.g., BTCUSDC, ETHUSDC, PUMPUSDT)
- `--quantity`: Quantity per order (if you are trading ETHUSDC, then 0.1 means 0.1 ETH)
- `--take_profit`: Price offset for profit taking. 0.5 means placing close order for opening price + $0.5
- `--max-orders`: Maximum number of concurrent orders
- `--wait-time`: Wait time between orders (seconds)
- `--direction`: Trading direction (BUY or SELL)

## Usage

#### BTC/USDC Trading

```bash
python runbot.py --symbol BTCUSDC --quantity 0.001 --take_profit 50 --max-orders 50 --wait-time 30
```

#### ETH/USDC Trading

```bash
python runbot.py --symbol ETHUSDC --quantity 0.2 --take_profit 0.5 --max-orders 50 --wait-time 30
```

### Command Line Arguments

| Argument        | Description                        | Default | Example |
| --------------- | ---------------------------------- | ------- | ------- |
| `--symbol`      | Trading pair symbol                | ETHUSDC | BTCUSDC |
| `--quantity`    | Order quantity                     | 0.01    | 0.02    |
| `--take_profit` | Price offset                       | 1       | 50      |
| `--max-orders`  | Maximum concurrent orders          | 75      | 5       |
| `--wait-time`   | Wait time between orders (seconds) | 30      | 300     |
| `--direction`   | Trading direction                  | BUY     | SELL    |

## Dashboard

The bot includes a real-time dashboard for monitoring trading activities:

### Start the Dashboard

```bash
python dashboard.py
```

### Dashboard Features

- **Real-time Account Monitoring**: Live wallet balance, unrealized PnL, available balance
- **Position Tracking**: Monitor open positions with entry prices and mark prices
- **Order Management**: View all open orders with status and details
- **Trading Statistics**: Track total PnL, daily PnL, win rate, and trade counts
- **Recent Trades**: View the last 10 trades with realized PnL
- **Connection Status**: Monitor WebSocket connection and API status

### Dashboard Options

```bash
# Monitor a specific symbol
python dashboard.py --symbol BTCUSDC

# Change refresh rate (default: 5 seconds)
python dashboard.py --refresh-rate 10

# Use API credentials from command line
python dashboard.py --api-key "your_key" --api-secret "your_secret"
```

## Project Structure

```
binance-scalping/
├── runbot.py          # Main trading bot
├── dashboard.py       # Real-time monitoring dashboard
├── requirements.txt   # Python dependencies
├── .env.example      # Environment variables template
├── .gitignore        # Git ignore rules
├── LICENSE           # MIT License
└── README.md         # This file
```

## How It Works

### Trading Strategy

1. **Order Placement**: The bot places limit orders at random price levels
2. **Order Monitoring**: WebSocket connection monitors order status in real-time
3. **Execution Handling**: When an order is filled, the bot automatically places a closing order
4. **Risk Management**: Configurable limits prevent excessive exposure

### Key Components

- **TradingBot**: Main bot logic and order management
- **WebSocketManager**: Real-time order and account updates
- **BinanceClient**: API interaction and order placement
- **TradingLogger**: Comprehensive logging and transaction tracking
- **TradingDashboard**: Real-time monitoring interface

### Order Flow

1. Bot places an POST-ONLY open order at QUEUE 1 price ± offset
2. WebSocket monitors order status continuously
3. When order fills, bot immediately places a closing limit order
4. Process repeats based on wait time and max orders configuration

## Logging

The bot provides comprehensive logging:

- **Transaction Logs**: CSV files with detailed trade information
- **Activity Logs**: Debug logs for troubleshooting
- **Real-time Updates**: Console output for immediate feedback

Log files are created per symbol:

- `{SYMBOL}_transactions_log.csv`
- `{SYMBOL}_bot_activity.log`

## Security Considerations

### API Credentials

- **Environment Variables**: API credentials are stored in environment variables, never hardcoded
- **Secure Storage**: Use `.env` file for local development (not committed to git)
- **Production**: Use your system's environment variable management for production deployments

### Connection Security

- **WebSocket**: All connections use secure WebSocket protocols (WSS)
- **API Calls**: All API calls use HTTPS with proper authentication
- **Listen Key**: Automatic refresh every 30 minutes to maintain secure connections

### Data Protection

- **No Sensitive Logging**: API keys and secrets are never logged or displayed
- **Transaction Logs**: Only trade data is logged, no account credentials
- **Error Handling**: Sensitive information is masked in error messages

### Best Practices

1. **Never commit `.env` files** - They're already in `.gitignore`
2. **Use API keys with minimal permissions** - Only futures trading permissions needed
3. **Regular key rotation** - Consider rotating API keys periodically
4. **Test on testnet first** - Always test with small amounts before live trading
5. **Monitor access logs** - Check your Binance account for unusual activity

### Environment Setup

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
# Edit .env with your actual API credentials
```

## Risk Warning

⚠️ **Important**: This bot is for educational and testing purposes. Cryptocurrency trading involves significant risk. Never trade with money you cannot afford to lose.

- Test thoroughly on testnet before using real funds
- Start with small amounts
- Monitor the bot continuously
- Understand the trading strategy before deployment

## Support

For issues and questions:

1. Check the logs for error messages
2. Verify API credentials and permissions
3. Test with small quantities first
4. Monitor the dashboard for real-time status

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request. For major changes, please open an issue first to discuss what you would like to change.

### Development Setup

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## Security Reporting

If you discover a security vulnerability, please report it via email or create a private issue. Please do not create a public GitHub issue for security vulnerabilities.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

**Disclaimer**: This software is for educational purposes only. Use at your own risk. The authors are not responsible for any financial losses incurred from using this bot.
