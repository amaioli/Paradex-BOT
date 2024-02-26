from paradex import Paradex
import yaml
import asyncio
import logging
import os
from decimal import Decimal
from shared.api_client import get_jwt_token, get_paradex_config
from shared.paradex_api_utils import Order, OrderSide, OrderType

with open('config.yaml', 'r') as file:
        config = yaml.safe_load(file)



async def main(loop):

        api_server ="https://api.testnet.paradex.trade/v1" if config["config"]["env"] == "testnet" else "https://api.prod.paradex.trade/v1"
        paradex_config = await get_paradex_config("https://api.testnet.paradex.trade/v1")
        global paradex
        paradex = Paradex(config, paradex_config, api_server)

        markets = await paradex.get_market(None)
        for i in markets:
                try:
                        config["coins"][i['symbol']]['price_precision']=len(i["price_tick_size"].split(".")[1])
                        config["coins"][i['symbol']]['size_precision']=len(i["order_size_increment"].split(".")[1])
                except:
                        pass
        for i in config["coins"]:
                config["coins"][i]["tp_order"] = ""
                config["coins"][i]["positions"] = 0
                await paradex.delete_all_orders(i)

        await paradex.subscribe_channel(func=strategy, channel="positions")


async def strategy(msg):
        #try:
        if "params" in msg and msg["params"]["data"]["market"] in config["coins"]:
                side = msg["params"]["data"]["side"]
                pair = msg["params"]["data"]["market"]
                price = await paradex.get_price(pair)
                positions = float(msg["params"]["data"]["size"])
                if float(msg["params"]["data"]["size"]) == 0:
                        logging.info(f"take TP {pair}")
                        # ol orders cancellation
                        await paradex.delete_all_orders(pair) #gestire market
                        # construct the grid
                        
                        first_grid_step = config["coins"][pair]["first_grid_step"]
                        p_1 = price * (1 - first_grid_step/100) if config["coins"][pair]["side"] == "LONG" else price * (1 + first_grid_step/100)
                        p_2 = price
                        s_1 = config["coins"][pair]["size"]

                        order_side = OrderSide.Buy if config["coins"][pair]["side"] == "LONG" else OrderSide.Sell

                        config["coins"][pair]["positions"] = 0

                        # create market order
                        await paradex.post_order(
                                order_type=OrderType.Market,
                                order_side=order_side,
                                limit_price=None,
                                size=Decimal(str(round(s_1,config["coins"][pair]['size_precision']))),
                                market=pair,
                                client_id=""
                        )


                        #create first grid order
                        await paradex.post_order(
                                order_type=OrderType.Limit,
                                order_side=order_side,
                                limit_price=Decimal(str(round(p_1,config["coins"][pair]['price_precision']))),
                                size=Decimal(str(round(s_1,config["coins"][pair]['size_precision']))),
                                market=pair,
                                client_id=""
                        )


                        for n in range(1, config["coins"][pair]["grids"]):
                                # create grid orders
                                p_n = p_1 - (p_2 - p_1) * config["coins"][pair]["grid_step"] if config["coins"][pair]["side"] == "LONG" else p_1 + (p_1 - p_2) * config["coins"][pair]["grid_step"]
                                #price = round(p_n, config["coins"][pair]["price_precision"])
                                s_n = s_1 * (config["coins"][pair]["order_step"])
                                await paradex.post_order(
                                        order_type=OrderType.Limit,
                                        order_side=order_side,
                                        limit_price=Decimal(str(round(p_n,config["coins"][pair]['price_precision']))),
                                        size=Decimal(str(round(s_n,config["coins"][pair]['size_precision']))),
                                        market=pair,
                                        client_id=""
                                )
                                p_2 = p_1
                                p_1 = p_n
                                s_1 = s_n

                # gestione Posizione
                else:
                        if positions > config["coins"][pair]["positions"]:
                                logging.info(f'Filled grid order {pair}')
                                #rebuid the TP
                                if config["coins"][pair]["tp_order"]:
                                        await paradex.delete_order(config["coins"][pair]["tp_order"]) # cancelliamo il vecchio TP
                                if side == "LONG":
                                        order_side = OrderSide.Sell
                                        limit_price = price * (1 + config["coins"][pair]["take_step"])
                                else:
                                        order_side = OrderSide.Buy
                                        limit_price = price * (1 - config["coins"][pair]["take_step"])

                                config["coins"][pair]["tp_order"] = await paradex.post_order(
                                        order_type=OrderType.Limit,
                                        order_side=order_side,
                                        limit_price=Decimal(str(round(limit_price,config["coins"][pair]['price_precision']))),
                                        size=Decimal(str(round(positions, config["coins"][pair]['size_precision']))),
                                        market=pair,
                                        client_id=""    
                                )

                        config["coins"][pair]["positions"] = positions

        # except Exception as error:
        #         # handle the exception
        #         print("An exception occurred:", error) # An exception occurred: division by zero

        
        
logging.basicConfig(
        level=os.getenv("LOGGING_LEVEL", "INFO"),
        format="%(asctime)s.%(msecs)03d | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
loop = asyncio.get_event_loop()
loop.run_until_complete(main(loop))