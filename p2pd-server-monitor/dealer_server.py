"""
I'll put notes here.

BIG note: the STUN server validation code needs to run on a server without a NAT.

copying change servers to map servers as-is means you could accidentally white list
a change server address by checking a wan ip, thus, only the primary address
should be in the map servers. this means that the current code is wrong.

wll use pub bind for fastapi and for private calls reject non-local client src.
    add auth later on7

norm ip vals
exp backoff based on service downtime
"""

import asyncio
import aiosqlite
from typing import Union
from fastapi import FastAPI
import json
import math
from p2pd import *
from .dealer_utils import *

app = FastAPI(default_response_class=PrettyJSONResponse)

@app.get("/work")
async def get_work(stack_type: int = DUEL_STACK):
    if stack_type == DUEL_STACK:
        need_af = "af"
    else:
        need_af = stack_type if stack_type in VALID_AFS else "af"

    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row

        # Step 1: fetch all status rows, oldest first
        sql_status = """
        SELECT *
        FROM status
        ORDER BY last_status ASC
        """
        async with db.execute(sql_status) as cursor:
            status_entries = [dict(r) for r in await cursor.fetchall()]

        current_time = int(time.time())

        for status_entry in status_entries:
            status_entry["status_id"] = status_entry["id"]

            group_records = []

            # Step 2a: if this status row points to a service, load the whole service group + status
            if status_entry["service_id"] is not None:
                sql_service_group = """
                SELECT services.*, status.id AS status_id, status.status,
                        status.last_status, status.failed_tests, status.test_no,
                        status.max_uptime, status.uptime, status.last_success
                FROM services
                LEFT JOIN status ON status.service_id = services.id
                WHERE services.group_id = (
                    SELECT group_id
                    FROM services
                    WHERE id=? AND af=?
                    LIMIT 1
                )
                AND services.af=?
                """
                async with db.execute(sql_service_group, (status_entry["service_id"], need_af, need_af)) as cursor:
                    group_records = [dict(r) for r in await cursor.fetchall()]

            # Step 2b: if this status row points to an alias, load the alias + status
            elif status_entry["alias_id"] is not None:
                sql_alias_group = """
                SELECT aliases.*, status.id AS status_id, status.status,
                        status.last_status, status.failed_tests, status.test_no,
                        status.max_uptime, status.uptime, status.last_success
                FROM aliases
                LEFT JOIN status ON status.alias_id = aliases.id
                WHERE aliases.id=? AND aliases.af=?
                """
                async with db.execute(sql_alias_group, (status_entry["alias_id"], need_af)) as cursor:
                    alias_row = await cursor.fetchone()
                    if alias_row:
                        group_records = [dict(alias_row)]

            if not group_records:
                continue

            # Step 3: ensure service_id and alias_id are set from the status entry
            for record in group_records:
                record["service_id"] = status_entry.get("service_id")
                record["alias_id"] = status_entry.get("alias_id")

            # Step 4: allocation logic
            allocatable_records = []
            for record in group_records:
                elapsed_since_last_status = current_time - (record["last_status"] or 0)

                if record["status"] == STATUS_DEALT:
                    if elapsed_since_last_status >= WORKER_TIMEOUT:
                        record["status"] = STATUS_AVAILABLE

                if elapsed_since_last_status < MONITOR_FREQUENCY:
                    continue

                if record["status"] == STATUS_AVAILABLE:
                    allocatable_records.append(record)

            if allocatable_records:
                # Step 5: mark group as allocated
                allocation_time = int(time.time())
                for record in allocatable_records:
                    await update_status_dealt(db, record["status_id"], t=allocation_time)
                return allocatable_records

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
    service_types = [STUN_MAP_TYPE, STUN_CHANGE_TYPE, MQTT_TYPE, TURN_TYPE, NTP_TYPE]
    protocols = [UDP, TCP]
    address_families = [IP4, IP6]
    servers = {}

    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row

        for service_type in service_types:
            servers[service_type] = {proto: {af: [] for af in address_families} for proto in protocols}

            for proto in protocols:
                for af in address_families:
                    sql = """
                    WITH server_scores AS (
                        SELECT
                            services.group_id,
                            services.id AS service_id,
                            services.ip,
                            services.af,
                            services.proto,
                            services.type,
                            status.id AS status_id,
                            status.failed_tests,
                            status.test_no,
                            status.uptime,
                            status.max_uptime,
                            status.last_status,
                            (
                                (1.0 - CAST(status.failed_tests AS REAL) / (status.test_no + 1e-9))
                                *
                                (0.5 * CASE WHEN status.max_uptime > 0 THEN status.uptime / status.max_uptime ELSE 1.0 END + 0.5)
                                *
                                (1.0 - EXP(-CAST(status.test_no AS REAL) / 50.0))
                            ) AS quality_score,
                            (
                                SELECT GROUP_CONCAT(fqn)
                                FROM aliases
                                WHERE aliases.ip = services.ip AND aliases.af = services.af
                            ) AS aliases
                        FROM services
                        JOIN status ON status.service_id = services.id
                        WHERE services.type = ?
                            AND services.proto = ?
                            AND services.af = ?
                    )
                    SELECT 
                        group_id,
                        AVG(quality_score) AS group_score,
                        json_group_array(
                            json_object(
                                'service_id', service_id,
                                'status_id', status_id,
                                'ip', ip,
                                'af', af,
                                'proto', proto,
                                'type', type,
                                'quality_score', quality_score,
                                'aliases', aliases
                            )
                            ORDER BY service_id ASC
                        ) AS servers
                    FROM server_scores
                    GROUP BY group_id
                    ORDER BY group_score DESC;
                    """

                    async with db.execute(sql, (service_type, proto, af)) as cursor:
                        rows = [dict(r) for r in await cursor.fetchall()]

                    # Convert JSON arrays of servers to Python lists
                    for row in rows:
                        row['servers'] = json.loads(row['servers'])

                    # Assign the list of groups to the nested structure
                    servers[service_type][proto][af] = [row['servers'] for row in rows]

    return servers


@app.get("/alias")
async def update_alias(alias_id: int, ip: str):
    async with aiosqlite.connect(DB_NAME) as db:
        sql = """
        UPDATE aliases
        SET ip = ?
        WHERE id = ?;
        """
        await db.execute(sql, (ip, alias_id,))
        await db.commit()

    return [alias_id]


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