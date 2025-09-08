"""
I'll put notes here.

Have some kind of uptime thing for servers based on
    (failed_no / test_no) * 100
    maybe have the fields wrap around so they dont eventually overflow idk

have that linked list also add a db check that fallback_id < max(id)

i think ill use nat test as the basis but avoid actually touching that code
it works so 

need to reuse pipe or change tests wont reach anywhere bound...

BIG note: the STUN server validation code needs to run on a server without a NAT.

copying change servers to map servers as-is means you could accidentally white list
a change server address by checking a wan ip, thus, only the primary address
should be in the map servers. this means that the current code is wrong.
"""

import asyncio
import aiosqlite
from p2pd import *


DB_NAME = "monitor.sqlite3"

#####################################################################################
SERVICE_SCHEMA = ("type", "af", "proto", "ip", "port", "fallback_id", "last_online")
STUN_MAP_TYPE = 1
STUN_CHANGE_TYPE = 2
MQTT_TYPE = 3
TURN_TYPE = 4
NTP_TYPE = 5

#####################################################################################
# groups .. group(s) ... fields inc list of fqns associated with it (maybe be blank)
# type * af * proto * group_len = ...
TEST_DATA = [


    [
        [
            ["stun.hot-chilli.net"],
            STUN_CHANGE_TYPE, V4, SOCK_DGRAM, "49.12.125.53", 3478
        ],
        [
            ["stun.hot-chilli.net"],
            STUN_CHANGE_TYPE, V4, SOCK_DGRAM, "49.12.125.53", 3479
        ],
        [
            [],
            STUN_CHANGE_TYPE, V4, SOCK_DGRAM, "49.12.125.24", 3478
        ],
        [
            [],
            STUN_CHANGE_TYPE, V4, SOCK_DGRAM, "49.12.125.24", 3479
        ],
    ],

]



async def get_last_row_id(db, table_name):
    sql = "SELECT max(id) FROM %s;" % (table_name)

    # Try fetch a row
    async with db.execute(sql) as cursor:
        row = await cursor.fetchone()
        return row[0]

async def delete_all_data(db):
    for table in ("services", "aliases"):
        sql = "DELETE FROM %s;" % (table)
        await db.execute(sql)

async def insert_service(db, service_type, af, proto, ip, port, fallback_id=None):
    # Parameterized insert
    sql  = "INSERT INTO services (%s) VALUES " % (", ".join(SERVICE_SCHEMA)) 
    sql += "(?, ?, ?, ?, ?, ?, ?)"
    async with await db.execute(
        sql,
        (service_type, af, proto, ip, port, fallback_id, 0)
    ) as cursor:
        return cursor.lastrowid

async def is_unique_service(db, service_type, af, proto, ip, port):
    # Remove these fields -- not relevant for uniqueness check.
    schema = list(SERVICE_SCHEMA[:])
    schema.remove("fallback_id")
    schema.remove("last_online")

    # Parameterized SELECT
    sql  = "SELECT %s FROM services WHERE " % (", ".join(schema))
    sql += " AND ".join(["%s=?" % f for f in schema])

    # Try fetch a row
    async with db.execute(sql, (service_type, af, proto, ip, port)) as cursor:
        rows = await cursor.fetchall()
        return not len(rows)
    
async def validate_stun_server(ip, port, pipe, mode, cip=None, cport=None):
    # New client used for the req.
    stun_client = STUNClient(
        af=pipe.route.af,
        dest=(ip, port),
        nic=pipe.route.interface,
        proto=pipe.proto,
        mode=mode
    )

    print("validate stun server = ", ip, ":", port)

    # Lowever level -- get STUN reply.
    reply = None
    if mode == RFC3489:
        # Reply from different port only.
        if cport is not None and cip is None:
            print("change port", ip, ":", cport)
            reply = await stun_client.get_change_port_reply((ip, cport), pipe)
            

        # Reply from different IP only.
        if cip is not None and cport is not None:
            print("change ip:port", cip, ":", cport)
            reply = await stun_client.get_change_tup_reply((cip, cport), pipe)

        # The NAT test code doesn't need to very just the IP.
        # So that edge case is not checked.
        # if cip is not None and cport is None: etc
        if cip is None and cport is None:
            print("get reug stun reply.")
            reply = await stun_client.get_stun_reply(pipe=pipe)
    else:
        reply = await stun_client.get_stun_reply(pipe=pipe)

    print(reply)
    
    # Validate the reply.
    reply = validate_stun_reply(reply, mode)
    if reply is None:
        raise Exception("Invalid stun reply.")

    # Specific logic to validate RFC3489 change IP/ports.
    # this wont work you actually need to test the change requests work as expected
    # it doesnt even matter if the server returns the wrong cips as long as
    # it replies on the expected ips when the requests are sent
    return reply
    if mode == RFC3489:
        if not hasattr(reply, "ctup"):
            raise Exception("no ctup in reply.")
            
        # Change IP different from reply IP.
        #if IPR(ip, af) == IPR(reply.ctup[0], af):
        #    raise Exception("change IP was the same")
        
        # Validate change IP is as expected.
        if cip is not None:

            if IPR(reply.ctup[0], af) != IPR(cip, af):
                raise Exception("Change IP not as expected.")
        
        # Change port different from reply port.
        #if port == reply.ctup[1]:
        #    raise Exception("change port is same as source port")
        
        # Validate cport is as expected.
        if cport is not None:
            if cport != reply.ctup[1]:
                raise Exception("change port not as expected.")

    # Return all the gathered data.
    return reply

