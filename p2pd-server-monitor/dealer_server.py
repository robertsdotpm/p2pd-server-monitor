"""
I'll put notes here.

BIG note: the STUN server validation code needs to run on a server without a NAT.

copying change servers to map servers as-is means you could accidentally white list
a change server address by checking a wan ip, thus, only the primary address
should be in the map servers. this means that the current code is wrong.

wll use pub bind for fastapi and for private calls reject non-local client src.
    add auth later on


- actually -- lets make resolvers part of the service types to check and have an
API func that updates the IPs they point to -- get resolver stuff working tomorrow.

could give out work based on supported AF stack of a worker.

status now can be for a service or an alias
"""

import asyncio
import aiosqlite
from typing import Union
from fastapi import FastAPI
from p2pd import *
from .dealer_utils import *

app = FastAPI(default_response_class=PrettyJSONResponse)

@app.get("/work")
async def get_work():
    sql = """
    SELECT *
    FROM status
    ORDER BY last_status ASC;
    """
    groups = []
    chain_end = False
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row

        # Try fetch a row
        async with db.execute(sql) as cursor:
            rows = await cursor.fetchall()
            rows = [dict(row) for row in rows]
            for row in rows:
                row["status_id"] = row["id"]

                # Load from alias or services.
                ret = None
                if row["service_id"] is not None:
                    sql = "SELECT * FROM services WHERE id=?"
                    async with db.execute(sql, (row["service_id"],)) as cursor:
                        ret = dict(await cursor.fetchone())
                if row["alias_id"] is not None:
                    sql = "SELECT * FROM alias WHERE id=?"
                    async with  db.execute(sql, (row["alias_id"],)) as cursor:
                        ret = dict(await cursor.fetchone())

                # Combine into row.
                print(ret)
                for k, v in ret.items():
                    if k in row:
                        continue

                    row[k] = v

                print(row)

                # Convert back af and proto.
                groups.append(row)

                # Build chain of groups based on fallback servers.
                if not hasattr(row, "fallback_id") or row["fallback_id"] is None:
                    chain_end = True

                # If server hasn't been updated by a worker in over five mins.
                # Assume worker has crashed and allow work to be reallocated.
                elapsed = (int(time.time()) - row["last_status"]) 
                if row["status"] == STATUS_DEALT:
                    if elapsed >= WORKER_TIMEOUT:
                        row["status"] = STATUS_AVAILABLE

                # Skip servers that were checked recently.
                if elapsed < MONITOR_FREQUENCY:
                    continue

                # Specific logic for stun change servers.
                if len(groups) == 4:
                    available = True
                    for group in group:
                        if group["status"] != STATUS_AVAILABLE:
                            available = False

                    if available:
                        # Make all in group have same status time.
                        t = int(time.time())
                        for group in groups:
                            # Indicate this is allocated as work.
                            await update_status_dealt(db, row["status_id"], t=t)
                    else:
                        continue
                else:
                    # Skip work already allocated.
                    if row["status"] != STATUS_AVAILABLE:
                        continue

                    # Indicate this is allocated as work.
                    await update_status_dealt(db, row["status_id"])

                # Return group info.
                return groups

                print(status_row)

                # Cleanup.
                if chain_end:
                    print("chain end = ", chain_end)
                    groups = []
                    chain_end = False

    return []

# TODO change to post later.
@app.get("/complete")
async def signal_complete_work(is_success: int, status_id: int, t: int):
    """
    For uptime -- keep incrementing uptime field as long as its success.
    However, if last_success time reaches a threshold consider the server offline.
    """
    async with aiosqlite.connect(DB_NAME) as db:
        if is_success:
            # Update uptime.
            sql = """
            UPDATE status
            SET uptime = uptime + (? - last_status)
            WHERE id = ?;
            """
            await db.execute(sql, (t, status_id))

            # Update max_uptime if the new uptime is larger.
            sql = """
            UPDATE status
            SET max_uptime = uptime
            WHERE id = ?
            AND uptime > max_uptime;
            """
            await db.execute(sql, (status_id,))

            # Indicate success: advance test_no with wrap.
            sql = """
            UPDATE status
            SET status = ?,
                last_status = ?,
                last_success = ?,
                test_no = (test_no + 1) % 1000000,
                failed_tests = CASE
                    WHEN (test_no + 1) % 1000000 = 0 THEN 0
                    ELSE failed_tests
                END
            WHERE id = ?;
            """
            await db.execute(sql, (STATUS_AVAILABLE, t, t, status_id,))
        else:
            # Update status.
            sql = """
            UPDATE status
            SET status = ?,
                last_status = ?,
                test_no = (test_no + 1) % 1000000,
                failed_tests = CASE
                    WHEN (test_no + 1) % 1000000 = 0 THEN 0
                    ELSE failed_tests + 1
                END
            WHERE id = ?;
            """
            await db.execute(sql, (STATUS_AVAILABLE, t, status_id))

            # Reset uptime if last_success passes failure threshold.
            sql = """
            UPDATE status
            SET uptime = 0
            WHERE id = ?
            AND (? - last_success) >= ?;
            """
            await db.execute(sql, (status_id, t, MAX_SERVER_DOWNTIME))

        await db.commit()

    return []

#Show a listing of servers based on quality
@app.get("/servers")
async def list_servers():
    sql = """
    SELECT status.*, services.*, 
        (
            -- Reliability
            (1.0 - CAST(status.failed_tests AS REAL) / (status.test_no + 1e-9))
            *
            -- Uptime ratio, fallback to 0.5 if max_uptime is zero
            (0.5 * CASE WHEN status.max_uptime > 0 
                        THEN status.uptime / status.max_uptime 
                        ELSE 1.0
                    END + 0.5)
            *
            -- Confidence factor
            (1.0 - EXP(-CAST(status.test_no AS REAL) / 50.0))
        ) AS quality_score
    FROM status
    JOIN services ON status.service_id = services.id
    WHERE services.type = ? AND services.proto = ? AND services.af = ?
    ORDER BY quality_score DESC;
    """

    # build the server lists and return
    service_types = [STUN_MAP_TYPE, STUN_CHANGE_TYPE, MQTT_TYPE, TURN_TYPE]
    service_types += [NTP_TYPE]

    servers = {}
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        for service_type in service_types:
            servers[service_type] = {
                UDP: {IP4: [], IP6: []},
                TCP: {IP4: [], IP6: []}
            }

            for proto in [UDP, TCP]:
                for af in [IP4, IP6]:
                    params = (service_type, proto, af,)
                    async with db.execute(sql, params) as cursor:
                        rows = await cursor.fetchall()
                        rows = [dict(row) for row in rows]
                        servers[service_type][proto][af] = rows

    return servers

app.post("/alias")
async def update_alias():
    pass

# Just for testing.
@app.get("/freshdb")
async def delete_all_rows():
    async with aiosqlite.connect(DB_NAME) as db:
        await delete_all_data(db)
        await db.commit()

@app.on_event("startup")
async def main():
    print("main")
    print()
    print(int(V4)) # 2
    print(int(V6)) # 10
    print(int(TCP))
    print(int(UDP))

    params = (1, V4, 1, "127.0.0.1", 80, None)
    async with aiosqlite.connect(DB_NAME) as db:
        await delete_all_data(db)
        await insert_test_data(db)
        #await get_last_row_id(db, "services")
        #await delete_all_data(db)
        await db.commit()
        return

        await record_service(db, 1, V4, TCP, "127.0.0.1", 80, None)

        
        #ret = await is_unique_service(db, *params[:5])
        #print(ret)


        #await insert_service(db, *params)
        await db.commit()
        print(db)