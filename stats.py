from typing import Dict
from collections import Counter
from pytz import timezone
import hashlib
import datetime

HOUR = datetime.timedelta(hours=1).total_seconds()
THREEHOURS = datetime.timedelta(hours=3).total_seconds()
DAY = datetime.timedelta(days=1).total_seconds()
BOT_TIMEZONE = timezone("Europe/Zurich")
STARTTIME_UTC = datetime.datetime.now(BOT_TIMEZONE)

class Stats:
    timestamp_by_user: Dict[str, float]
    interactions: Counter

    def __init__(self):
        self.timestamp_by_user = dict()
        self.interactions = Counter()

    def hash_user(self, user_id: int) -> str:
        return hashlib.sha256(user_id.to_bytes(10, byteorder='big', signed=True)).hexdigest()

    def collect(self, user_id: int, node: str):
        # collect user stats
        user_hash = self.hash_user(user_id)
        self.timestamp_by_user[user_hash] = datetime.datetime.now().timestamp()
        # collect node stats
        self.interactions[node] += 1

    def compute(self) -> str:
        hourly = 0
        threehourly = 0
        daily = 0
        now = datetime.datetime.now().timestamp()
        for u in self.timestamp_by_user:
            user_ts = self.timestamp_by_user[u]
            hourly += 1 if user_ts > now - HOUR else 0
            threehourly += 1 if user_ts > now - THREEHOURS else 0
            daily += 1 if user_ts > now - DAY else 0

        node_stats = "\n".join([f"\t- {n}: {c}" for n, c in self.interactions.most_common(10)])
        user_stats = f"\t- 1h: {hourly}\n\t- 3h: {threehourly}\n\t- 24h: {daily}"
        now_tz = datetime.datetime.now(BOT_TIMEZONE)
        uptime = str(now_tz - STARTTIME_UTC).split('.')[0]
        return f"Start time: {now_tz.replace(microsecond=0)}\nUptime: {uptime}\nTotal users:\n{user_stats}\nTop 10 interactions:\n{node_stats}"
