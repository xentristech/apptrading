import MetaTrader5 as mt5, os, logging
from dotenv import load_dotenv
load_dotenv()

def calc_lot(symbol:str, entry:float, sl:float, risk_pct:float) -> float:
    acc = mt5.account_info()
    if acc is None:            # no connected
        return 0.0
    balance = acc.balance
    risk_amt = balance * risk_pct

    info  = mt5.symbol_info(symbol)
    point = info.point
    stop_pips = abs(entry - sl) / point
    pip_value = info.trade_tick_value / info.trade_tick_size

    volume = risk_amt / (stop_pips * pip_value)
    # redondear a step
    volume = max(info.volume_min,
                 round(volume / info.volume_step) * info.volume_step)
    volume = min(info.volume_max, volume)
    logging.info(f"Lot calc→ balance={balance:.2f} risk={risk_pct*100:.1f}% "
                 f"stop={stop_pips:.1f}p volume={volume}")
    return volume

def should_trail(pos, tp_price:float, start_ratio:float, step_pips:int):
    """Devuelve nuevo SL si debe moverse, si no devuelve None."""
    tick = mt5.symbol_info_tick(pos.symbol)
    price_now = tick.bid if pos.type == mt5.ORDER_TYPE_BUY else tick.ask
    move_start = abs(tp_price - pos.price_open) * start_ratio

    moved = abs(price_now - pos.price_open) >= move_start
    if not moved:
        return None

    direction = 1 if pos.type == mt5.ORDER_TYPE_BUY else -1
    point = mt5.symbol_info(pos.symbol).point
    new_sl = pos.sl + direction * step_pips * point

    # nunca peor que breakeven
    if (direction==1 and new_sl < pos.price_open) or \
       (direction==-1 and new_sl > pos.price_open):
        new_sl = pos.price_open
    return round(new_sl, 5)   # 5 dec para FX
