"""
Main entry point for the Simplified Crypto Arbitrage Web Application
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))  # DON'T CHANGE THIS !!!

from flask import Flask, render_template, send_from_directory, jsonify, request
import logging
from logging.handlers import RotatingFileHandler
import threading
import time
import json
import datetime
import csv
import requests
import hmac
import hashlib
import base64
from io import StringIO

# Create Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)

# Global variables
config = {}
active_trades = {}
trade_cooldowns = {}
price_update_thread = None
balance_update_thread = None
auto_trade_thread = None
stop_threads = False

# Constants
CONFIG_FILE = 'config.json'
TRADE_LOG_FILE = 'trade_log.csv'

# Default configuration
DEFAULT_CONFIG = {
    'binance': {
        'api_key': '',
        'api_secret': '',
        'taker_fee': 0.001,
        'base_url': 'https://testnet.binance.vision/api',
    },
    'okx': {
        'api_key': '',
        'api_secret': '',
        'passphrase': '',
        'taker_fee': 0.001,
        'base_url': 'https://www.okx.com',
        'demo_trading': True
    },
    'min_profit_threshold': 0.09,
    'max_concurrent_trades': 3,
    'refresh_interval': 10,
    'trade_cooldown': 60,
    'auto_trade': False,
    'use_websocket': False
}

# Configure logging
if not os.path.exists('logs'):
    os.makedirs('logs')

file_handler = RotatingFileHandler('logs/app.log', maxBytes=10240, backupCount=10)
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
))
file_handler.setLevel(logging.INFO)
app.logger.addHandler(file_handler)
app.logger.setLevel(logging.INFO)
app.logger.info('Simplified Crypto Arbitrage Web Application startup')

# Helper functions
def load_config():
    """Load configuration from file or create default"""
    global config
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
        else:
            # Create default config file
            with open(CONFIG_FILE, 'w') as f:
                json.dump(DEFAULT_CONFIG, f, indent=4)
            config = DEFAULT_CONFIG
        return config
    except Exception as e:
        app.logger.error(f"Error loading config: {e}")
        config = DEFAULT_CONFIG
        return config

def save_config(new_config):
    """Save configuration to file"""
    global config
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(new_config, f, indent=4)
        config = new_config
        return True
    except Exception as e:
        app.logger.error(f"Error saving config: {e}")
        return False

def init_trade_log():
    """Initialize trade log file if it doesn't exist"""
    if not os.path.exists(TRADE_LOG_FILE):
        with open(TRADE_LOG_FILE, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                'timestamp', 'coin', 'buy_exchange', 'buy_price', 
                'sell_exchange', 'sell_price', 'amount', 
                'gross_profit', 'fees', 'net_profit', 'status',
                'buy_order_id', 'sell_order_id', 'error', 'trade_type'
            ])

def log_trade(trade_data):
    """Log a trade to the CSV file"""
    try:
        with open(TRADE_LOG_FILE, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                trade_data.get('timestamp', ''),
                trade_data.get('coin', ''),
                trade_data.get('buy_exchange', ''),
                trade_data.get('buy_price', 0),
                trade_data.get('sell_exchange', ''),
                trade_data.get('sell_price', 0),
                trade_data.get('amount', 0),
                trade_data.get('gross_profit', 0),
                trade_data.get('fees', 0),
                trade_data.get('net_profit', 0),
                trade_data.get('status', ''),
                trade_data.get('buy_order_id', ''),
                trade_data.get('sell_order_id', ''),
                trade_data.get('error', ''),
                trade_data.get('trade_type', 'Manual')
            ])
        return True
    except Exception as e:
        app.logger.error(f"Error logging trade: {e}")
        return False

