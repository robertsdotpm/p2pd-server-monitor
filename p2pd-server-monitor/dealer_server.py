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
"""

import asyncio
import aiosqlite
from typing import Union
from fastapi import FastAPI
from p2pd import *
from .dealer_utils import *

app = FastAPI()


async def load_status_row(db, service_id):
    sql = "SELECT * FROM status WHERE id=?"
    async with db.execute(sql, (service_id,)) as cursor:
        return dict(await cursor.fetchone())
    
async def update_status_dealt(db, status_id):
    sql = "UPDATE status SET status=?, last_status=? WHERE id=?"
    await db.execute(sql, (STATUS_DEALT, int(time.time()), status_id,))
    await db.commit()

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

                # If server hasn't been updated by a worker in over five mins.
                # Assume worker has crashed and allow work to be reallocated.
                elapsed = (int(time.time()) - status_row["last_status"]) 
                if status_row["status"] == STATUS_DEALT:
                    if elapsed >= WORKER_TIMEOUT:
                        status_row["status"] = STATUS_AVAILABLE

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