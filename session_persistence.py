import logging
import os
import redis
import simplejson as json
from datetime import timedelta
from typing import List
from urllib.parse import urlparse

SESSION_DURATION = timedelta(minutes=30)
SESSIONS_DATABASE = 0

logger = logging.getLogger(__name__)

class SessionPersistence:
    def __init__(self):
        use_ssl = True
        redis_url = os.environ.get("REDIS_TLS_URL")
        if redis_url is None:
            redis_url = "redis://localhost:6379"
            use_ssl = False

        logger.info(f"Using redis-based session persistence.\nURL: '{redis_url}', Use SSL: {use_ssl}")
        url = urlparse(redis_url)
        self.r = redis.Redis(db=SESSIONS_DATABASE, host=url.hostname, port=url.port, username=url.username, password=url.password, ssl=use_ssl, ssl_cert_reqs=None, decode_responses=True)


    def save_nav_stack(self, user_id: int, nav_stack: List[str]) -> None:
        self.r.setex(user_id, SESSION_DURATION, json.dumps(nav_stack))


    def load_nav_stack(self, user_id: int) -> List[str]:
        session_json = self.r.get(user_id)
        try:
            return json.loads(session_json)
        except:
            return None


class NullSessionPersistence(SessionPersistence):
    def __init__(self):
        logger.info("Using null session persistence")


    def save_nav_stack(self, user_id: int, nav_stack: List[str]) -> None:
        pass


    def load_nav_stack(self, user_id: int) -> List[str]:
        return None
