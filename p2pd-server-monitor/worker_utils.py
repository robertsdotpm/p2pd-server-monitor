import asyncio
import aiosqlite
from p2pd import *

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