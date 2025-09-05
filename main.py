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
    
# Validation here.
async def record_service(db, service_type, af, proto, ip, port, fallback_id=None):
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
    
    # Insert the service.
    ret = await insert_service(db, service_type, af, proto, ip, port, fallback_id)
    print(ret)

async def main():
    print("main")
    print()
    print(int(V4)) # 2
    print(int(V6)) # 10


    params = (1, V4, 1, "127.0.0.1", 80, None)
    async with aiosqlite.connect(DB_NAME) as db:

        await record_service(db, 1, V4, TCP, "127.0.0.1", 80, None)

        
        #ret = await is_unique_service(db, *params[:5])
        #print(ret)


        #await insert_service(db, *params)
        await db.commit()
        print(db)



asyncio.run(main())