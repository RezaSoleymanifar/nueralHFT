import os 

ALPACA_API_BASE_URL = 'https://api.alpaca.markets'

try:
    ALPACA_API_KEY = os.environ['ALPACA_API_KEY']
    ALPACA_API_SECRET = os.environ['ALPACA_API_SECRET']
except:
    raise KeyError('Alpaca API secret and key not set up in OS environment.')