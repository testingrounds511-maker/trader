"""Trade executor via MetaTrader 5 API."""

import logging
from datetime import datetime, timezone

import MetaTrader5 as mt5

from config import config, FN_RULES

logger = logging.getLogger("phantom.executor")

# Magic number to identify our bot's trades
PHANTOM_MAGIC = 777333


class Executor:
    """Executes trades on MT5. Supports auto and manual modes."""

    def place_trade(
        self,
        symbol: str,
        direction: str,  # "BUY" or "SELL"
        lot_size: float,
        sl_price: float,
        tp_price: float,
        comment: str = "Phantom v3",
    ) -> dict:
        """Place a market order on MT5.

        Returns: {"success": bool, "ticket": int, "error": str}
        """
        if config.manual_mode:
            return {
                "success": False,
                "mode": "MANUAL",
                "signal": {
                    "symbol": symbol,
                    "direction": direction,
                    "lot_size": lot_size,
                    "sl": sl_price,
                    "tp": tp_price,
                    "comment": comment,
                },
                "message": "Manual mode: signal generated, execute in MT5 manually",
            }

        try:
            # Get symbol info
            symbol_info = mt5.symbol_info(symbol)
            if symbol_info is None:
                return {"success": False, "error": f"Symbol {symbol} not found"}

            if not symbol_info.visible:
                if not mt5.symbol_select(symbol, True):
                    return {"success": False, "error": f"Failed to select {symbol}"}

            # Get current price
            tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                return {"success": False, "error": f"No tick data for {symbol}"}

            # Determine order type and price
            if direction == "BUY":
                order_type = mt5.ORDER_TYPE_BUY
                price = tick.ask
            else:
                order_type = mt5.ORDER_TYPE_SELL
                price = tick.bid

            # Validate lot size
            lot_size = max(symbol_info.volume_min, lot_size)
            lot_size = min(symbol_info.volume_max, lot_size)
            # Round to volume step
            step = symbol_info.volume_step
            lot_size = round(round(lot_size / step) * step, 2)

            # Build order request
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": lot_size,
                "type": order_type,
                "price": price,
                "sl": round(sl_price, symbol_info.digits),
                "tp": round(tp_price, symbol_info.digits),
                "deviation": 20,  # Max slippage in points
                "magic": PHANTOM_MAGIC,
                "comment": comment,
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }

            # Send order
            result = mt5.order_send(request)
            if result is None:
                return {"success": False, "error": f"Order send failed: {mt5.last_error()}"}

            if result.retcode != mt5.TRADE_RETCODE_DONE:
                return {
                    "success": False,
                    "error": f"Order rejected: {result.retcode} — {result.comment}",
                }

            logger.info(
                f"✅ {direction} {lot_size} {symbol} @ {price} "
                f"SL={sl_price} TP={tp_price} | Ticket: {result.order}"
            )

            return {
                "success": True,
                "ticket": result.order,
                "price": price,
                "volume": lot_size,
                "direction": direction,
                "symbol": symbol,
                "sl": sl_price,
                "tp": tp_price,
            }

        except Exception as e:
            logger.error(f"Execution error: {e}")
            return {"success": False, "error": str(e)}

    def close_position(self, ticket: int) -> dict:
        """Close a specific position by ticket."""
        if config.manual_mode:
            return {
                "success": False,
                "mode": "MANUAL",
                "message": f"Manual mode: close ticket {ticket} in MT5",
            }

        try:
            position = mt5.positions_get(ticket=ticket)
            if not position:
                return {"success": False, "error": f"Position {ticket} not found"}

            pos = position[0]
            symbol = pos.symbol
            volume = pos.volume

            # Close with opposite order
            tick = mt5.symbol_info_tick(symbol)
            if pos.type == 0:  # BUY position -> SELL to close
                order_type = mt5.ORDER_TYPE_SELL
                price = tick.bid
            else:  # SELL position -> BUY to close
                order_type = mt5.ORDER_TYPE_BUY
                price = tick.ask

            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": volume,
                "type": order_type,
                "position": ticket,
                "price": price,
                "deviation": 20,
                "magic": PHANTOM_MAGIC,
                "comment": "Phantom v3 close",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }

            result = mt5.order_send(request)
            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                logger.info(f"✅ Closed position {ticket}")
                return {"success": True, "ticket": ticket}
            else:
                err = result.comment if result else mt5.last_error()
                return {"success": False, "error": f"Close failed: {err}"}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def close_all_positions(self) -> list[dict]:
        """Emergency close all open positions."""
        results = []
        positions = mt5.positions_get()
        if not positions:
            return results

        for pos in positions:
            if pos.magic == PHANTOM_MAGIC or not config.manual_mode:
                result = self.close_position(pos.ticket)
                results.append(result)

        return results

    def modify_position(self, ticket: int, sl: float = None, tp: float = None) -> dict:
        """Modify SL/TP of an open position."""
        try:
            position = mt5.positions_get(ticket=ticket)
            if not position:
                return {"success": False, "error": f"Position {ticket} not found"}

            pos = position[0]
            symbol_info = mt5.symbol_info(pos.symbol)

            request = {
                "action": mt5.TRADE_ACTION_SLTP,
                "symbol": pos.symbol,
                "position": ticket,
                "sl": round(sl or pos.sl, symbol_info.digits),
                "tp": round(tp or pos.tp, symbol_info.digits),
            }

            result = mt5.order_send(request)
            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                return {"success": True}
            else:
                return {"success": False, "error": f"Modify failed: {result.comment if result else 'unknown'}"}

        except Exception as e:
            return {"success": False, "error": str(e)}
