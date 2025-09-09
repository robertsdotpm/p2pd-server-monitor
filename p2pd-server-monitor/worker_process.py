import asyncio
import aiosqlite
from p2pd import *
from .dealer_defs import *
from .worker_utils import *

async def worker(nic, groups):
    single_group = len(groups) == 1
    status_ids = []
    af = IP4 if groups[0]["af"] == 2 else IP6
    proto = UDP if groups[0]["proto"] == 2 else TCP
    is_success = 1
    if groups[0]["type"] == STUN_MAP_TYPE and single_group:
        """
        print("in map type")
        print(ip, port)
        print(af)
        print(proto)
        """
        try:
            dest = (groups[0]["ip"], groups[0]["port"],)
            client = STUNClient(af, dest, nic, proto=proto, mode=RFC5389)
            out = await client.get_wan_ip()
            print(out)
            status_ids.append(groups[0]["status"]["id"])
        except:
            what_exception()
            is_success = 0
            pass

    """
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
    """

    return is_success, status_ids

async def worker_loop():
    nic = await Interface()
    endpoint = ("127.0.0.1", 8000,)
    route = nic.route(IP4)
    curl = WebCurl(endpoint, route)
    while 1:
        print("Fetching work... ")

        # Processing here.
        resp = await curl.vars().get("/work")
        groups = json.loads(to_s(resp.out))
        print(groups)

        # Carry out the work.
        is_success, status_ids = await worker(nic, groups)
        print("is success = ", is_success)
        print("status ids = ", status_ids)

        # Indicate the status outcome.
        for status_id in status_ids:
            # Indicate work complete.
            params = {"is_success": is_success, "status_id": status_id}
            await curl.vars(params).get("/complete")

        #await curl.vars().get("/freshdb")

        time.sleep(10)
        return



asyncio.run(worker_loop())