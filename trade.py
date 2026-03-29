import ccxt
import pandas as pd
import time
import requests
from datetime import datetime

# ════════════════════════════════════════════════════════════════════════════════
# CONFIGURATION — CHANGE THESE
# ════════════════════════════════════════════════════════════════════════════════
BOT_TOKEN = "YOUR_BOT_TOKEN"        # Get from @BotFather
CHAT_ID = "YOUR_CHAT_ID"            # Get from getUpdates
TIMEFRAME = "12h"
LIMIT = 60
VOL_MULT = 1.5                      # Volume multiplier (1.5x average)
MIN_USD_VOL = 500000                # Minimum 12h USD volume
SLEEP_BETWEEN = 0.12                # API rate limit safety

exchange = ccxt.binance({
    "enableRateLimit": True,
    "options": {"defaultType": "spot"}
})


# ════════════════════════════════════════════════════════════════════════════════
# TECHNICAL INDICATORS
# ════════════════════════════════════════════════════════════════════════════════
def ema(series, period):
    """Exponential Moving Average"""
    return pd.Series(series).ewm(span=period, adjust=False).mean()


def rsi(series, period=14):
    """Relative Strength Index"""
    s = pd.Series(series)
    delta = s.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    return 100 - (100 / (1 + rs))


def vwap(high, low, close, volume):
    """Volume Weighted Average Price"""
    tp = (pd.Series(high) + pd.Series(low) + pd.Series(close)) / 3
    vol = pd.Series(volume)
    return (tp * vol).cumsum() / vol.cumsum()


# ════════════════════════════════════════════════════════════════════════════════
# TELEGRAM ALERTS
# ════════════════════════════════════════════════════════════════════════════════
def send_telegram(message):
    """Send alert to Telegram"""
    if BOT_TOKEN == "YOUR_BOT_TOKEN" or CHAT_ID == "YOUR_CHAT_ID":
        print("📱 Telegram not configured — skipping")
        return
    
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, data={
            "chat_id": CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }, timeout=10)
        print("📱 Telegram alert sent")
    except Exception as e:
        print(f"Telegram error: {e}")


# ════════════════════════════════════════════════════════════════════════════════
# SYMBOLS & SCANNING
# ════════════════════════════════════════════════════════════════════════════════
def get_symbols():
    """Get all active USDT pairs"""
    markets = exchange.load_markets()
    symbols = [
        s for s in markets 
        if s.endswith('/USDT') 
        and markets[s]['active']
        and 'UP/' not in s and 'DOWN/' not in s and 'BULL/' not in s and 'BEAR/' not in s
    ]
    print(f"🔍 Found {len(symbols)} USDT pairs")
    return symbols


def check_symbol(symbol):
    """Check single symbol for EMA + VWAP + RSI + volume conditions"""
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME, limit=LIMIT)
        if len(ohlcv) < 50:
            return None
            
        df = pd.DataFrame(ohlcv, columns=['ts','open','high','low','close','volume'])
        
        # Calculate indicators
        df['ema9'] = ema(df['close'], 9)
        df['ema50'] = ema(df['close'], 50)
        df['rsi14'] = rsi(df['close'], 14)
        df['vwap'] = vwap(df['high'], df['low'], df['close'], df['volume'])
        
        last = df.iloc[-1]
        prev = df.iloc[-2]
        
        # EMA crossover
        bullish = prev['ema9'] < prev['ema50'] and last['ema9'] > last['ema50']
        bearish = prev['ema9'] > prev['ema50'] and last['ema9'] < last['ema50']
        
        # Volume conditions
        usd_volume = float(last['close'] * last['volume'])
        avg_vol20 = float(df['volume'].rolling(20).mean().iloc[-1])
        high_volume = bool(last['volume'] > avg_vol20 * VOL_MULT) if pd.notna(avg_vol20) else False
        enough_usd_volume = usd_volume >= MIN_USD_VOL
        
        # VWAP and RSI
        above_vwap = float(last['close']) > float(last['vwap'])
        below_vwap = float(last['close']) < float(last['vwap'])
        
        # Final filters
        buy = bullish and above_vwap and high_volume and enough_usd_volume and float(last['rsi14']) > 50
        sell = bearish and below_vwap and high_volume and enough_usd_volume and float(last['rsi14']) < 50
        
        if buy or sell:
            return {
                'symbol': symbol.replace('/USDT', ''),
                'signal': '🟢 BUY' if buy else '🔴 SELL',
                'close': float(last['close']),
                'ema9': float(last['ema9']),
                'ema50': float(last['ema50']),
                'vwap': float(last['vwap']),
                'rsi': float(last['rsi14']),
                'usd_volume': usd_volume,
                'timestamp': pd.to_datetime(last['ts'], unit='ms')
            }
    except Exception as e:
        print(f"❌ {symbol}: {e}")
    
    return None


# ════════════════════════════════════════════════════════════════════════════════
# MAIN SCANNER
# ════════════════════════════════════════════════════════════════════════════════
def scan():
    print(f"\n{'═'*80}")
    print(f"🔍 EMA 9/50 + VWAP + RSI + Volume Scanner | {TIMEFRAME} | {datetime.now().strftime('%Y-%m-%d %H:%M:%S IST')}")
    print(f"{'═'*80}\n")
    
    symbols = get_symbols()
    results = []
    
    for i, symbol in enumerate(symbols, 1):
        result = check_symbol(symbol)
        if result:
            results.append(result)
            msg = (
                f"<b>{result['signal']}</b> <code>{result['symbol']}</code>\n"
                f"💰 Close: <code>{result['close']:.6f}</code>\n"
                f"📊 EMA9: <code>{result['ema9']:.6f}</code> | EMA50: <code>{result['ema50']:.6f}</code>\n"
                f"📈 VWAP: <code>{result['vwap']:.6f}</code> | RSI: <code>{result['rsi']:.1f}</code>\n"
                f"📊 VolUSD: <code>${result['usd_volume']:,.0f}</code>\n"
                f"⏰ {result['timestamp'].strftime('%Y-%m-%d %H:%M')}"
            )
            print(f"🎯 {msg}")
            send_telegram(msg)
        
        if i % 25 == 0:
            print(f"⏳ Scanned {i}/{len(symbols)} symbols...")
        
        time.sleep(SLEEP_BETWEEN)
    
    # Save results
    if results:
        df = pd.DataFrame(results)
        filename = f"ema_signals_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
        df.to_csv(filename, index=False)
        print(f"\n✅ Scan complete | {len(results)} signals found | Saved to {filename}")
    else:
        print("\n⚠️  No signals found")


if __name__ == "__main__":
    scan()