# So with RFC 3489 there's actualoly 4 STUN servers to check:
async def validate_rfc3489_stun_server(af, proto, nic, primary_tup, secondary_tup):
    infos = [
        # Test primary ip, port.
        (primary_tup[0], primary_tup[1], None, None),

        # Test reply from primary ip, change port.
        (primary_tup[0], primary_tup[1], None, primary_tup[2]),

        # Test primary ip, change ip replay.
        # NAT test doesn't need this functionality -- skip for now.
        #(secondary_tup[0], secondary_tup[1], secondary_tup[0], None),

        # Test secondary IP, change port.
        (primary_tup[0], primary_tup[1], secondary_tup[0], secondary_tup[2]),
    ]


    route = nic.route(af)
    pipe = await pipe_open(proto, route=route)


    # Compare IPS in different tups (must be different)
    if IPR(primary_tup[0], af) == IPR(secondary_tup[0], af):
        raise Exception("primary and secondary IPs must differ 3489.")

    # Change port must differ.
    if primary_tup[1] == secondary_tup[2]:
        raise Exception("change port must differ 3489")

    # Test each STUN server.
    for info in infos:
        dest_ip, dest_port, cip, cport = info
        print(info)
        print()

        await validate_stun_server(
            ip=dest_ip,
            port=dest_port,
            pipe=pipe,
            mode=RFC3489,
            cip=cip,
            cport=cport
        )

        print("validate stun server n success")
    
# Validation here.
# Don't expose fallback_id directly in public APIs -- grouped service API though.
async def record_service(db, nic, service_type, af, proto, ip, port, fallback_id=None):
    if not in_range(service_type, [1, 5]):
        raise Exception("Invalid service type for record")
    
    if af not in VALID_AFS:
        raise Exception("invalid af for record service")
    
    if proto not in (TCP, UDP):
        raise Exception("trans proto unsupported for service")
    
    # Check ip is valid -- throw exception if it isn't.
    cidr = 32 if af == IP4 else 128
    IPRange(ip, cidr=cidr)

    # Check port is valid.
    if not valid_port(port):
        raise Exception("remote port for record service invalid.")
    
    # Check uniqueness.
    is_unq = await is_unique_service(db, service_type, af, proto, ip, port)
    if not is_unq:
        raise Exception("service already inserted.")

    """
    Some 'public' STUN servers like to point to private
    addresses. This could be dangerous.
    """
    ipr = IPRange(ip, cidr=af_to_cidr(af))
    if ipr.is_private:
        raise Exception("ip is private for record service")
        
    # Insert the service.
    ret = await insert_service(db, service_type, af, proto, ip, port, fallback_id)
    return ret

async def insert_test_data(db, nic):
    for groups in TEST_DATA:
        fallback_id = None
        for group in groups:
            insert_id = await record_service(
                db=db,
                nic=nic,
                service_type=group[1],
                af=group[2],
                proto=group[3],
                ip=group[4],
                port=group[5],
                fallback_id=fallback_id
            )

            fallback_id  = insert_id

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




async def main():
    print("main")
    print()
    print(int(V4)) # 2
    print(int(V6)) # 10
    print(int(TCP))
    print(int(UDP))
    nic = await Interface()




    params = (1, V4, 1, "127.0.0.1", 80, None)
    async with aiosqlite.connect(DB_NAME) as db:
        await delete_all_data(db)
        await insert_test_data(db, nic)
        #await get_last_row_id(db, "services")
        await worker(db, nic)
        await delete_all_data(db)
        await db.commit()
        return

        await record_service(db, 1, V4, TCP, "127.0.0.1", 80, None)

        
        #ret = await is_unique_service(db, *params[:5])
        #print(ret)


        #await insert_service(db, *params)
        await db.commit()
        print(db)



asyncio.run(main())