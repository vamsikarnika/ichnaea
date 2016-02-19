from collections import defaultdict
from datetime import timedelta

from sqlalchemy import func

from ichnaea.models import CellOCID
from ichnaea import util


class ApiKeyLimits(object):

    def __init__(self, task):
        self.task = task
        self.redis_client = task.redis_client
        self.stats_client = task.stats_client

    def __call__(self):
        today = util.utcnow().strftime('%Y%m%d')
        keys = self.redis_client.keys('apilimit:*:' + today)
        values = []
        if keys:
            values = self.redis_client.mget(keys)
            keys = [k.decode('utf-8').split(':')[1:3] for k in keys]

        result = defaultdict(dict)
        for (api_key, path), value in zip(keys, values):
            value = int(value)
            result[api_key][path] = value
            self.stats_client.gauge(
                'api.limit', value, tags=['key:' + api_key, 'path:' + path])
        return result


class ApiUsers(object):

    def __init__(self, task):
        self.task = task
        self.redis_client = task.redis_client
        self.stats_client = task.stats_client

    def __call__(self):
        days = {}
        today = util.utcnow().date()
        for i in range(0, 7):
            day = today - timedelta(days=i)
            days[i] = day.strftime('%Y-%m-%d')

        metrics = defaultdict(list)
        result = {}
        for key in self.redis_client.scan_iter(
                match='apiuser:*', count=100):
            _, api_type, api_name, day = key.decode('ascii').split(':')
            if day not in days.values():
                # delete older entries
                self.redis_client.delete(key)
                continue

            if day == days[0]:
                metrics[(api_type, api_name, '1d')].append(key)

            metrics[(api_type, api_name, '7d')].append(key)

        for parts, keys in metrics.items():
            api_type, api_name, interval = parts
            value = self.redis_client.pfcount(*keys)

            self.stats_client.gauge(
                '%s.user' % api_type, value,
                tags=['key:%s' % api_name, 'interval:%s' % interval])
            result['%s:%s:%s' % parts] = value
        return result


class OcidImport(object):

    def __init__(self, task):
        self.task = task
        self.stats_client = task.stats_client

    def __call__(self):
        max_created = None
        now = util.utcnow()
        result = -1

        with self.task.db_session(commit=False) as session:
            query = session.query(func.max(CellOCID.created))
            max_created = query.first()[0]

        if max_created:
            # diff between now and the value, in milliseconds
            diff = now - max_created
            result = (diff.days * 86400 + diff.seconds) * 1000

        self.stats_client.gauge('table', result, tags=['table:cell_ocid_age'])
        return result


class QueueSize(object):

    def __init__(self, task):
        self.task = task
        self.redis_client = task.redis_client
        self.stats_client = task.stats_client

    def __call__(self):
        result = {}
        for name in self.task.app.all_queues:
            result[name] = value = self.redis_client.llen(name)
            self.stats_client.gauge('queue', value, tags=['queue:' + name])
        return result
