import time, logging, os
from datetime import datetime
from utils          import (TZ, TIMEFRAMES, limpiar, get_indicadores_tf,
                            obtener_cierres, generar_prompt, analizar_con_ollama,
                            enviar_telegram, guardar_senal_csv)
from bridge_mt5     import MT5Bridge
from signal_parser  import parse_signal
from risk           import calc_lot, should_trail
from dotenv         import load_dotenv
import pytz, MetaTrader5 as mt5

load_dotenv()
RISK_PCT   = float(os.getenv("RISK_PER_TRADE", 0.01))
TR_START   = float(os.getenv("TRAIL_START", 0.5))
TR_STEP    = int(os.getenv("TRAIL_STEP_PIPS", 100))
SYMBOL     = os.getenv("SYMBOL", "BTC/USD")

def debe_consultar(tf:str, dt:datetime) -> bool:
    m = dt.minute
    return (tf=="5min"  and m%5==0) or \
           (tf=="15min" and m%15==0) or \
           (tf=="30min" and m%30==0) or \
           (tf=="1h")

def main():
    # ── MT5 ────────────────────────────────────────────────
    mt5b = MT5Bridge()
    if not mt5b.connect():
        raise SystemExit("❌ No se pudo conectar a MT5")

    datos_guardados = {tf:{} for tf in TIMEFRAMES}
    cierres_guardados = {tf:[] for tf in TIMEFRAMES}
    datetime_guardados = {tf:None for tf in TIMEFRAMES}

    open_positions = {}   # ticket → TradeSignal

    while True:
        now = datetime.now(TZ)
        logging.info(f"Cycle {now.strftime('%Y-%m-%d %H:%M:%S')}")

        # 1. Actualizar datos/indicadores
        for tf in TIMEFRAMES:
            if debe_consultar(tf, now) or datos_guardados[tf]=={}:
                nuevos = limpiar(get_indicadores_tf(tf))
                datos_guardados[tf] = nuevos
                cierres_guardados[tf] = obtener_cierres(tf, 30)
                datetime_guardados[tf] = nuevos.get("precio_datetime") or nuevos.get("datetime")
                logging.debug(f"Actualizado {tf}")

        # 2. IA
        prompt = generar_prompt(datos_guardados, cierres_guardados)
        respuesta = analizar_con_ollama(prompt)
        logging.info("IA answered")
        print(respuesta)      # para consola

        # 3. Telegram + CSV
        enviar_telegram("🚨 Señal BTCUSD\n\n"+respuesta)
        guardar_senal_csv(respuesta, now)

        # 4. Parsear y, si procede, enviar orden
        sig = parse_signal(respuesta)
        if sig:
            lot = calc_lot(SYMBOL.replace("/",""), sig.entry, sig.sl, RISK_PCT)
            if lot>0:
                ticket = mt5b.send_market_order(SYMBOL.replace("/",""), lot, sig.side, sig.sl, sig.tp)
                if ticket:
                    open_positions[ticket] = sig

        # 5. Trailing stop
        for ticket, sig in list(open_positions.items()):
            pos = mt5.positions_get(ticket=ticket)
            if not pos:                     # cerrada
                open_positions.pop(ticket)
                continue
            pos = pos[0]
            new_sl = should_trail(pos, sig.tp, TR_START, TR_STEP)
            if new_sl and abs(new_sl - pos.sl) > pos.price_tick:
                if mt5b.modify_position(ticket, new_sl=new_sl):
                    logging.info(f"SL movido a {new_sl} (ticket {ticket})")

        # 6. Esperar
        time.sleep(60)

if __name__ == "__main__":
    main()
