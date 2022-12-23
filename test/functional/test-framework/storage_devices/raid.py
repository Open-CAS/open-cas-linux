#
# Copyright(c) 2020-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#
import threading
from enum import IntEnum, Enum

from core.test_run import TestRun
from storage_devices.device import Device
from storage_devices.disk import Disk
from test_tools.fs_utils import readlink
from test_tools.mdadm import Mdadm
from test_utils.disk_finder import resolve_to_by_id_link
from test_utils.size import Size, Unit


def get_devices_paths_string(devices: [Device]):
    return " ".join([d.path for d in devices])


class Level(IntEnum):
    Raid0 = 0
    Raid1 = 1
    Raid4 = 4
    Raid5 = 5
    Raid6 = 6
    Raid10 = 10


class StripSize(IntEnum):
    Strip4K = 4
    Strip8K = 8
    Strip16K = 16
    Strip32K = 32
    Strip64K = 64
    Strip128K = 128
    Strip256K = 256
    Strip1M = 1024


class MetadataVariant(Enum):
    Legacy = "legacy"
    Imsm = "imsm"


class RaidConfiguration:
    def __init__(
            self,
            level: Level = None,
            metadata: MetadataVariant = MetadataVariant.Imsm,
            number_of_devices: int = 0,
            size: Size = None,
            strip_size: StripSize = None,
            name: str = None,
    ):
        self.level = level
        self.metadata = metadata
        self.number_of_devices = number_of_devices
        self.size = size
        self.strip_size = strip_size
        self.name = name


class Raid(Disk):
    __unique_id = 0
    __lock = threading.Lock()

    def __init__(
            self,
            path: str,
            level: Level,
            uuid: str,
            container_uuid: str = None,
            container_path: str = None,
            metadata: MetadataVariant = MetadataVariant.Imsm,
            array_devices: [Device] = [],
            volume_devices: [Device] = [],
    ):
        Device.__init__(self, resolve_to_by_id_link(path.replace("/dev/", "")))
        self.device_name = path.split('/')[-1]
        self.level = level
        self.uuid = uuid
        self.container_uuid = container_uuid
        self.container_path = container_path
        self.metadata = metadata
        self.array_devices = array_devices if array_devices else volume_devices.copy()
        self.volume_devices = volume_devices
        self.partitions = []
        self.__block_size = None

    def __eq__(self, other):
        try:
            return self.uuid == other.uuid
        except AttributeError:
            return False

    @property
    def block_size(self):
        if not self.__block_size:
            self.__block_size = Unit(int(self.get_sysfs_property("logical_block_size")))
        return self.__block_size

    def stop(self):
        Mdadm.stop(self.path)
        if self.container_path:
            Mdadm.stop(self.container_path)

    @classmethod
    def discover(cls):
        TestRun.LOGGER.info("Discover RAIDs in system...")
        raids = []
        for raid in Mdadm.examine_result():
            raids.append(
                cls(
                    raid["path"],
                    Level[raid["level"]],
                    raid["uuid"],
                    raid["container"]["uuid"] if "container" in raid else None,
                    raid["container"]["path"] if "container" in raid else None,
                    MetadataVariant(raid["metadata"]),
                    [Device(d) for d in raid["array_devices"]],
                    [Device(d) for d in raid["devices"]]
                )
            )

        return raids

    @classmethod
    def create(
            cls,
            raid_configuration: RaidConfiguration,
            devices: [Device]
    ):
        import copy
        raid_conf = copy.deepcopy(raid_configuration)

        if not raid_conf.number_of_devices:
            raid_conf.number_of_devices = len(devices)
        elif len(devices) < raid_conf.number_of_devices:
            raise ValueError("RAID configuration requires at least "
                             f"{raid_conf.number_of_devices} devices")

        md_dir_path = "/dev/md/"
        array_devices = devices
        volume_devices = devices[:raid_conf.number_of_devices]

        if raid_conf.metadata != MetadataVariant.Legacy:
            container_conf = RaidConfiguration(
                name=cls.__get_unique_name(raid_conf.metadata.value),
                metadata=raid_conf.metadata,
                number_of_devices=len(array_devices)
            )
            Mdadm.create(container_conf, get_devices_paths_string(array_devices))

        if not raid_conf.name:
            raid_conf.name = cls.__get_unique_name()

        Mdadm.create(raid_conf, get_devices_paths_string(volume_devices))

        raid_link = md_dir_path + raid_conf.name
        raid = [r for r in Mdadm.examine_result() if readlink(r["path"]) == readlink(raid_link)][0]

        return cls(
            raid["path"],
            raid_conf.level,
            raid["uuid"],
            raid["container"]["uuid"] if "container" in raid else None,
            raid["container"]["path"] if "container" in raid else None,
            raid_conf.metadata,
            array_devices,
            volume_devices
        )

    @staticmethod
    def remove_all():
        Mdadm.stop()

    @classmethod
    def __get_unique_name(cls, prefix: str = "Raid"):
        with cls.__lock:
            cls.__unique_id += 1
            return f"{prefix}{cls.__unique_id}"
