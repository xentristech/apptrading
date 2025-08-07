import re
from typing import Optional, NamedTuple

class TradeSignal(NamedTuple):
    side  : str
    entry : float
    sl    : float
    tp    : float
    ratio : float

def parse_signal(text:str) -> Optional[TradeSignal]:
    if "Señal final" not in text:
        return None
    side   = "BUY" if "COMPRA" in text.upper() else "SELL" if "VENTA" in text.upper() else ""
    try:
        entry = float(re.search(r"Entrada[:= ]+([\d\.]+)", text).group(1))
        sl    = float(re.search(r"SL[:= ]+([\d\.]+)",      text).group(1))
        tp    = float(re.search(r"TP[:= ]+([\d\.]+)",      text).group(1))
        ratio = float(re.search(r"Ratio TP/SL[:= ]+([\d\.]+)", text).group(1))
    except Exception:
        return None
    return TradeSignal(side, entry, sl, tp, ratio)
