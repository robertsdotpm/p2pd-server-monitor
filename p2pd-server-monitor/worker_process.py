import asyncio
import aiosqlite
from p2pd import *
from .dealer_defs import *
from .worker_utils import *

async def service_worker(nic, groups):
    single_group = len(groups) == 1
    status_ids = []
    af = IP4 if groups[0]["af"] == 2 else IP6
    proto = UDP if groups[0]["proto"] == 2 else TCP
    is_success = 1
    if groups[0]["type"] == STUN_MAP_TYPE and single_group:
        try:
            dest = (groups[0]["ip"], groups[0]["port"],)
            client = STUNClient(af, dest, nic, proto=proto, mode=RFC5389)
            out = await client.get_wan_ip()
            print(out)
            status_ids.append(groups[0]["status_id"])
        except:
            what_exception()
            is_success = 0
            pass

    if groups[0]["type"] == STUN_CHANGE_TYPE and len(groups) == 4:
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
            (groups[0]["ip"], groups[0]["port"], groups[1]["port"],),
            (groups[2]["ip"], groups[2]["port"], groups[3]["port"],),
        )

        for group in groups:
            status_ids.append(group["status_id"])

        print("change servers validated")
    
    return is_success, status_ids

async def alias_worker(nic, groups):
    addr = await Address(groups[0]["fqn"], 80, nic)
    return addr.select_ip(groups[0]["af"]).ip

async def worker_loop():
    nic = await Interface()
    endpoint = ("127.0.0.1", 8000,)
    route = nic.route(IP4)
    curl = WebCurl(endpoint, route)
    while 1:
        print("Fetching work... ")

        # Fetch work from dealer server.
        resp = await curl.vars({"stack_type": int(nic.stack)}).get("/work")
        if resp.info is None:
            await asyncio.sleep(5)
            continue
        else:
            groups = json.loads(to_s(resp.out))

        # If there's no work -- sleep and continue.
        if not len(groups):
            print("no work ready ... sleeping.")
            await asyncio.sleep(5)
            continue

        is_success = False
        status_ids = []
        if groups[0]["service_id"] is not None:
            # Carry out the work.
            try:
                is_success, status_ids = await service_worker(nic, groups)
            except:
                print("Worker process exception.")
                log_exception()
                await asyncio.sleep(5)
                continue
        else:
            ip = await alias_worker(nic, groups)
            print("ip = ", ip)
            if ip is not None:
                is_success = True
                status_ids = [groups[0]["status_id"]]
                params = {"alias_id": groups[0]["alias_id"], "ip": ip}
                await curl.vars(params).get("/alias")



        print("is success = ", is_success)
        print("status ids = ", status_ids)

        # Indicate the status outcome.
        t = int(time.time())
        for status_id in status_ids:
            # Indicate work complete.
            params = {"is_success": is_success, "status_id": status_id, "t": t}
            await curl.vars(params).get("/complete")

        #await curl.vars().get("/freshdb")

asyncio.run(worker_loop())