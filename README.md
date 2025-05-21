# Cryptocurrency Arbitrage Tool

A web-based application that monitors price differences between Binance and OKX exchanges, allowing you to profit from cryptocurrency arbitrage opportunities.

## Features

- **Real-time Price Monitoring**: Tracks prices across Binance and OKX exchanges for coins under $5 USD
- **Balance Display**: Shows your USDT and cryptocurrency balances on both exchanges
- **Smart Trading Rules**: Automatically adjusts trade amounts based on price ranges:
  - Coins > $3.5: Trade amount = 1 coin
  - Coins $1-$3.5: Trade amount = 4 coins
  - Coins $0.5-$1: Trade amount = 8 coins
  - Coins < $0.5: Trade amount = 15 coins
- **Auto-Trading**: Toggle button to enable/disable automatic trading when profitable opportunities (>$0.09 profit after fees) are detected
- **Manual Trading**: Execute trades manually from the opportunity table
- **Detailed Logging**: All trades are logged with timestamps, prices, amounts, and profit calculations

## Deployment on Render

### Prerequisites

1. GitHub account
2. Render account (sign up at [render.com](https://render.com))
3. Binance Testnet API keys
4. OKX Demo Trading API keys

### Deployment Steps

1. **Fork or clone this repository** to your GitHub account

2. **Create a new Web Service on Render**:
   - Go to your Render dashboard
   - Click "New" and select "Web Service"
   - Connect your GitHub account if you haven't already
   - Select the repository with the Crypto Arbitrage Tool
   - Configure the service:
     - Name: `crypto-arbitrage-tool` (or your preferred name)
     - Environment: `Python 3`
     - Build Command: `pip install -r requirements.txt`
     - Start Command: `gunicorn -k geventwebsocket.gunicorn.workers.GeventWebSocketWorker -w 1 src.main:app`
     - Select the appropriate plan (Free tier works for testing)

3. **Add Environment Variables** (optional):
   - If you want to pre-configure API keys, add these environment variables:
     - `BINANCE_API_KEY`: Your Binance Testnet API key
     - `BINANCE_API_SECRET`: Your Binance Testnet API secret
     - `OKX_API_KEY`: Your OKX Demo Trading API key
     - `OKX_API_SECRET`: Your OKX Demo Trading API secret
     - `OKX_PASSPHRASE`: Your OKX Demo Trading passphrase

4. **Deploy the service**:
   - Click "Create Web Service"
   - Wait for the build and deployment to complete (this may take a few minutes)

5. **Access your application**:
   - Once deployment is complete, Render will provide a URL (e.g., `https://crypto-arbitrage-tool.onrender.com`)
   - Open this URL in your browser to access the Crypto Arbitrage Tool

### Post-Deployment Configuration

If you didn't add environment variables during deployment, you'll need to configure your API keys in the application:

1. Navigate to the Settings tab in the application
2. Enter your Binance Testnet and OKX Demo Trading API credentials
3. Save your settings

## Local Development

### Prerequisites

- Python 3.6 or higher
- pip (Python package installer)

### Setup Instructions

1. Clone the repository:
   ```
   git clone https://github.com/yourusername/crypto-arbitrage-tool.git
   cd crypto-arbitrage-tool
   ```

2. Create a virtual environment:
   ```
   python -m venv venv
   ```

3. Activate the virtual environment:
   - Windows: `venv\Scripts\activate`
   - macOS/Linux: `source venv/bin/activate`

4. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

5. Run the application:
   ```
   python src/main.py
   ```

6. Access the web interface:
   - Open your browser and navigate to: `http://localhost:5000`

## Security Considerations

- This tool is designed for use with test/demo environments only
- Never use real trading API keys with this tool without thorough testing
- Store your API keys securely and never commit them to version control
- Monitor your trades regularly to ensure proper functioning

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgements

- Binance API
- OKX API
- Flask framework
- WebSocket technology for real-time updates