def get_binance_signature(query_string, secret):
    """Generate Binance API signature"""
    return hmac.new(
        secret.encode('utf-8'),
        query_string.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()

def get_okx_signature(timestamp, method, request_path, body, secret):
    """Generate OKX API signature"""
    if str(body) == '{}' or str(body) == 'None':
        body = ''
    message = timestamp + method + request_path + body
    mac = hmac.new(
        bytes(secret, encoding='utf8'),
        bytes(message, encoding='utf-8'),
        digestmod='sha256'
    )
    return base64.b64encode(mac.digest()).decode()

def get_binance_prices():
    """Get prices from Binance API"""
    try:
        response = requests.get(f"{config['binance']['base_url']}/v3/ticker/price")
        if response.status_code == 200:
            all_prices = response.json()
            # Filter for USDT pairs and convert to dictionary
            prices = {}
            for item in all_prices:
                symbol = item['symbol']
                if symbol.endswith('USDT'):
                    coin = symbol[:-4]  # Remove USDT suffix
                    price = float(item['price'])
                    # Only include coins under $5
                    if price < 5.0:
                        prices[coin] = price
            return prices
        else:
            app.logger.error(f"Error getting Binance prices: {response.status_code} - {response.text}")
            return {}
    except Exception as e:
        app.logger.error(f"Exception getting Binance prices: {e}")
        return {}

def get_okx_prices():
    """Get prices from OKX API"""
    try:
        url = f"{config['okx']['base_url']}/api/v5/market/tickers?instType=SPOT"
        
        headers = {}
        if config['okx']['demo_trading']:
            headers['x-simulated-trading'] = '1'
        
        response = requests.get(url, headers=headers)
        
        if response.status_code == 200:
            data = response.json()
            if data['code'] == '0':
                all_tickers = data['data']
                # Filter for USDT pairs and convert to dictionary
                prices = {}
                for ticker in all_tickers:
                    symbol = ticker['instId']
                    if symbol.endswith('-USDT'):
                        coin = symbol.split('-')[0]
                        price = float(ticker['last'])
                        # Only include coins under $5
                        if price < 5.0:
                            prices[coin] = price
                return prices
            else:
                app.logger.error(f"OKX API error: {data['msg']}")
                return {}
        else:
            app.logger.error(f"Error getting OKX prices: {response.status_code} - {response.text}")
            return {}
    except Exception as e:
        app.logger.error(f"Exception getting OKX prices: {e}")
        return {}

def get_binance_balances():
    """Get account balances from Binance API"""
    if not config['binance']['api_key'] or not config['binance']['api_secret']:
        return []
    
    try:
        timestamp = int(time.time() * 1000)
        query_string = f"timestamp={timestamp}"
        signature = get_binance_signature(query_string, config['binance']['api_secret'])
        
        url = f"{config['binance']['base_url']}/v3/account?{query_string}&signature={signature}"
        headers = {
            'X-MBX-APIKEY': config['binance']['api_key']
        }
        
        response = requests.get(url, headers=headers)
        
        if response.status_code == 200:
            data = response.json()
            # Filter for non-zero balances
            balances = [b for b in data['balances'] if float(b['free']) > 0 or float(b['locked']) > 0]
            return balances
        else:
            app.logger.error(f"Error getting Binance balances: {response.status_code} - {response.text}")
            return []
    except Exception as e:
        app.logger.error(f"Exception getting Binance balances: {e}")
        return []

def get_okx_balances():
    """Get account balances from OKX API"""
    if not config['okx']['api_key'] or not config['okx']['api_secret'] or not config['okx']['passphrase']:
        return []
    
    try:
        timestamp = datetime.datetime.utcnow().isoformat()[:-3] + 'Z'
        method = 'GET'
        request_path = '/api/v5/account/balance'
        body = ''
        
        signature = get_okx_signature(timestamp, method, request_path, body, config['okx']['api_secret'])
        
        url = f"{config['okx']['base_url']}{request_path}"
        headers = {
            'OK-ACCESS-KEY': config['okx']['api_key'],
            'OK-ACCESS-SIGN': signature,
            'OK-ACCESS-TIMESTAMP': timestamp,
            'OK-ACCESS-PASSPHRASE': config['okx']['passphrase'],
            'Content-Type': 'application/json'
        }
        
        if config['okx']['demo_trading']:
            headers['x-simulated-trading'] = '1'
        
        response = requests.get(url, headers=headers)
        
        if response.status_code == 200:
            data = response.json()
            if data['code'] == '0':
                # Extract balances from response
                if data['data'] and len(data['data']) > 0:
                    balances = data['data'][0]['details']
                    # Filter for non-zero balances
                    balances = [b for b in balances if float(b['availBal']) > 0 or float(b['cashBal']) > 0]
                    return balances
                else:
                    return []
            else:
                app.logger.error(f"OKX API error: {data['msg']}")
                return []
        else:
            app.logger.error(f"Error getting OKX balances: {response.status_code} - {response.text}")
            return []
    except Exception as e:
        app.logger.error(f"Exception getting OKX balances: {e}")
        return []

def calculate_trade_amount(price):
    """Calculate trade amount based on price"""
    if price > 3.5:
        return 1
    elif price >= 1:
        return 4
    elif price >= 0.5:
        return 8
    else:
        return 15

def calculate_opportunities(binance_prices, okx_prices):
    """Calculate arbitrage opportunities between exchanges"""
    opportunities = []
    
    # Find common coins
    common_coins = set(binance_prices.keys()).intersection(set(okx_prices.keys()))
    
    for coin in common_coins:
        binance_price = binance_prices[coin]
        okx_price = okx_prices[coin]
        
        # Calculate price difference percentage
        if binance_price < okx_price:
            buy_exchange = 'Binance'
            sell_exchange = 'OKX'
            buy_price = binance_price
            sell_price = okx_price
        else:
            buy_exchange = 'OKX'
            sell_exchange = 'Binance'
            buy_price = okx_price
            sell_price = binance_price
        
        price_diff = sell_price - buy_price
        price_diff_pct = (price_diff / buy_price) * 100
        
        # Calculate trade amount based on price
        trade_amount = calculate_trade_amount(buy_price)
        
        # Calculate fees
        binance_fee = config['binance']['taker_fee'] * (buy_price if buy_exchange == 'Binance' else sell_price) * trade_amount
        okx_fee = config['okx']['taker_fee'] * (buy_price if buy_exchange == 'OKX' else sell_price) * trade_amount
        total_fees = binance_fee + okx_fee
        
        # Calculate profit
        gross_profit = price_diff * trade_amount
        net_profit = gross_profit - total_fees
        
        # Check if trade is in cooldown
        in_cooldown = coin in trade_cooldowns and trade_cooldowns[coin] > time.time()
        
        # Check if profitable
        profitable = net_profit > config['min_profit_threshold']
        
        opportunities.append({
            'coin': coin,
            'buy_exchange': buy_exchange,
            'buy_price': buy_price,
            'sell_exchange': sell_exchange,
            'sell_price': sell_price,
            'price_diff': price_diff,
            'price_diff_pct': price_diff_pct,
            'trade_amount': trade_amount,
            'gross_profit': gross_profit,
            'fees': total_fees,
            'net_profit': net_profit,
            'profitable': profitable,
            'in_cooldown': in_cooldown
        })
    
    # Sort by net profit (descending)
    opportunities.sort(key=lambda x: x['net_profit'], reverse=True)
    
    return opportunities

def place_binance_order(coin, side, quantity):
    """Place an order on Binance"""
    try:
        timestamp = int(time.time() * 1000)
        symbol = f"{coin}USDT"
        
        params = {
            'symbol': symbol,
            'side': side,  # 'BUY' or 'SELL'
            'type': 'MARKET',
            'quantity': quantity,
            'timestamp': timestamp
        }
        
        query_string = '&'.join([f"{k}={v}" for k, v in params.items()])
        signature = get_binance_signature(query_string, config['binance']['api_secret'])
        
        url = f"{config['binance']['base_url']}/v3/order?{query_string}&signature={signature}"
        headers = {
            'X-MBX-APIKEY': config['binance']['api_key']
        }
        
        response = requests.post(url, headers=headers)
        
        if response.status_code == 200:
            return response.json()
        else:
            app.logger.error(f"Error placing Binance order: {response.status_code} - {response.text}")
            return {'error': response.text}
    except Exception as e:
        app.logger.error(f"Exception placing Binance order: {e}")
        return {'error': str(e)}

def place_okx_order(coin, side, quantity):
    """Place an order on OKX"""
    try:
        timestamp = datetime.datetime.utcnow().isoformat()[:-3] + 'Z'
        method = 'POST'
        request_path = '/api/v5/trade/order'
        
        # Convert side to OKX format
        okx_side = 'buy' if side == 'BUY' else 'sell'
        
        body = {
            'instId': f"{coin}-USDT",
            'tdMode': 'cash',
            'side': okx_side,
            'ordType': 'market',
            'sz': str(quantity)
        }
        
        body_str = json.dumps(body)
        signature = get_okx_signature(timestamp, method, request_path, body_str, config['okx']['api_secret'])
        
        url = f"{config['okx']['base_url']}{request_path}"
        headers = {
            'OK-ACCESS-KEY': config['okx']['api_key'],
            'OK-ACCESS-SIGN': signature,
            'OK-ACCESS-TIMESTAMP': timestamp,
            'OK-ACCESS-PASSPHRASE': config['okx']['passphrase'],
            'Content-Type': 'application/json'
        }
        
        if config['okx']['demo_trading']:
            headers['x-simulated-trading'] = '1'
        
        response = requests.post(url, headers=headers, json=body)
        
        if response.status_code == 200:
            data = response.json()
            if data['code'] == '0':
                return data['data'][0]
            else:
                app.logger.error(f"OKX API error: {data['msg']}")
                return {'error': data['msg']}
        else:
            app.logger.error(f"Error placing OKX order: {response.status_code} - {response.text}")
            return {'error': response.text}
    except Exception as e:
        app.logger.error(f"Exception placing OKX order: {e}")
        return {'error': str(e)}

def execute_trade(coin, trade_type='Manual'):
    """Execute a trade for a specific coin"""
    # Get current prices
    binance_prices = get_binance_prices()
    okx_prices = get_okx_prices()
    
    if coin not in binance_prices or coin not in okx_prices:
        return {
            'success': False,
            'message': f"Coin {coin} not found in one or both exchanges"
        }
    
    # Determine buy and sell exchanges
    binance_price = binance_prices[coin]
    okx_price = okx_prices[coin]
    
    if binance_price < okx_price:
        buy_exchange = 'Binance'
        sell_exchange = 'OKX'
        buy_price = binance_price
        sell_price = okx_price
    else:
        buy_exchange = 'OKX'
        sell_exchange = 'Binance'
        buy_price = okx_price
        sell_price = binance_price
    
    # Calculate trade amount
    trade_amount = calculate_trade_amount(buy_price)
    
    # Calculate fees and profit
    binance_fee = config['binance']['taker_fee'] * (buy_price if buy_exchange == 'Binance' else sell_price) * trade_amount
    okx_fee = config['okx']['taker_fee'] * (buy_price if buy_exchange == 'OKX' else sell_price) * trade_amount
    total_fees = binance_fee + okx_fee
    
    gross_profit = (sell_price - buy_price) * trade_amount
    net_profit = gross_profit - total_fees
    
    # Generate trade ID
    trade_id = f"{coin}-{int(time.time())}"
    
    # Log trade initiation
    trade_data = {
        'timestamp': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'coin': coin,
        'buy_exchange': buy_exchange,
        'buy_price': buy_price,
        'sell_exchange': sell_exchange,
        'sell_price': sell_price,
        'amount': trade_amount,
        'gross_profit': gross_profit,
        'fees': total_fees,
        'net_profit': net_profit,
        'status': 'Initiated',
        'buy_order_id': '',
        'sell_order_id': '',
        'error': '',
        'trade_type': trade_type
    }
    
    log_trade(trade_data)
    
    # Add to active trades
    active_trades[trade_id] = trade_data
    
    # Add to cooldown
    trade_cooldowns[coin] = time.time() + config['trade_cooldown']
    
    # Start trade execution in a separate thread
    thread = threading.Thread(target=process_trade, args=(trade_id, trade_data))
    thread.daemon = True
    thread.start()
    
    return {
        'success': True,
        'trade_id': trade_id,
        'message': f"Trade initiated for {coin}"
    }

def process_trade(trade_id, trade_data):
    """Process a trade in a separate thread"""
    try:
        coin = trade_data['coin']
        buy_exchange = trade_data['buy_exchange']
        sell_exchange = trade_data['sell_exchange']
        trade_amount = trade_data['amount']
        
        app.logger.info(f"Processing trade {trade_id}: Buy {trade_amount} {coin} on {buy_exchange}, Sell on {sell_exchange}")
        
        # Update trade status
        trade_data['status'] = f"Placing buy order on {buy_exchange}"
        log_trade(trade_data)
        
        # Place buy order
        if buy_exchange == 'Binance':
            buy_result = place_binance_order(coin, 'BUY', trade_amount)
        else:  # OKX
            buy_result = place_okx_order(coin, 'BUY', trade_amount)
        
        if 'error' in buy_result:
            # Buy order failed
            trade_data['status'] = 'Failed'
            trade_data['error'] = f"Buy order failed: {buy_result['error']}"
            log_trade(trade_data)
            
            # Remove from active trades
            if trade_id in active_trades:
                del active_trades[trade_id]
            
            app.logger.error(f"Trade {trade_id} failed: {trade_data['error']}")
            return
        
        # Buy order succeeded
        trade_data['buy_order_id'] = buy_result.get('ordId', buy_result.get('orderId', 'unknown'))
        trade_data['status'] = f"Placing sell order on {sell_exchange}"
        log_trade(trade_data)
        
        # Place sell order
        if sell_exchange == 'Binance':
            sell_result = place_binance_order(coin, 'SELL', trade_amount)
        else:  # OKX
            sell_result = place_okx_order(coin, 'SELL', trade_amount)
        
        if 'error' in sell_result:
            # Sell order failed
            trade_data['status'] = 'Failed'
            trade_data['error'] = f"Sell order failed: {sell_result['error']}"
            log_trade(trade_data)
            
            # Remove from active trades
            if trade_id in active_trades:
                del active_trades[trade_id]
            
            app.logger.error(f"Trade {trade_id} failed: {trade_data['error']}")
            return
        
        # Sell order succeeded
        trade_data['sell_order_id'] = sell_result.get('ordId', sell_result.get('orderId', 'unknown'))
        trade_data['status'] = 'Completed'
        log_trade(trade_data)
        
        # Remove from active trades
        if trade_id in active_trades:
            del active_trades[trade_id]
        
        app.logger.info(f"Trade {trade_id} completed successfully")
        
    except Exception as e:
        # Handle any unexpected errors
        trade_data['status'] = 'Failed'
        trade_data['error'] = f"Unexpected error: {str(e)}"
        log_trade(trade_data)
        
        # Remove from active trades
        if trade_id in active_trades:
            del active_trades[trade_id]
        
        app.logger.error(f"Trade {trade_id} failed with exception: {str(e)}")

def get_trade_history(limit=None, status=None, coin=None):
    """Get trade history with optional filtering"""
    try:
        if not os.path.exists(TRADE_LOG_FILE):
            return []
        
        # Read CSV file
        trades = []
        with open(TRADE_LOG_FILE, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                trades.append(row)
        
        # Apply filters
        if status:
            trades = [t for t in trades if t['status'] == status]
        
        if coin:
            trades = [t for t in trades if t['coin'] == coin]
        
        # Sort by timestamp (descending)
        trades.sort(key=lambda x: x['timestamp'], reverse=True)
        
        # Apply limit
        if limit and isinstance(limit, int):
            trades = trades[:limit]
        
        return trades
            
    except Exception as e:
        app.logger.error(f"Error getting trade history: {e}")
        return []

def get_trade_statistics():
    """Calculate trade statistics"""
    try:
        if not os.path.exists(TRADE_LOG_FILE):
            return {
                'total_trades': 0,
                'completed_trades': 0,
                'failed_trades': 0,
                'total_profit': 0,
                'avg_profit': 0
            }
        
        # Read CSV file
        trades = []
        with open(TRADE_LOG_FILE, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                trades.append(row)
        
        if not trades:
            return {
                'total_trades': 0,
                'completed_trades': 0,
                'failed_trades': 0,
                'total_profit': 0,
                'avg_profit': 0
            }
        
        # Calculate statistics
        total_trades = len(trades)
        completed_trades = len([t for t in trades if t['status'] == 'Completed'])
        failed_trades = len([t for t in trades if t['status'] == 'Failed'])
        
        # Filter for completed trades for profit calculations
        completed_trades_list = [t for t in trades if t['status'] == 'Completed']
        
        total_profit = sum(float(t['net_profit']) for t in completed_trades_list) if completed_trades_list else 0
        avg_profit = total_profit / completed_trades if completed_trades > 0 else 0
        
        return {
            'total_trades': total_trades,
            'completed_trades': completed_trades,
            'failed_trades': failed_trades,
            'total_profit': total_profit,
            'avg_profit': avg_profit
        }
            
    except Exception as e:
        app.logger.error(f"Error calculating trade statistics: {e}")
        return {
            'error': str(e)
        }

def background_price_updates():
    """Background thread for price updates"""
    global stop_threads
    
    while not stop_threads:
        try:
            # Check if websocket is enabled
            if not config['use_websocket']:
                time.sleep(5)
                continue
            
            # Get prices from both exchanges
            binance_prices = get_binance_prices()
            okx_prices = get_okx_prices()
            
            # Calculate opportunities
            opportunities = calculate_opportunities(binance_prices, okx_prices)
            
            # Sleep for refresh interval
            time.sleep(config['refresh_interval'])
        except Exception as e:
            app.logger.error(f"Error in price update thread: {e}")
            time.sleep(5)

def background_balance_updates():
    """Background thread for balance updates"""
    global stop_threads
    
    while not stop_threads:
        try:
            # Check if websocket is enabled
            if not config['use_websocket']:
                time.sleep(5)
                continue
            
            # Get balances from both exchanges
            get_binance_balances()
            get_okx_balances()
            
            # Sleep for 30 seconds (balance updates less frequent than price updates)
            time.sleep(30)
        except Exception as e:
            app.logger.error(f"Error in balance update thread: {e}")
            time.sleep(5)

def auto_trade_monitor():
    """Background thread for monitoring and executing auto-trades"""
    global stop_threads
    
    app.logger.info("Starting auto-trade monitor thread")
    
    while not stop_threads:
        try:
            # Check if auto-trade is enabled
            if not config['auto_trade']:
                time.sleep(5)
                continue
            
            # Check if we have too many active trades
            if len(active_trades) >= config['max_concurrent_trades']:
                time.sleep(5)
                continue
            
            # Get current prices
            binance_prices = get_binance_prices()
            okx_prices = get_okx_prices()
            
            # Calculate opportunities
            opportunities = calculate_opportunities(binance_prices, okx_prices)
            
            # Filter for profitable opportunities not in cooldown
            profitable_opportunities = [
                o for o in opportunities 
                if o['profitable'] and not o['in_cooldown']
            ]
            
            # Execute the most profitable opportunity
            if profitable_opportunities:
                best_opportunity = profitable_opportunities[0]
                app.logger.info(f"Auto-trade found profitable opportunity: {best_opportunity['coin']}")
                
                # Execute trade
                execute_trade(best_opportunity['coin'], 'Auto')
            
            # Sleep for a few seconds
            time.sleep(10)
            
        except Exception as e:
            app.logger.error(f"Error in auto-trade monitor: {str(e)}")
            time.sleep(5)

def start_background_threads():
    """Start background threads"""
    global price_update_thread, balance_update_thread, auto_trade_thread, stop_threads
    
    stop_threads = False
    
    if price_update_thread is None or not price_update_thread.is_alive():
        price_update_thread = threading.Thread(target=background_price_updates)
        price_update_thread.daemon = True
        price_update_thread.start()
    
    if balance_update_thread is None or not balance_update_thread.is_alive():
        balance_update_thread = threading.Thread(target=background_balance_updates)
        balance_update_thread.daemon = True
        balance_update_thread.start()
    
    if auto_trade_thread is None or not auto_trade_thread.is_alive():
        auto_trade_thread = threading.Thread(target=auto_trade_monitor)
        auto_trade_thread.daemon = True
        auto_trade_thread.start()

def stop_background_threads():
    """Stop background threads"""
    global stop_threads
    stop_threads = True

# Initialize configuration
load_config()
init_trade_log()

# API routes
@app.route('/api/prices', methods=['GET'])
def api_prices():
    """Get prices from both exchanges"""
    binance_prices = get_binance_prices()
    okx_prices = get_okx_prices()
    
    return jsonify({
        'binance_prices': binance_prices,
        'okx_prices': okx_prices,
        'timestamp': datetime.datetime.now().isoformat()
    })

@app.route('/api/balances', methods=['GET'])
def api_balances():
    """Get balances from both exchanges"""
    binance_balances = get_binance_balances()
    okx_balances = get_okx_balances()
    
    return jsonify({
        'binance_balances': binance_balances,
        'okx_balances': okx_balances,
        'timestamp': datetime.datetime.now().isoformat()
    })

@app.route('/api/opportunities', methods=['GET'])
def api_opportunities():
    """Get arbitrage opportunities"""
    binance_prices = get_binance_prices()
    okx_prices = get_okx_prices()
    
    opportunities = calculate_opportunities(binance_prices, okx_prices)
    
    return jsonify({
        'opportunities': opportunities,
        'timestamp': datetime.datetime.now().isoformat()
    })

@app.route('/api/trade', methods=['POST'])
def api_trade():
    """Execute a trade"""
    data = request.json
    
    if not data or 'coin' not in data:
        return jsonify({
            'success': False,
            'message': 'Missing required parameter: coin'
        }), 400
    
    result = execute_trade(data['coin'])
    
    return jsonify(result)

@app.route('/api/trade_history', methods=['GET'])
def api_trade_history():
    """Get trade history"""
    limit = request.args.get('limit', type=int)
    status = request.args.get('status')
    coin = request.args.get('coin')
    
    trades = get_trade_history(limit, status, coin)
    
    return jsonify({
        'trades': trades,
        'timestamp': datetime.datetime.now().isoformat()
    })

@app.route('/api/trade_statistics', methods=['GET'])
def api_trade_statistics():
    """Get trade statistics"""
    statistics = get_trade_statistics()
    
    return jsonify({
        'statistics': statistics,
        'timestamp': datetime.datetime.now().isoformat()
    })

@app.route('/api/config', methods=['GET'])
def api_get_config():
    """Get configuration"""
    # Remove sensitive information
    safe_config = dict(config)
    if 'binance' in safe_config:
        if 'api_key' in safe_config['binance']:
            safe_config['binance']['api_key'] = bool(safe_config['binance']['api_key'])
        if 'api_secret' in safe_config['binance']:
            safe_config['binance']['api_secret'] = bool(safe_config['binance']['api_secret'])
    
    if 'okx' in safe_config:
        if 'api_key' in safe_config['okx']:
            safe_config['okx']['api_key'] = bool(safe_config['okx']['api_key'])
        if 'api_secret' in safe_config['okx']:
            safe_config['okx']['api_secret'] = bool(safe_config['okx']['api_secret'])
        if 'passphrase' in safe_config['okx']:
            safe_config['okx']['passphrase'] = bool(safe_config['okx']['passphrase'])
    
    return jsonify({
        'config': safe_config,
        'timestamp': datetime.datetime.now().isoformat()
    })

@app.route('/api/config', methods=['POST'])
def api_set_config():
    """Set configuration"""
    data = request.json
    
    if not data:
        return jsonify({
            'success': False,
            'message': 'Missing configuration data'
        }), 400
    
    # Update configuration
    new_config = dict(config)
    
    # Update Binance configuration
    if 'binance' in data:
        if 'api_key' in data['binance']:
            new_config['binance']['api_key'] = data['binance']['api_key']
        if 'api_secret' in data['binance']:
            new_config['binance']['api_secret'] = data['binance']['api_secret']
        if 'taker_fee' in data['binance']:
            new_config['binance']['taker_fee'] = float(data['binance']['taker_fee'])
    
    # Update OKX configuration
    if 'okx' in data:
        if 'api_key' in data['okx']:
            new_config['okx']['api_key'] = data['okx']['api_key']
        if 'api_secret' in data['okx']:
            new_config['okx']['api_secret'] = data['okx']['api_secret']
        if 'passphrase' in data['okx']:
            new_config['okx']['passphrase'] = data['okx']['passphrase']
        if 'taker_fee' in data['okx']:
            new_config['okx']['taker_fee'] = float(data['okx']['taker_fee'])
        if 'demo_trading' in data['okx']:
            new_config['okx']['demo_trading'] = bool(data['okx']['demo_trading'])
    
    # Update general configuration
    if 'min_profit_threshold' in data:
        new_config['min_profit_threshold'] = float(data['min_profit_threshold'])
    if 'max_concurrent_trades' in data:
        new_config['max_concurrent_trades'] = int(data['max_concurrent_trades'])
    if 'refresh_interval' in data:
        new_config['refresh_interval'] = int(data['refresh_interval'])
    if 'trade_cooldown' in data:
        new_config['trade_cooldown'] = int(data['trade_cooldown'])
    if 'auto_trade' in data:
        new_config['auto_trade'] = bool(data['auto_trade'])
    if 'use_websocket' in data:
        new_config['use_websocket'] = bool(data['use_websocket'])
    
    # Save configuration
    success = save_config(new_config)
    
    return jsonify({
        'success': success,
        'message': 'Configuration updated' if success else 'Failed to update configuration'
    })

@app.route('/api/auto_trade', methods=['POST'])
def api_auto_trade():
    """Enable or disable auto-trading"""
    data = request.json
    
    if not data or 'enabled' not in data:
        return jsonify({
            'success': False,
            'message': 'Missing required parameter: enabled'
        }), 400
    
    # Update configuration
    new_config = dict(config)
    new_config['auto_trade'] = bool(data['enabled'])
    
    # Save configuration
    success = save_config(new_config)
    
    return jsonify({
        'success': success,
        'auto_trade': new_config['auto_trade'],
        'message': f"Auto-trading {'enabled' if new_config['auto_trade'] else 'disabled'}"
    })

@app.route('/api/websocket', methods=['POST'])
def api_websocket():
    """Enable or disable WebSocket updates"""
    data = request.json
    
    if not data or 'enabled' not in data:
        return jsonify({
            'success': False,
            'message': 'Missing required parameter: enabled'
        }), 400
    
    # Update configuration
    new_config = dict(config)
    new_config['use_websocket'] = bool(data['enabled'])
    
    # Save configuration
    success = save_config(new_config)
    
    return jsonify({
        'success': success,
        'use_websocket': new_config['use_websocket'],
        'message': f"WebSocket {'enabled' if new_config['use_websocket'] else 'disabled'}"
    })

@app.route('/api/export_trades', methods=['GET'])
def api_export_trades():
    """Export trade history as CSV"""
    if not os.path.exists(TRADE_LOG_FILE):
        return jsonify({
            'success': False,
            'message': 'No trade history available'
        }), 404
    
    # Create in-memory CSV
    output = StringIO()
    with open(TRADE_LOG_FILE, 'r') as f:
        output.write(f.read())
    
    output.seek(0)
    
    return app.response_class(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment;filename=trade_history.csv'}
    )

# Routes
@app.route('/')
def index():
    """Serve the main application page"""
    return send_from_directory('static', 'index.html')

@app.route('/favicon.ico')
def favicon():
    """Serve the favicon"""
    return send_from_directory('static', 'favicon.ico')

@app.route('/health')
def health_check():
    """Health check endpoint for monitoring"""
    return jsonify({"status": "healthy"})

# Error handlers
@app.errorhandler(404)
def not_found_error(error):
    """Handle 404 errors"""
    return jsonify({
        'error': 'Not Found',
        'message': 'The requested URL was not found on the server.'
    }), 404

@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors"""
    app.logger.error(f"Server Error: {error}")
    return jsonify({
        'error': 'Internal Server Error',
        'message': 'The server encountered an internal error and was unable to complete your request.'
    }), 500

# Start background threads when the app starts
@app.before_first_request
def before_first_request():
    """Start background threads before first request"""
    app.logger.info("Starting background threads")
    start_background_threads()

# Cleanup when the app shuts down
@app.teardown_appcontext
def teardown_appcontext(exception=None):
    """Clean up resources when the app shuts down"""
    app.logger.info("Shutting down background threads")
    stop_background_threads()

# Run the app
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
