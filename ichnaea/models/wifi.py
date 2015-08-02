import colander
from enum import IntEnum
from sqlalchemy import (
    Column,
    Date,
    Index,
    String,
    PrimaryKeyConstraint,
    UniqueConstraint,
)
from sqlalchemy.dialects.mysql import (
    INTEGER as Integer,
    TINYINT as TinyInteger,
)
from sqlalchemy.ext.declarative import declared_attr

from ichnaea.models import constants
from ichnaea.models.base import (
    _Model,
    BigIdMixin,
    CreationMixin,
    PositionMixin,
    TimeTrackingMixin,
)
from ichnaea.models.hashkey import (
    HashKey,
    HashKeyQueryMixin,
)
from ichnaea.models.sa_types import (
    MacColumn,
    TinyIntEnum,
)
from ichnaea.models.schema import (
    CopyingSchema,
    DefaultNode,
    FieldSchema,
    ValidatorNode,
)
from ichnaea.models.station import (
    BboxMixin,
    StationMixin,
    StationBlocklistMixin,
    ValidStationSchema,
)

WIFI_SHARDS = {}


class WifiKey(HashKey):

    _fields = ('key', )


class WifiKeyMixin(HashKeyQueryMixin):

    _hashkey_cls = WifiKey
    _query_batch = 100

    key = Column(String(12))


class WifiKeyNode(ValidatorNode):
    """
    A node containing a valid wifi key.
    ex: 01005e901000
    """

    def preparer(self, cstruct):
        # Remove ':' '-' ',' from a wifi key.
        if cstruct and (':' in cstruct or '-' in cstruct or '.' in cstruct):
            cstruct = (cstruct.replace(':', '')
                              .replace('-', '')
                              .replace('.', ''))
        return cstruct and cstruct.lower() or colander.null

    def validator(self, node, cstruct):
        super(WifiKeyNode, self).validator(node, cstruct)

        valid = (len(cstruct) == 12 and
                 constants.INVALID_WIFI_REGEX.match(cstruct) and
                 constants.VALID_WIFI_REGEX.match(cstruct))

        if not valid:
            raise colander.Invalid(node, 'Invalid wifi key')


class ValidWifiKeySchema(FieldSchema, CopyingSchema):
    """A schema which validates the fields present in a a wifi key."""

    key = WifiKeyNode(colander.String())


class ValidWifiSignalSchema(FieldSchema, CopyingSchema):
    """
    A schema which validates the fields related to wifi signal
    strength and quality.
    """

    channel = DefaultNode(
        colander.Integer(),
        missing=None,
        validator=colander.Range(
            constants.MIN_WIFI_CHANNEL, constants.MAX_WIFI_CHANNEL))
    signal = DefaultNode(
        colander.Integer(),
        missing=None,
        validator=colander.Range(
            constants.MIN_WIFI_SIGNAL, constants.MAX_WIFI_SIGNAL))
    snr = DefaultNode(
        colander.Integer(),
        missing=None,
        validator=colander.Range(0, 100))

    def deserialize(self, data):
        if data:
            channel = data.get('channel')
            channel = channel is not None and int(channel) or None

            if (channel is None or not
                    (constants.MIN_WIFI_CHANNEL < channel <
                     constants.MAX_WIFI_CHANNEL)):
                # if no explicit channel was given, calculate
                freq = data.get('frequency', None)
                if freq is None:
                    freq = 0

                if 2411 < freq < 2473:
                    # 2.4 GHz band
                    data['channel'] = (freq - 2407) // 5

                elif 5169 < freq < 5826:
                    # 5 GHz band
                    data['channel'] = (freq - 5000) // 5

                else:
                    data['channel'] = None

        return super(ValidWifiSignalSchema, self).deserialize(data)


class WifiMixin(BigIdMixin, WifiKeyMixin):
    pass


class ValidWifiSchema(ValidWifiKeySchema, ValidStationSchema):
    """A schema which validates the fields in wifi."""


class Wifi(WifiMixin, StationMixin, CreationMixin, _Model):
    __tablename__ = 'wifi'

    _indices = (
        UniqueConstraint('key', name='wifi_key_unique'),
        Index('wifi_created_idx', 'created'),
    )
    _valid_schema = ValidWifiSchema


class WifiBlocklist(WifiMixin, StationBlocklistMixin, _Model):
    __tablename__ = 'wifi_blacklist'

    _indices = (
        UniqueConstraint('key', name='wifi_blacklist_key_unique'),
    )


