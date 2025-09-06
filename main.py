"""
I'll put notes here.

Have some kind of uptime thing for servers based on
    (failed_no / test_no) * 100
    maybe have the fields wrap around so they dont eventually overflow idk

have that linked list also add a db check that fallback_id < max(id)
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
            ["stun.l.google.com"],
            STUN_MAP_TYPE, V4, SOCK_DGRAM, "74.125.250.129", 19302
        ]
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
    
async def validate_stun_server(af, host, port, proto, interface, mode, timeout, recurse=True):
    # Attempt to resolve STUN server address.
    dest = await Address(host, port, interface)
    dest = dest.select_ip(af)
    
    """
    Some 'public' STUN servers like to point to private
    addresses. This could be dangerous.
    """
    ipr = IPRange(dest.tup[0], cidr=af_to_cidr(af))
    if ipr.is_private:
        log(f"{af} {host} {recurse} is private")
        return None

    # New pipe used for the req.
    stun_client = STUNClient(
        af=af,
        dest=dest.tup,
        nic=interface,
        proto=proto,
        mode=mode
    )

    try:
        reply = await stun_client.get_stun_reply()
    except:
        log_exception()
        log(f"{af} {host} {proto} {mode} get reply {recurse} none")
        return None
    
    reply = validate_stun_reply(reply, mode)
    if reply is None:
        return
    # Cleanup.
    if hasattr(reply, "pipe"):
        await reply.pipe.close()  

    # Validate change server reply.
    ctup = (None, None)
    if mode == RFC3489:
        if recurse and hasattr(reply, "ctup"):
            try:
                # Change IP different from reply IP.
                if reply.stup[0] == reply.ctup[0]:
                    log(f'ctup bad {to_h(reply.txn_id)}: bad {reply.ctup[0]} 1')
                    return None
                
                # Change port different from reply port.
                if reply.stup[1] == reply.ctup[1]:
                    log(f'ctup bad {to_h(reply.txn_id)}: bad {reply.ctup[0]} 2')
                    return None


                creply = await validate_stun_server(
                    af,
                    reply.ctup[0],
                    reply.ctup[1],
                    proto,

                    interface,
                    mode,
                    timeout,
                    recurse=False # Avoid infinite loop.
                )
            except:
                log(f"vaid stun recurse failed {af} {host}")
                log_exception()
            if creply is not None:
                ctup = reply.ctup
            else:
                log(f"{af} {host} {reply.ctup} ctup get reply {recurse} none")

    # Return all the gathered data.
    return [
        af,
        host,
        dest.tup[0],
        dest.tup[1], 
        ctup[0],
        ctup[1],
        proto,
        mode
    ]
    
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
    
    # For stun validate the server type.
    if service_type in (STUN_CHANGE_TYPE, STUN_MAP_TYPE):
        try:
            out = await validate_stun_server(
                af,
                ip,
                port,
                proto,
                nic,
                RFC5389 if service_type == STUN_MAP_TYPE else RFC3489,
                8
            )
            print(out)
        except:
            what_exception()
            pass

    
    # Insert the service.
    ret = await insert_service(db, service_type, af, proto, ip, port, fallback_id)
    return ret

async def insert_test_data(db, nic):
    for groups in TEST_DATA:
        fallback_id = None
        print(groups)
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

            chain_end = False
            groups.append(row)

            # Build chain of groups based on fallback servers.
            if fallback_id is None:
                chain_end = True

            # Processing here.

            if service_type == STUN_MAP_TYPE:
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

            if service_type == STUN_CHANGE_TYPE:
                # Needs at least primary and secondary server IPs.
                if len(groups) != 2:
                    groups = []
                    continue



            # Cleanup.
            if chain_end:
                groups = []




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

        await db.commit()
        return

        await record_service(db, 1, V4, TCP, "127.0.0.1", 80, None)

        
        #ret = await is_unique_service(db, *params[:5])
        #print(ret)


        #await insert_service(db, *params)
        await db.commit()
        print(db)



asyncio.run(main())