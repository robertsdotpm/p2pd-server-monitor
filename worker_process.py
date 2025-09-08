import asyncio
import aiosqlite
from p2pd import *
from .dealer_defs import *
from .worker_utils import *

async def worker(db, nic):
    # Try fetch a row
    async with db.execute("SELECT * FROM services ORDER BY id DESC;") as cursor:
        rows = await cursor.fetchall()
        
        chain_end = False
        groups = []
        for row in rows:
            row_id = row[0]
            service_type = row[1]
            af = row[2]
            proto = row[3]
            ip = row[4]
            port = row[5]
            fallback_id = row[6]
            last_online = row[7]



            # Convert back af and proto.
            af = IP4 if af == 2 else IP6
            proto = UDP if proto == 2 else TCP


            # Skip unsupported AFs for now.
            if af not in nic.supported():
                print(af, " not supported")
                continue

            groups.append(row)

            print("fallback id ", fallback_id)

            # Build chain of groups based on fallback servers.
            if fallback_id is None:
                chain_end = True

            # Processing here.

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

            # Cleanup.
            if chain_end:
                print("chain end = ", chain_end)
                groups = []
                chain_end = False