class StationSource(IntEnum):
    """
    The station source states on what kind of data the station
    record is based on. A lower integer value hints at a better quality
    of the observation data that went into this station record.
    """

    fixed = 0  #: Outside knowledge about the true position of the station.
    gnss = 3  #: Global navigation satellite system based data.
    fused = 6  #: Observation data positioned based on fused data.
    query = 9  #: Position estimate based on query data.


class WifiMac(HashKey):

    _fields = ('mac', )


class WifiShard(HashKeyQueryMixin,
                CreationMixin,
                PositionMixin,
                BboxMixin,
                TimeTrackingMixin):

    _hashkey_cls = WifiMac
    _query_batch = 100

    mac = Column(MacColumn(6))
    radius = Column(Integer(unsigned=True))

    country = Column(String(2))
    samples = Column(Integer(unsigned=True))
    source = Column(TinyIntEnum(StationSource))

    block_first = Column(Date)
    block_last = Column(Date)
    block_count = Column(TinyInteger(unsigned=True))

    @declared_attr
    def __table_args__(cls):  # NOQA
        _indices = (
            PrimaryKeyConstraint('mac'),
            Index('%s_country_idx' % cls.__tablename__, 'country'),
            Index('%s_created_idx' % cls.__tablename__, 'created'),
            Index('%s_modified_idx' % cls.__tablename__, 'modified'),
            Index('%s_latlon_idx' % cls.__tablename__, 'lat', 'lon'),
        )
        return _indices + (cls._settings, )

    @property
    def range(self):
        # BBB: alias
        return self.radius

    @property
    def total_measures(self):
        # BBB: alias
        return self.samples

    @classmethod
    def shard_model(cls, mac):
        """
        Given a BSSID/MAC return the correct DB model class for this
        shard of data.

        The shard id is based on the fifth hex character of the vendor
        prefix of the BSSID. This tends to be evenly distributed, but
        still keeps data from the same vendor inside the same table.

        It also allows us to later extend the sharding by taking in
        parts of the sixth hex char without having to do a complete
        re-sharding of everything, but merely breaking up each shard
        further.
        """
        if not mac:
            return None
        return WIFI_SHARDS.get(mac.lower()[4], None)


class WifiShard0(WifiShard, _Model):
    __tablename__ = 'wifi_shard_0'

WIFI_SHARDS['0'] = WifiShard0


class WifiShard1(WifiShard, _Model):
    __tablename__ = 'wifi_shard_1'

WIFI_SHARDS['1'] = WifiShard1


class WifiShard2(WifiShard, _Model):
    __tablename__ = 'wifi_shard_2'

WIFI_SHARDS['2'] = WifiShard2


class WifiShard3(WifiShard, _Model):
    __tablename__ = 'wifi_shard_3'

WIFI_SHARDS['3'] = WifiShard3


class WifiShard4(WifiShard, _Model):
    __tablename__ = 'wifi_shard_4'

WIFI_SHARDS['4'] = WifiShard4


class WifiShard5(WifiShard, _Model):
    __tablename__ = 'wifi_shard_5'

WIFI_SHARDS['5'] = WifiShard5


class WifiShard6(WifiShard, _Model):
    __tablename__ = 'wifi_shard_6'

WIFI_SHARDS['6'] = WifiShard6


class WifiShard7(WifiShard, _Model):
    __tablename__ = 'wifi_shard_7'

WIFI_SHARDS['7'] = WifiShard7


class WifiShard8(WifiShard, _Model):
    __tablename__ = 'wifi_shard_8'

WIFI_SHARDS['8'] = WifiShard8


class WifiShard9(WifiShard, _Model):
    __tablename__ = 'wifi_shard_9'

WIFI_SHARDS['9'] = WifiShard9


class WifiShardA(WifiShard, _Model):
    __tablename__ = 'wifi_shard_a'

WIFI_SHARDS['a'] = WifiShardA


class WifiShardB(WifiShard, _Model):
    __tablename__ = 'wifi_shard_b'

WIFI_SHARDS['b'] = WifiShardB


class WifiShardC(WifiShard, _Model):
    __tablename__ = 'wifi_shard_c'

WIFI_SHARDS['c'] = WifiShardC


class WifiShardD(WifiShard, _Model):
    __tablename__ = 'wifi_shard_d'

WIFI_SHARDS['d'] = WifiShardD


class WifiShardE(WifiShard, _Model):
    __tablename__ = 'wifi_shard_e'

WIFI_SHARDS['e'] = WifiShardE


class WifiShardF(WifiShard, _Model):
    __tablename__ = 'wifi_shard_f'

WIFI_SHARDS['f'] = WifiShardF
