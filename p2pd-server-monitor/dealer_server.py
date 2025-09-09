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

wll use pub bind for fastapi and for private calls reject non-local client src.
    add auth later on

todo: dont give out work thats already too recent

max uptime
"""

import asyncio
import aiosqlite
from typing import Union
from fastapi import FastAPI
from p2pd import *
from .dealer_utils import *

app = FastAPI()

@app.get("/work")
async def get_work():
    groups = []
    chain_end = False
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row

        # Try fetch a row
        async with db.execute("SELECT * FROM services ORDER BY id DESC;") as cursor:
            rows = await cursor.fetchall()
            print(rows)

            rows = [dict(row) for row in rows]
            for row in rows:
                # Convert back af and proto.
                row["af"] = IP4 if row["af"] == 2 else IP6
                row["proto"] = UDP if row["proto"] == 2 else TCP
                groups.append(row)

                # Build chain of groups based on fallback servers.
                if row["fallback_id"] is None:
                    chain_end = True


                status_row = await load_status_row(db, row["id"])
                row["status"] = status_row

                # If server hasn't been updated by a worker in over five mins.
                # Assume worker has crashed and allow work to be reallocated.
                elapsed = (int(time.time()) - status_row["last_status"]) 
                if status_row["status"] == STATUS_DEALT:
                    if elapsed >= WORKER_TIMEOUT:
                        status_row["status"] = STATUS_AVAILABLE

                # Skip servers that were checked recently.
                if elapsed < MONITOR_FREQUENCY:
                    continue

                # Specific logic for stun change servers.
                if len(groups) == 4:
                    available = True
                    for group in group:
                        if group["status"]["status"] != STATUS_AVAILABLE:
                            available = False

                    if available:
                        # Make all in group have same status time.
                        t = int(time.time())
                        for group in groups:
                            # Indicate this is allocated as work.
                            await update_status_dealt(db, row["status"]["id"], t=t)
                    else:
                        continue
                else:
                    # Skip work already allocated.
                    if status_row["status"] != STATUS_AVAILABLE:
                        continue

                    # Indicate this is allocated as work.
                    await update_status_dealt(db, status_row["id"])

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
            await db.execute(sql, (status_id, t, SERVER_MAX_DOWNTIME))

        await db.commit()

    return []

#Show a listing of servers based on quality
@app.get("/servers")
async def list_servers():
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