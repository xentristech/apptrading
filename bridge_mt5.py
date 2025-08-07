import MetaTrader5 as mt5, os, logging
from dotenv import load_dotenv
load_dotenv()

class MT5Bridge:
    def __init__(self):
        self.path     = os.getenv("MT5_PATH")
        self.login    = int(os.getenv("MT5_LOGIN"))
        self.password = os.getenv("MT5_PASSWORD")
        self.server   = os.getenv("MT5_SERVER")
        self.portable = int(os.getenv("MT5_PORTABLE", 0))
        self.connected = False

    # ── conexión ────────────────────────────────────────────
    def connect(self) -> bool:
        mt5.initialize(path=self.path, portable=self.portable)
        ok = mt5.login(self.login, self.password, self.server)
        self.connected = ok
        if not ok:
            logging.error(f"MT5 login failed {mt5.last_error()}")
        return ok

    # ── orden de mercado ────────────────────────────────────
    def send_market_order(self, symbol:str, volume:float, side:str,
                          sl:float, tp:float, magic:int=777, comment:str="IA bot"):
        if not self.connected:
            raise RuntimeError("MT5 no conectado")

        info = mt5.symbol_info(symbol)
        if not info.visible:
            mt5.symbol_select(symbol, True)

        tick = mt5.symbol_info_tick(symbol)
        price = tick.ask if side == "BUY" else tick.bid

        request = {
            "action"      : mt5.TRADE_ACTION_DEAL,
            "symbol"      : symbol,
            "volume"      : volume,
            "type"        : mt5.ORDER_TYPE_BUY if side=="BUY" else mt5.ORDER_TYPE_SELL,
            "price"       : price,
            "sl"          : sl,
            "tp"          : tp,
            "deviation"   : 50,
            "magic"       : magic,
            "comment"     : comment,
            "type_time"   : mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            logging.error(f"order_send falló {result.retcode} {result.comment}")
            return None
        logging.info(f"Orden ticket={result.order} abierta @ {result.price}")
        return result.order

    # ── modificar SL / TP ───────────────────────────────────
    def modify_position(self, ticket:int, new_sl:float=None, new_tp:float=None) -> bool:
        pos = mt5.positions_get(ticket=ticket)
        if not pos:
            return False
        pos = pos[0]
        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": ticket,
            "sl": new_sl if new_sl else pos.sl,
            "tp": new_tp if new_tp else pos.tp,
            "symbol": pos.symbol,
            "comment": "update",
        }
        r = mt5.order_send(request)
        return r.retcode == mt5.TRADE_RETCODE_DONE
