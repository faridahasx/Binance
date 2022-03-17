import logging
import websocket
import json
import time
import ccxt
import threading
import warnings
from datetime import datetime as dt
from binance.client import Client
from ws_functions import on_close, on_open, on_ping, on_pong, on_error
from config import *

warnings.filterwarnings('ignore')

exchange = ccxt.binance({
    'options': {
        'adjustForTimeDifference': True,
        'recvWindow': 50000,
    },
    'enableRateLimit': True,
    'apiKey': API_KEY,
    'secret': API_SECRET,
})
exchange.load_markets()

client = Client(api_key=API_KEY, api_secret=API_SECRET)
logging.basicConfig(level=logging.INFO, filename='bot.log', format='%(asctime)s:%(levelname)s:%(message)s', )

balance = exchange.fetch_balance()
USDT_balance = float(balance['USDT']['free'])

order_IDs = []
filled_buy_orders = {}
open_sell_orders = {}
last_order_timestamp = 0

# Add streams
streams = {"1INCHUSDT": 'kline_1h', "BTCUSDT": 'kline_1d', "BNBUSDT": 'kline_1d', "ETHUSDT": 'kline_1h',
           "FTMUSDT": 'kline_1h',"SOLUSDT": 'kline_1h'}

# Total USDT amount for each position
USDT_to_spend = {"1INCHUSDT": 500, "BTCUSDT": 1000, "BNBUSDT": 1000, "ETHUSDT": 500, "FTMUSDT": 500, "SOLUSDT": 500}

# The bot will give  Fill or Kill order immediately,
# when the current price drops x% from the opening level of the current candle
percentage_drop_to_enter = {"1INCHUSDT": -15, "BTCUSDT": -10, "BNBUSDT": -20, "ETHUSDT": -15, "FTMUSDT": -15, "SOLUSDT": -15}

# Take x% profit
take_profit = {"1INCHUSDT": 5, "BTCUSDT": 5, "BNBUSDT": 20, "ETHUSDT": 5, "FTMUSDT": 5, "SOLUSDT": 5}

positions = {"1INCHUSDT": False, "BTCUSDT": False, "BNBUSDT": False, "ETHUSDT": False, "FTMUSDT": False, "SOLUSDT": False}


SOCKET = 'wss://stream.binance.com:9443/ws'
for stream in streams:
    SOCKET += '/' + stream.lower() + '@' + streams[stream]


def on_message(ws, message):
    global positions, USDT_to_spend, order_IDs, last_order_timestamp, USDT_balance, open_sell_orders
    json_array = json.loads(message)
    pair = json_array['s']
    opening = float(json_array['k']['o'])
    close = float(json_array['k']['c'])
    low = float(json_array['k']['l'])
    entry_price = opening * ((100 + percentage_drop_to_enter[pair]) / 100)
    exit_price = entry_price * ((100 + take_profit[pair]) / 100)

    if dt.now().minute == 0:
        for p in positions:
            if p not in open_sell_orders:
                positions[p] = False

    else:
        if close <= entry_price and positions[pair] is False:
            now = dt.now()
            now_timestamp = int(str((dt.timestamp(now) * 1000))[:13])

            if now_timestamp - last_order_timestamp > 900:
                try:
                    amount = USDT_to_spend[pair] / entry_price
                    params = {'timeInForce': 'FOK', }
                    buy_amount = exchange.amount_to_precision(symbol=pair, amount=amount)
                    buy_price = exchange.price_to_precision(symbol=pair, price=entry_price)

                    if float(buy_amount) * float(buy_price) > 10 and float(buy_amount) * float(
                            buy_price) >= USDT_balance:
                        buy_order = exchange.create_limit_buy_order(symbol=pair, price=buy_price,
                                                                    amount=buy_amount, params=params)

                        order_IDs.append(int(buy_order['id']))
                        last_order_timestamp = buy_order['timestamp']
                except:
                    pass

        elif low <= entry_price and close >= exit_price and positions[pair] is False:
            positions[pair] = True


def user_data_stream():
    while True:
        key = client.stream_get_listen_key()
        socket = f'wss://stream.binance.com:9443/ws/{key}'

        def on_message(ws, message):
            global USDT_balance, order_IDs, positions, open_sell_orders, take_profit
            json_array = json.loads(message)

            # Update balance
            if json_array["e"] == 'outboundAccountPosition':
                for balance in json_array['B']:
                    if balance['a'] == 'USDT':
                        USDT_balance = float(balance['f'])

            # Check filled buy orders
            elif json_array["e"] == 'executionReport':
                side = json_array["S"]
                status = json_array["X"]
                symbol = json_array["s"]
                filled_USDT_quantity = float(json_array["Z"])
                time_in_force = json_array['f']
                order_id = json_array['i']
                price = json_array['p']
                executed_quantity = float(json_array["z"])

                if side == 'BUY' and status == 'EXPIRED' and order_id in order_IDs:
                    order_IDs.remove(order_id)

                if time_in_force == 'FOK' and side == 'BUY' and status == 'FILLED':
                    time.sleep(1.5)
                    if order_id in order_IDs:
                        order_IDs.remove(order_id)
                        positions[symbol] = True
                        logging.info(f'{symbol}:{status} {side}, filledqty: {filled_USDT_quantity}')

                        try:

                            sell_price = price * (1 + (take_profit[symbol] / 100))
                            sell_order = exchange.create_limit_sell_order(symbol=symbol, amount=executed_quantity,
                                                                          price=sell_price)
                            open_sell_orders[symbol] = symbol

                            order_IDs.append(int(sell_order['id']))
                        except Exception as e:
                            logging.error(f'Sell Order Error {e}')

                elif side == 'SELL' and status == 'FILLED' and order_id in order_IDs and symbol in open_sell_orders:
                    order_IDs.remove(order_id)
                    open_sell_orders.pop(symbol)

                    logging.info(f'{symbol}:{status} {side}')

        ws = websocket.WebSocketApp(socket, on_open=on_open, on_close=on_close, on_message=on_message,
                                    on_error=on_error,
                                    on_ping=on_ping, on_pong=on_pong)

        ws.run_forever()


def connect(on_message, socket):
    ws = websocket.WebSocketApp(socket, on_open=on_open,
                                on_close=on_close,
                                on_message=on_message, on_error=on_error,
                                on_ping=on_ping, on_pong=on_pong)
    while True:
        ws.run_forever()


if __name__ == '__main__':
    logging.info("\nBot Started...")

    threads = []

    thread = threading.Thread(target=connect, args=(on_message, SOCKET))
    thread.start()
    threads.append(thread)
    threads.append(thread)

    thread1 = threading.Thread(target=user_data_stream, args=())
    thread1.start()
    threads.append(thread1)
    threads.append(thread1)

    for t in threads:
        t.join()
