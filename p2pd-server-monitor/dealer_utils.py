import asyncio
import aiosqlite
from fastapi.responses import JSONResponse
from p2pd import *
from .dealer_defs import *

class PrettyJSONResponse(JSONResponse):
    def render(self, content: any) -> bytes:
        return json.dumps(
            content,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,        # pretty-print here
        ).encode("utf-8")

async def get_last_row_id(db, table_name):
    sql = "SELECT max(id) FROM %s;" % (table_name)

    # Try fetch a row
    async with db.execute(sql) as cursor:
        row = await cursor.fetchone()
        return row[0]

async def delete_all_data(db):
    for table in ("services", "aliases", "status"):
        sql = "DELETE FROM %s;" % (table)
        await db.execute(sql)

async def insert_service(db, service_type, af, proto, ip, port, fb_id=None):
    # Parameterized insert
    sql  = "INSERT INTO services (%s) VALUES " % (", ".join(SERVICE_SCHEMA)) 
    sql += "(?, ?, ?, ?, ?, ?)"
    async with await db.execute(
        sql,
        (service_type, af, proto, ip, port, fb_id,)
    ) as cursor:
        await db.commit()
        return cursor.lastrowid

async def is_unique_service(db, service_type, af, proto, ip, port):
    # Remove these fields -- not relevant for uniqueness check.
    schema = list(SERVICE_SCHEMA[:])
    schema.remove("fallback_id")

    # Parameterized SELECT
    sql  = "SELECT %s FROM services WHERE " % (", ".join(schema))
    sql += " AND ".join(["%s=?" % f for f in schema])

    # Try fetch a row
    async with db.execute(sql, (service_type, af, proto, ip, port)) as cursor:
        rows = await cursor.fetchall()
        return not len(rows)
    
    
# Validation here.
# Don't expose fallback_id directly in public APIs -- grouped service API though.
async def record_service(db, service_type, af, proto, ip, port, fb_id=None):
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
    ret = await insert_service(db, service_type, af, proto, ip, port, fb_id)
    return ret

async def init_status_row(db, service_id=None, alias_id=None):
    schema = list(STATUS_SCHEMA[:])
    if alias_id is not None:
        schema[0] = "alias_id"
        target_id = alias_id
    else:
        target_id = service_id

    # Parameterized insert
    sql  = "INSERT INTO status (%s) VALUES " % (", ".join(schema)) 
    sql += "(?, ?, ?, ?, ?, ?)"
    async with await db.execute(
        sql,
        (target_id, 0, int(time.time()), 0, 0, 0)
    ) as cursor:
        await db.commit()
        return cursor.lastrowid
    
async def load_status_row(db, service_id):
    sql = "SELECT * FROM status WHERE id=?"
    async with db.execute(sql, (service_id,)) as cursor:
        return dict(await cursor.fetchone())
    
async def update_status_dealt(db, status_id, t=None):
    t = t or int(time.time())
    sql = "UPDATE status SET status=?, last_status=? WHERE id=?"
    await db.execute(sql, (STATUS_DEALT, t, status_id,))
    await db.commit()

async def record_alias(db, af, proto, fqn):
    sql = "INSERT into aliases (af, proto, fqn) VALUES (?)"
    async with await db.execute(sql, (af, proto, fqn,)) as cursor:
        await db.commit()
        return cursor.lastrowid

async def insert_test_data(db):
    for groups in TEST_DATA:
        fallback_id = None
        for group in groups:
            try:
                insert_id = await record_service(
                    db=db,
                    service_type=group[1],
                    af=group[2],
                    proto=group[3],
                    ip=group[4],
                    port=group[5],
                    fb_id=fallback_id
                )
                assert(insert_id is not None)

                # Attach a status row.
                status_id = await init_status_row(db, service_id=insert_id)
                assert(status_id is not None)
            except:
                log_exception()
                continue

            # Store alias(es)
            for fqn in group[0]:
                try:
                    alias_id = await record_alias(db, group[2], group[3], fqn)
                    print("alias_id = ", alias_id)
                    if alias_id is not None:
                        await init_status_row(db, alias_id=alias_id)
                except:
                    log_exception()
                    continue

            # Used for making chains of fallback servers.
            fallback_id  = insert_id