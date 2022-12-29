#
# Copyright(c) 2020-2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#
import re

from core.test_run import TestRun
from test_utils.size import Unit
from test_utils.os_utils import Udev


class Mdadm:
    @staticmethod
    def assemble(device_paths: str = None):
        cmd = f"mdadm --assemble " + (device_paths if device_paths else "--scan")
        return TestRun.executor.run(cmd)

    @staticmethod
    def create(conf, device_paths: str):
        if not conf.name:
            raise ValueError("Name needed for RAID creation.")
        if not device_paths:
            raise ValueError("Device paths needed for RAID creation.")

        cmd = f"mdadm --create --run /dev/md/{conf.name} "
        if conf.metadata.value != "legacy":
            cmd += f"--metadata={conf.metadata.value} "
        if conf.level is not None:
            cmd += f"--level={conf.level.value} "
        if conf.number_of_devices:
            cmd += f"--raid-devices={conf.number_of_devices} "
        if conf.strip_size:
            cmd += f"--chunk={conf.strip_size} "
        if conf.size:
            cmd += f"--size={int(conf.size.get_value(Unit.KibiByte))} "
        cmd += device_paths
        ret = TestRun.executor.run_expect_success(cmd)

        Udev.trigger()
        Udev.settle()

        return ret

    @staticmethod
    def detail(raid_device_paths: str):
        if not raid_device_paths:
            raise ValueError("Provide paths of RAID devices to show details for.")
        cmd = f"mdadm --detail {raid_device_paths} --prefer=by-id"
        return TestRun.executor.run_expect_success(cmd)

    @classmethod
    def detail_result(cls, raid_device_paths: str):
        output = cls.detail(raid_device_paths)
        details = {}
        for device_details in re.split("^/dev/", output.stdout, flags=re.MULTILINE):
            if not device_details:
                continue
            lines = device_details.splitlines()
            key = "/dev/" + lines[0].rstrip(':')
            details[key] = {}
            details[key]["path"] = key
            details[key]["devices"] = cls.__parse_devices(device_details)
            details[key]["level"] = cls.__parse_level(device_details)
            details[key]["uuid"] = cls.__parse_uuid(device_details)
            metadata = cls.__parse_metadata(device_details)
            if metadata:
                details[key]["metadata"] = metadata

        return details

    @staticmethod
    def examine(brief: bool = True, device_paths: str = None):
        cmd = f"mdadm --examine "
        if brief:
            cmd += "--brief "
        cmd += (device_paths if device_paths else "--scan")
        return TestRun.executor.run_expect_success(cmd)

    @classmethod
    def examine_result(cls, device_paths: str = None):
        output = cls.examine(device_paths=device_paths)
        raids = []

        uuid_path_prefix = "/dev/disk/by-id/md-uuid-"

        for line in output.stdout.splitlines():
            split_line = line.split()
            try:
                uuid = [i for i in split_line if i.startswith("UUID=")][0].split("=")[-1]
            except IndexError:
                continue
            raid_link = uuid_path_prefix + uuid
            raid = Mdadm.detail_result(raid_link)[raid_link]
            if raid["level"] == "Container":
                continue
            raid["metadata"], raid["array_devices"] = "legacy", []
            container = (
                [i for i in split_line if i.startswith("container=")][0]
                if "container=" in line else None
            )
            if container:
                container_link = uuid_path_prefix + container.split("=")[-1]
                raid["container"] = cls.detail_result(container_link)[container_link]
                raid["metadata"] = raid["container"]["metadata"]
                raid["array_devices"] = raid["container"]["devices"]
            raids.append(raid)
        return raids

    @staticmethod
    def stop(device_paths: str = None):
        cmd = f"mdadm --stop " + (device_paths if device_paths else "--scan")
        return TestRun.executor.run_expect_success(cmd)

    @staticmethod
    def zero_superblock(device_paths: str):
        cmd = f"mdadm --zero-superblock {device_paths}"
        return TestRun.executor.run_expect_success(cmd)

    @staticmethod
    def __parse_devices(details: str):
        devices = []
        for detail in [d.strip() for d in details.splitlines() if "  /dev/" in d]:
            devices.append(detail.split()[-1])
        return devices

    @staticmethod
    def __parse_level(details: str):
        level = [line for line in details.splitlines() if "Raid Level" in line][0].split(" : ")[-1]
        return level.capitalize()

    @staticmethod
    def __parse_uuid(details: str):
        uuid = [line for line in details.splitlines() if "UUID" in line][0].split(" : ")[-1]
        return uuid

    @staticmethod
    def __parse_metadata(details: str):
        try:
            return [
                line.strip() for line in details.splitlines()
                if line.strip().startswith("Version :")
            ][0].split(" : ")[-1]
        except IndexError:
            return None
