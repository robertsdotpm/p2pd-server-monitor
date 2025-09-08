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

@app.get("/work")
def get_work():
    return {"Hello": "World"}


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
        await delete_all_data(db)
        await db.commit()
        return

        await record_service(db, 1, V4, TCP, "127.0.0.1", 80, None)

        
        #ret = await is_unique_service(db, *params[:5])
        #print(ret)


        #await insert_service(db, *params)
        await db.commit()
        print(db)



#asyncio.run(main())