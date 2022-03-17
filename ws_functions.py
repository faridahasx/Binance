import logging
logging.basicConfig(level=logging.INFO, filename='bot.log', format='%(asctime)s:%(levelname)s:%(message)s', )


def on_open(ws):
    logging.info("Opened connection")


def on_close(ws, close_status_code, close_msg):
    logging.critical("Closed connection")


def on_error(ws, error):
    logging.error(error)


def on_ping(wsapp, message):
    pass


def on_pong(wsapp, message):
    pass

