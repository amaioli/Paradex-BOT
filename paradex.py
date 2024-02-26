from shared.api_config import ApiConfig
from shared.api_client import get_jwt_token, get_paradex_config, post_order_payload, sign_order, get_markets, delete_all_orders_payload, delete_order_payload, get_market_summary
from shared.paradex_api_utils import Order, OrderSide, OrderType
import asyncio, json, websockets
from decimal import Decimal
from utils import (
    generate_paradex_account,
    get_account,
    get_l1_eth_account,
    sign_stark_key_message,
)
from cachetools import cached, TTLCache
from cache import AsyncTTL


class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return str(obj)
        return json.JSONEncoder.default(self, obj)

class Paradex:
    def __init__(self, config, paradex_config, api_server):
        self.api_config = ApiConfig()
        self.api_config.paradex_http_url = api_server
        self.api_config.ws_http_url ="wss://ws.api.testnet.paradex.trade/v1" if config["config"]["env"] == "testnet" else "wss://ws.api.prod.paradex.trade/v1"
        self.api_config.ethereum_private_key = config["config"]["eth_priv_key"]
        _, self.eth_account = get_l1_eth_account(self.api_config.ethereum_private_key)
        self.api_config.paradex_config = paradex_config
        self.gen_paradex_account()

    @cached(cache=TTLCache(maxsize=20, ttl=60*60*24))
    def gen_paradex_account(self):
        self.api_config.paradex_account, self.api_config.paradex_account_private_key = generate_paradex_account(
            self.api_config.paradex_config, self.eth_account.key.hex())

    #@cached(cache=TTLCache(maxsize=20, ttl=60*4))
    @AsyncTTL(time_to_live=60*4, maxsize=128)
    async def jwt(self):
        self.gen_paradex_account()
        return await get_jwt_token(
            self.api_config.paradex_config,
            self.api_config.paradex_http_url,
            self.api_config.paradex_account,
            self.api_config.paradex_account_private_key,
    )

    async def post_order(self, order_type: OrderType, order_side: OrderSide, limit_price:Decimal, size: Decimal, market: str, client_id: str) -> Order:

        order = Order(
            market=market,
            order_type=order_type,
            order_side=order_side,
            limit_price=limit_price,
            size=size,
            client_id=client_id,
        )
        print(order.dump_to_dict())

        sig = sign_order(self.api_config, order)
        order.signature = sig

        # POST order
        #order = build_order(config, OrderType.Market, OrderSide.Buy, Decimal("0.1"), "ETH-USD-PERP", "mock")
        jwt = await self.jwt()
        ret = await post_order_payload(self.api_config.paradex_http_url, jwt, order.dump_to_dict())
        try:
            a = ret['id']
            return a
        except Exception as error:
        #         # handle the exception
            print(ret)
            print("An exception occurred in post order:", error) # An exception occurred: division by zero

    async def delete_all_orders(self, pair):
        jwt = await self.jwt()
        return await delete_all_orders_payload(self.api_config.paradex_http_url, jwt, pair)

    async def delete_order(self, order_id: str):
        jwt = await self.jwt()
        return await delete_order_payload(self.api_config.paradex_http_url, jwt, order_id)

    async def get_price(self, pair: str):
        ret = await get_market_summary(
            paradex_http_url=self.api_config.paradex_http_url, 
            pair=pair)
        return float(ret[0]['mark_price'])

    async def get_market(self, pair: str):
        ret = await get_markets(
            paradex_http_url=self.api_config.paradex_http_url, 
            pair=None)
        return ret
 



    async def subscribe_channel(self, func, channel: str):

        auth = {
            "jsonrpc": "2.0",
            "method": "auth",
            "params": {
                "bearer": await self.jwt()
        },
            "id": 0
        }
        message = {
            "jsonrpc": "2.0",
            "method": "subscribe",
            "params": {
                "channel": channel
        },
            "id": 1
        }

        my_websocket = None
        self.is_connected_ws = False

        async for websocket in websockets.connect(self.api_config.paradex_ws_url):
            try:
                my_websocket = websocket
                await my_websocket.send(json.dumps(auth))
                await my_websocket.send(json.dumps(message))
                self.is_connected_ws = True
                async for message in websocket:
                    message_json = json.loads(message)
                    await func(message_json)
            except websockets.ConnectionClosed:
                my_websocket = None
                self.is_connected_ws = False

