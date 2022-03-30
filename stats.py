from typing import Dict, List
from collections import Counter, defaultdict
from pytz import timezone

import math
import hashlib
import datetime
import redis

TIME_BUCKETS = {
    "1h": datetime.timedelta(hours=1).total_seconds(),
    "3h": datetime.timedelta(hours=3).total_seconds(),
    "24h": datetime.timedelta(days=1).total_seconds(),
}
TOP_K_INTERACTIONS = 20
HOUR_SEC = int(datetime.timedelta(hours=1).total_seconds())

BOT_TIMEZONE = timezone("Europe/Zurich")
STARTTIME_TZ = datetime.datetime.now(BOT_TIMEZONE)
DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"

METRICS_RETENTION = datetime.timedelta(days=3)
REDIS_USER_NS = "user"
REDIS_NODE_NS = "node"


class Storage:

    def store_interaction(self, user_id: str, node: str, ts: int):
        pass

    def get_users_data(self) -> List[int]:
        pass

    def get_interactions_data(self) -> Counter:
        pass


class Stats:

    storage: Storage
    last_reload_time_tz: datetime.datetime
    last_reloader_username: str

    def __init__(self, storage: Storage):
        self.storage = storage
        self.last_reload_time_tz = None
        self.last_reloader_username = None

    def collect_interaction(self, user_id: int, node: str):
        ts = int(datetime.datetime.now(BOT_TIMEZONE).timestamp())
        return self.storage.store_interaction(hash_user(user_id), node, ts)

    def conversation_reloaded(self, username):
        self.last_reload_time_tz = datetime.datetime.now(BOT_TIMEZONE)
        self.last_reloader_username = username

    def compute(self) -> str:
        now_tz = datetime.datetime.now(BOT_TIMEZONE)
        uptime = now_tz - STARTTIME_TZ
        uptime = datetime.timedelta(seconds=int(uptime.total_seconds()))

        now_ts = int(now_tz.timestamp())
        interacts_data = self.storage.get_interactions_data().most_common(TOP_K_INTERACTIONS)
        users_data = defaultdict(int)
        for user_ts in self.storage.get_users_data():
            for k, bucket_ts in TIME_BUCKETS.items():
                if user_ts > now_ts - bucket_ts:
                    users_data[k] += 1

        users_stats = "\n".join([f"\t- {i}: {c}" for i, c in users_data.items()])
        interacts_stats = "\n".join([f"\t- {n}: {c}" for n, c in interacts_data])

        output = [
            f"Start time: {STARTTIME_TZ.strftime(DATETIME_FORMAT)}",
            f"Uptime: {uptime}"
        ]
        if self.last_reload_time_tz:
            output.append(f"Last conversation reload: {self.last_reload_time_tz.strftime(DATETIME_FORMAT)} ({self.last_reloader_username})")

        output.extend([
            f"Total users:\n{users_stats}",
            f"Top {TOP_K_INTERACTIONS} interactions:\n{interacts_stats}"
        ])
        return "\n".join(output)


class RedisStorage(Storage):

    rd: redis.Redis

    def __init__(self, rd: redis.Redis):
        self.rd = rd

    def store_interaction(self, user_id: str, node: str, ts: int):
        pipeline = self.rd.pipeline()
        pipeline.setex(
            f"{REDIS_USER_NS}:{user_id}",
            METRICS_RETENTION,
            ts,
        )
        bucket = self.hbucket(ts, 1)
        pipeline.hincrby(f"{REDIS_NODE_NS}:{bucket}", node, 1)
        pipeline.expire(
            f"{REDIS_NODE_NS}:{bucket}",
            METRICS_RETENTION,
        )
        pipeline.execute()

    def get_users_data(self) -> List[int]:
        users_data = []
        for user in self.rd.scan_iter(f"{REDIS_USER_NS}:*"):
            users_data.append(int(self.rd.get(user)))

        return users_data

    def get_interactions_data(self) -> Counter:
        interacts_data = Counter()
        for bucket in self.hourly_buckets(METRICS_RETENTION.total_seconds()):
            node_stats = self.rd.hgetall(f"{REDIS_NODE_NS}:{bucket}").items()
            for node, node_interacts in node_stats:
                interacts_data[node.decode("utf-8")] += int(node_interacts)

        return interacts_data

    def hourly_buckets(self, stats_period: int) -> List[int]:
        now_ts = int(datetime.datetime.now(BOT_TIMEZONE).timestamp())
        num_buckets = math.ceil(stats_period / HOUR_SEC)
        buckets = []
        for i in range(1, num_buckets + 1):
            buckets.append(self.hbucket(now_ts, i))

        return buckets

    def hbucket(self, now_ts: int, bucket: int) -> int:
        return now_ts - (now_ts % HOUR_SEC) - HOUR_SEC * (bucket - 1)


class MemStorage(Storage):

    timestamp_by_user: Dict[str, int]
    interactions: Counter()

    def __init__(self):
        self.timestamp_by_user = {}
        self.interactions = Counter()

    def store_interaction(self, user_id: str, node: str, ts: int):
        self.timestamp_by_user[user_id] = ts
        self.interactions[node] += 1

    def get_users_data(self) -> List[int]:
        return self.timestamp_by_user.values()

    def get_interactions_data(self) -> Counter:
        return self.interactions


def hash_user(user_id: int) -> str:
    return hashlib.sha256(user_id.to_bytes(10, byteorder='big', signed=True)).hexdigest()
