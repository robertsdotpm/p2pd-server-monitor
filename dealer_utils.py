import asyncio
import aiosqlite
from p2pd import *
from .dealer_defs import *


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