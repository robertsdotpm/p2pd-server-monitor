import asyncio
import aiosqlite
from p2pd import *
from .dealer_defs import *
from .worker_utils import *

async def worker():
    nic = await Interface()
    endpoint = ("127.0.0.1", 8000,)
    route = nic.route(IP4)
    curl = WebCurl(endpoint, route)
    while 1:
        # Processing here.
        resp = await curl.vars().get("/work")
        print(resp.out)

        # Do work on rsp.
        ####

        is_success = 1

        # Indicate work complete.
        params = {"is_success": is_success, "status_id": 0}
        # await curl.vars(params).get("/complete")

        await curl.vars().get("/freshdb")

        time.sleep(10000)
        return

        if service_type == STUN_MAP_TYPE:
            """
            print("in map type")
            print(ip, port)
            print(af)
            print(proto)
            try:
                client = STUNClient(af, (ip, port), nic, proto=proto, mode=RFC5389)
                out = await client.get_wan_ip()
                print(out)
            except:
                what_exception()
                pass
            """
            pass

        if service_type == STUN_CHANGE_TYPE and len(groups) == 4:
            print("stun inside change type")

            # Validates the relationship between 4 stun servers.
            groups = list(reversed(groups))
            print(groups)
            print()
            await validate_rfc3489_stun_server(
                af,
                proto,
                nic,

                # IP, main port, secondary port
                (groups[0][4], groups[0][5], groups[1][5]),
                (groups[2][4], groups[2][5], groups[3][5]),
            )

            print("change servers validated")

asyncio.run(worker())