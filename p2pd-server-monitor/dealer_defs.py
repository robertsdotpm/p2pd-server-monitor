from p2pd import SOCK_DGRAM, SOCK_STREAM, V4, V6

# Placeholder -- fix this.
DB_NAME = "/home/x/Desktop/projects/p2pd-server-monitor/p2pd-server-monitor/monitor.sqlite3"

#####################################################################################
SERVICE_SCHEMA = ("type", "af", "proto", "ip", "port", "fallback_id")
STATUS_SCHEMA = ("service_id", "status", "last_status", "test_no")
STATUS_SCHEMA += ("failed_tests", "last_success")
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
            ["stun.hot-chilli.net"],
            STUN_CHANGE_TYPE, V4, SOCK_DGRAM, "49.12.125.53", 3478
        ],
    ],
]