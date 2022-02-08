#
# Copyright(c) 2012-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import subprocess
import csv
import re
import os
import stat
import time

# Casadm functionality


class casadm:
    casadm_path = '/sbin/casadm'

    class result:
        def __init__(self, cmd):
            p = subprocess.run(cmd, universal_newlines=True, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE)
            self.exit_code = p.returncode
            self.stdout = p.stdout
            self.stderr = p.stderr

    class CasadmError(Exception):
        def __init__(self, result):
            super(casadm.CasadmError, self).__init__('casadm error: {}'.format(result.stderr))
            self.result = result

    @classmethod
    def run_cmd(cls, cmd):
        result = cls.result(cmd)
        if result.exit_code != 0:
            raise cls.CasadmError(result)
        return result

    @classmethod
    def get_version(cls):
        cmd = [cls.casadm_path,
               '--version',
               '--output-format', 'csv']
        return cls.run_cmd(cmd)

    @classmethod
    def list_caches(cls):
        cmd = [cls.casadm_path,
               '--list-caches',
               '--output-format', 'csv',
               '--by-id-path']
        return cls.run_cmd(cmd)

    @classmethod
    def check_cache_device(cls, device):
        cmd = [cls.casadm_path,
               '--script',
               '--check-cache-device',
               '--cache-device', device]
        return cls.run_cmd(cmd)

    @classmethod
    def start_cache(
        cls, device, cache_id=None, cache_mode=None, cache_line_size=None, load=False, force=False
    ):
        cmd = [cls.casadm_path,
               '--start-cache',
               '--cache-device', device]
        if cache_id:
            cmd += ['--cache-id', str(cache_id)]
        if cache_mode:
            cmd += ['--cache-mode', cache_mode]
        if cache_line_size:
            cmd += ['--cache-line-size', str(cache_line_size)]
        if load:
            cmd += ['--load']
        if force:
            cmd += ['--force']
        return cls.run_cmd(cmd)

    @classmethod
    def start_standby_cache(
        cls, device, cache_id=None, cache_line_size=None, load=False, force=False
    ):
        cmd = [cls.casadm_path,
               '--standby',
               '--init' if not load else '--load',
               '--cache-device', device]
        if cache_id:
            cmd += ['--cache-id', str(cache_id)]
        if cache_line_size:
            cmd += ['--cache-line-size', str(cache_line_size)]
        if force:
            cmd += ['--force']
        return cls.run_cmd(cmd)

    @classmethod
    def add_core(cls, device, cache_id, core_id=None, try_add=False):
        cmd = [cls.casadm_path,
               '--script',
               '--add-core',
               '--core-device', device,
               '--cache-id', str(cache_id)]
        if core_id is not None:
            cmd += ['--core-id', str(core_id)]
        if try_add:
            cmd += ['--try-add']
        return cls.run_cmd(cmd)

    @classmethod
    def stop_cache(cls, cache_id, no_flush=False):
        cmd = [cls.casadm_path,
               '--stop-cache',
               '--cache-id', str(cache_id)]
        if no_flush:
            cmd += ['--no-data-flush']
        return cls.run_cmd(cmd)

    @classmethod
    def remove_core(cls, cache_id, core_id, detach=False, force=False):
        cmd = [cls.casadm_path,
               '--script',
               '--remove-core',
               '--cache-id', str(cache_id),
               '--core-id', str(core_id)]
        if detach:
            cmd += ['--detach']
        if force:
            cmd += ['--no-flush']
        return cls.run_cmd(cmd)

    @classmethod
    def set_param(cls, namespace, cache_id, **kwargs):
        cmd = [cls.casadm_path,
               '--set-param', '--name', namespace,
               '--cache-id', str(cache_id)]

        for param, value in kwargs.items():
            cmd += ['--'+param.replace('_', '-'), str(value)]

        return cls.run_cmd(cmd)

    @classmethod
    def get_params(cls, namespace, cache_id, **kwargs):
        cmd = [cls.casadm_path,
               '--get-param', '--name', namespace,
               '--cache-id', str(cache_id)]

        for param, value in kwargs.items():
            cmd += ['--'+param.replace('_', '-'), str(value)]

        cmd += ['-o', 'csv']

        return cls.run_cmd(cmd)

    @classmethod
    def flush_parameters(cls, cache_id, policy_type):
        cmd = [cls.casadm_path,
               '--flush-parameters',
               '--cache-id', str(cache_id),
               '--cleaning-policy-type', policy_type]
        return cls.run_cmd(cmd)

    @classmethod
    def io_class_load_config(cls, cache_id, ioclass_file):
        cmd = [cls.casadm_path,
               '--io-class',
               '--load-config',
               '--cache-id', str(cache_id),
               '--file', ioclass_file]
        return cls.run_cmd(cmd)


# Configuration file parser


class cas_config(object):
    default_location = '/etc/opencas/opencas.conf'
    _by_id_dir = '/dev/disk/by-id'

    class ConflictingConfigException(ValueError):
        pass

    class AlreadyConfiguredException(ValueError):
        pass

    @staticmethod
    def get_by_id_path(path):
        path = os.path.abspath(path)

        if os.path.exists(path) or cas_config._is_exp_obj_path(path):
            return path
        else:
            raise ValueError(f"Given path {path} isn't correct by-id path.")

    @staticmethod
    def _is_exp_obj_path(path):
        return re.search(r"cas\d+-\d+", path) is not None

    @staticmethod
    def check_block_device(path):
        if not os.path.exists(path) and path.startswith('/dev/cas'):
            return

        try:
            mode = os.stat(path).st_mode
        except:
            raise ValueError(f'{path} not found')

        if not stat.S_ISBLK(mode):
            raise ValueError(f'{path} is not block device')

    class cache_config(object):
        def __init__(self, cache_id, device, cache_mode, **params):
            self.cache_id = int(cache_id)
            self.device = device
            self.cache_mode = cache_mode.lower()
            self.params = params
            self.cores = dict()

        @classmethod
        def from_line(cls, line, allow_incomplete=False):
            values = line.split()
            if len(values) < 3:
                raise ValueError('Invalid cache configuration (too few columns)')
            elif len(values) > 4:
                raise ValueError('Invalid cache configuration (too many columns)')

            cache_id = int(values[0])
            device = values[1]
            cache_mode = values[2].lower()

            params = dict()
            if len(values) > 3:
                for param in values[3].lower().split(','):
                    param_name, param_value = param.split('=')
                    if param_name in params:
                        raise ValueError('Invalid cache configuration (repeated parameter')
                    params[param_name] = param_value

            cache_config = cls(cache_id, device, cache_mode, **params)
            cache_config.validate_config(False, allow_incomplete)

            return cache_config

        def validate_config(self, force, allow_incomplete=False):
            type(self).check_cache_id_valid(self.cache_id)
            self.check_recursive()
            self.check_cache_mode_valid(self.cache_mode)
            for param_name, param_value in self.params.items():
                self.validate_parameter(param_name, param_value)

            if not allow_incomplete:
                cas_config.check_block_device(self.device)
                if not force:
                    self.check_cache_device_empty()

        def validate_parameter(self, param_name, param_value):
            if param_name == 'ioclass_file':
                if not os.path.exists(param_value):
                    raise ValueError('Invalid path to io_class file')
            elif param_name == 'cleaning_policy':
                self.check_cleaning_policy_valid(param_value)
            elif param_name == 'promotion_policy':
                self.check_promotion_policy_valid(param_value)
            elif param_name == 'cache_line_size':
                self.check_cache_line_size_valid(param_value)
            elif param_name == "lazy_startup":
                self.check_lazy_startup_valid(param_value)
            elif param_name == "target_failover_state":
                self.check_failover_state_valid(param_value)
            else:
                raise ValueError(f'{param_name} is invalid parameter name')

        @staticmethod
        def check_cache_id_valid(cache_id):
            if not 1 <= int(cache_id) <= 16384:
                raise ValueError(f'{cache_id} is invalid cache id')

        def check_cache_device_empty(self):
            try:
                result = casadm.run_cmd(['lsblk', '-o', 'NAME',  '-l', '-n', self.device])
            except:
                # lsblk returns non-0 if it can't probe for partitions
                # this means that we're probably dealing with atomic device
                # let it through
                return

            if len(list(filter(lambda a: a != '', result.stdout.split('\n')))) > 1:
                raise ValueError(
                    'Partitions found on device {self.device}. Use force option to ignore'
                )

        def check_cache_mode_valid(self, cache_mode):
            if cache_mode not in ['wt', 'pt', 'wa', 'wb', 'wo']:
                raise ValueError(f'Invalid cache mode {cache_mode}')

        def check_cleaning_policy_valid(self, cleaning_policy):
            if cleaning_policy not in ['acp', 'alru', 'nop']:
                raise ValueError(f'{cleaning_policy} is invalid cleaning policy name')

        def check_lazy_startup_valid(self, lazy_startup):
            if lazy_startup not in ["true", "false"]:
                raise ValueError('{0} is invalid lazy_startup value'.format(lazy_startup))

        def check_failover_state_valid(self, failover_state):
            if failover_state not in ["active", "standby"]:
                raise ValueError(f"{failover_state} is invalid target_failover_state value")

        def check_promotion_policy_valid(self, promotion_policy):
            if promotion_policy not in ['always', 'nhit']:
                raise ValueError(f'{promotion_policy} is invalid promotion policy name')

        def check_cache_line_size_valid(self, cache_line_size):
            if cache_line_size not in ['4', '8', '16', '32', '64']:
                raise ValueError(f'{cache_line_size} is invalid cache line size')

        def check_recursive(self):
            if not self.device.startswith('/dev/cas'):
                return

            ids = self.device.split('/dev/cas')[1]
            device_cache_id, _ = ids.split('-')

            if int(device_cache_id) == self.cache_id:
                raise ValueError('Recursive configuration detected')

        def to_line(self):
            ret = f'{self.cache_id}\t{self.device}\t{self.cache_mode}'
            if len(self.params) > 0:
                i = 0
                for param, value in self.params.items():
                    if i > 0:
                        ret += ','
                    else:
                        ret += '\t'

                    ret += f'{param}={value}'
                    i += 1
            ret += '\n'

            return ret

        def is_lazy(self):
            return self.params.get("lazy_startup", "false") == "true"

    class core_config(object):
        def __init__(self, cache_id, core_id, path, **params):
            self.cache_id = int(cache_id)
            self.core_id = int(core_id)
            self.device = path
            self.params = params

        @classmethod
        def from_line(cls, line, allow_incomplete=False):
            values = line.split()
            if len(values) > 4:
                raise ValueError("Invalid core configuration (too many columns)")
            elif len(values) < 3:
                raise ValueError("Invalid core configuration (too few columns)")

            cache_id = int(values[0])
            core_id = int(values[1])
            device = values[2]

            params = dict()
            if len(values) > 3:
                for param in values[3].lower().split(","):
                    param_name, param_value = param.split("=")
                    if param_name in params:
                        raise ValueError(
                            "Invalid core configuration (repeated parameter)"
                        )
                    params[param_name] = param_value

            core_config = cls(cache_id, core_id, device, **params)

            core_config.validate_config(allow_incomplete)

            return core_config

        def validate_config(self, allow_incomplete=False):
            self.check_core_id_valid()
            self.check_recursive()
            cas_config.cache_config.check_cache_id_valid(self.cache_id)

            for param_name, param_value in self.params.items():
                self.validate_parameter(param_name, param_value)

            if not allow_incomplete:
                cas_config.check_block_device(self.device)

        def validate_parameter(self, param_name, param_value):
            if param_name == "lazy_startup":
                if param_value not in ["true", "false"]:
                    raise ValueError(
                        f"{param_value} is invalid value for '{param_name}' core param"
                    )
            else:
                raise ValueError(f"'{param_name}' is invalid core param name")

        def check_core_id_valid(self):
            if not 0 <= int(self.core_id) <= 4095:
                raise ValueError(f'{self.core_id} is invalid core id')

        def check_recursive(self):
            if not self.device.startswith('/dev/cas'):
                return

            ids = self.device.split('/dev/cas')[1]
            device_cache_id, _ = ids.split('-')

            if int(device_cache_id) == self.cache_id:
                raise ValueError('Recursive configuration detected')

        def to_line(self):
            ret = f"{self.cache_id}\t{self.core_id}\t{self.device}"
            for i, (param, value) in enumerate(self.params.items()):
                ret += "," if i > 0 else "\t"

                ret += f"{param}={value}"
            ret += "\n"

            return ret

        def is_lazy(self):
            return self.params.get("lazy_startup", "false") == "true"

    def __init__(self, caches=None, cores=None, version_tag=None):
        self.caches = caches if caches else dict()

        self.cores = cores if cores else list()

        self.version_tag = version_tag

    @classmethod
    def from_file(cls, config_file, allow_incomplete=False):
        section_caches = False
        section_cores = False

        try:
            with open(config_file, 'r') as conf:
                version_tag = conf.readline()
                if not re.findall(r'^version=.*$', version_tag):
                    raise ValueError('No version tag found!')

                config = cls(version_tag=version_tag)

                for line in conf:
                    line = line.split('#')[0].rstrip()
                    if not line:
                        continue

                    if line == '[caches]':
                        section_caches = True
                        continue

                    if line == '[cores]':
                        section_caches = False
                        section_cores = True
                        continue

                    if section_caches:
                        cache = cas_config.cache_config.from_line(line, allow_incomplete)
                        config.insert_cache(cache)
                    elif section_cores:
                        core = cas_config.core_config.from_line(line, allow_incomplete)
                        config.insert_core(core)
        except ValueError:
            raise
        except IOError:
            raise Exception('Couldn\'t open config file')
        except:
            raise

        return config

    def insert_cache(self, new_cache_config):
        if new_cache_config.cache_id in self.caches:
            if (os.path.realpath(self.caches[new_cache_config.cache_id].device)
                    != os.path.realpath(new_cache_config.device)):
                raise cas_config.ConflictingConfigException(
                        'Other cache device configured under this id')
            else:
                raise cas_config.AlreadyConfiguredException(
                                'Cache already configured')

        for cache_id, cache in self.caches.items():
            if cache_id != new_cache_config.cache_id:
                if (os.path.realpath(new_cache_config.device)
                        == os.path.realpath(cache.device)):
                    raise cas_config.ConflictingConfigException(
                            'This cache device is already configured as a cache')

            for _, core in cache.cores.items():
                if (os.path.realpath(core.device)
                        == os.path.realpath(new_cache_config.device)):
                    raise cas_config.ConflictingConfigException(
                            'This cache device is already configured as a core')

        try:
            new_cache_config.device = cas_config.get_by_id_path(new_cache_config.device)
        except:
            pass

        self.caches[new_cache_config.cache_id] = new_cache_config

    def insert_core(self, new_core_config):
        if new_core_config.cache_id not in self.caches:
            raise KeyError(f'Cache id {new_core_config.cache_id} doesn\'t exist')

        try:
            for cache_id, cache in self.caches.items():
                if (os.path.realpath(cache.device)
                        == os.path.realpath(new_core_config.device)):
                    raise cas_config.ConflictingConfigException(
                            'Core device already configured as a cache')

                for core_id, core in cache.cores.items():
                    if (cache_id == new_core_config.cache_id
                            and core_id == new_core_config.core_id):
                        if (os.path.realpath(core.device)
                                == os.path.realpath(new_core_config.device)):
                            raise cas_config.AlreadyConfiguredException(
                                    'Core already configured')
                        else:
                            raise cas_config.ConflictingConfigException(
                                    'Other core device configured under this id')
                    else:
                        if (os.path.realpath(core.device)
                                == os.path.realpath(new_core_config.device)):
                            raise cas_config.ConflictingConfigException(
                                    'This core device is already configured as a core')
        except KeyError:
            pass

        try:
            new_core_config.device = cas_config.get_by_id_path(new_core_config.device)
        except:
            pass

        self.caches[new_core_config.cache_id].cores[new_core_config.core_id] = new_core_config
        self.cores += [new_core_config]

    def is_empty(self):
        if len(self.caches) > 0 or len(self.cores) > 0:
            return False

        return True

    def write(self, config_file):
        try:
            with open(config_file, 'w') as conf:
                conf.write(f'{self.version_tag}\n')
                conf.write('# This config was automatically generated\n')

                conf.write('[caches]\n')
                for _, cache in self.caches.items():
                    conf.write(cache.to_line())

                conf.write('\n[cores]\n')
                for core in self.cores:
                    conf.write(core.to_line())
        except:
            raise Exception('Couldn\'t write config file')

# Config helper functions


def start_cache(cache, load, force=False):
    target_state = cache.params.get("target_failover_state")
    if target_state is not None and target_state == "standby":
        casadm.start_standby_cache(
            device=cache.device,
            cache_id=cache.cache_id if not load else None,
            cache_line_size=cache.params.get("cache_line_size") if not load else None,
            load=load,
            force=force
        )
    else:
        casadm.start_cache(
            device=cache.device,
            cache_id=cache.cache_id if not load else None,
            cache_mode=cache.cache_mode if not load else None,
            cache_line_size=cache.params.get('cache_line_size') if not load else None,
            load=load,
            force=force
        )


def configure_cache(cache):
    if "cleaning_policy" in cache.params:
        casadm.set_param(
            "cleaning", cache_id=cache.cache_id, policy=cache.params["cleaning_policy"]
        )
    if "promotion_policy" in cache.params:
        casadm.set_param(
            "promotion", cache_id=cache.cache_id, policy=cache.params["promotion_policy"]
        )
    if "ioclass_file" in cache.params:
        casadm.io_class_load_config(
            cache_id=cache.cache_id, ioclass_file=cache.params["ioclass_file"]
        )


def add_core(core, attach):
    casadm.add_core(
            device=core.device,
            cache_id=core.cache_id,
            core_id=core.core_id,
            try_add=attach)

# Another helper functions


def is_cache_started(cache_config):
    dev_list = get_caches_list()
    for dev in dev_list:
        if dev['type'] == 'cache' and int(dev['id']) == cache_config.cache_id:
            return True

    return False


def is_core_added(core_config):
    dev_list = get_caches_list()
    cache_id = 0
    for dev in dev_list:
        if dev['type'] == 'cache':
            cache_id = int(dev['id'])

        if (dev['type'] == 'core' and
                cache_id == core_config.cache_id and
                int(dev['id']) == core_config.core_id):
            return True

    return False


def get_caches_list():
    result = casadm.list_caches()
    return list(csv.DictReader(result.stdout.split('\n')))


def check_cache_device(device):
    result = casadm.check_cache_device(device)
    return list(csv.DictReader(result.stdout.split('\n')))[0]


def get_cas_version():
    version = casadm.get_version()

    ret = {}
    for line in version.stdout.split('\n')[1:]:
        try:
            component, version = line.split(',')
        except:
            continue
        ret[component] = version

    return ret


class CompoundException(Exception):
    def __init__(self):
        super(CompoundException, self).__init__()
        self.exception_list = list()

    def __str__(self):
        s = "Multiple exceptions occured:\n" if len(self.exception_list) > 1 else ""

        for e in self.exception_list:
            s += f'{str(e)}\n'

        return s

    def add_exception(self, e):
        if type(e) is CompoundException:
            self.exception_list += e.exception_list
        else:
            self.exception_list += [e]

    def is_empty(self):
        return len(self.exception_list) == 0

    def raise_nonempty(self):
        if self.is_empty():
            return
        else:
            raise self


def detach_core_recursive(cache_id, core_id, flush):
    # Catching exceptions is left to uppermost caller of detach_core_recursive
    # as the immediate caller that made a recursive call depends on the callee
    # to remove core and thus release reference to lower level cache volume.
    l_cache_id = ''
    for dev in get_caches_list():
        if dev['type'] == 'cache':
            l_cache_id = dev['id']
        elif dev['type'] == 'core' and dev['status'] == 'Active':
            if f'/dev/cas{cache_id}-{core_id}' in dev['disk']:
                detach_core_recursive(l_cache_id, dev['id'], flush)
        elif l_cache_id == cache_id and dev['id'] == core_id and dev['status'] != 'Active':
            return

    casadm.remove_core(cache_id, core_id, detach=True, force=not flush)


def detach_all_cores(flush):
    error = CompoundException()

    try:
        dev_list = get_caches_list()
    except casadm.CasadmError as e:
        raise Exception(f'Unable to list caches. Reason:\n{e.result.stderr}')
    except:
        raise Exception('Unable to list caches.')

    for dev in dev_list:
        if dev['type'] == 'cache':
            cache_id = dev['id']
        elif dev['type'] == 'core' and dev['status'] == "Active":
            # In case of exception we proceed with detaching remaining core instances
            # to gracefully shutdown as many cache instances as possible.
            try:
                detach_core_recursive(cache_id, dev['id'], flush)
            except casadm.CasadmError as e:
                error.add_exception(Exception(
                    f"Unable to detach core {dev['disk']}. Reason:\n{e.result.stderr}"))
            except:
                error.add_exception(Exception(f"Unable to detach core {dev['disk']}."))

    error.raise_nonempty()


def stop_all_caches(flush):
    error = CompoundException()

    try:
        dev_list = get_caches_list()
    except casadm.CasadmError as e:
        raise Exception(f'Unable to list caches. Reason:\n{e.result.stderr}')
    except:
        raise Exception('Unable to list caches.')

    for dev in dev_list:
        if dev['type'] == 'cache':
            # In case of exception we proceed with stopping subsequent cache instances
            # to gracefully shutdown as many cache instances as possible.
            try:
                casadm.stop_cache(dev['id'], not flush)
            except casadm.CasadmError as e:
                error.add_exception(Exception(
                    f"Unable to stop cache {dev['disk']}. Reason:\n{e.result.stderr}"))
            except:
                error.add_exception(Exception(f"Unable to stop cache {dev['disk']}."))

    error.raise_nonempty()


def stop(flush):
    error = CompoundException()

    try:
        detach_all_cores(flush)
    except Exception as e:
        error.add_exception(e)

    try:
        stop_all_caches(False)
    except Exception as e:
        error.add_exception(e)

    error.raise_nonempty()


def get_devices_state():
    device_list = get_caches_list()

    devices = {"core_pool": {}, "caches": {}, "cores": {}}

    core_pool = False
    prev_cache_id = -1

    for device in device_list:
        if device["type"] == "core pool":
            core_pool = True
            continue

        if device["type"] == "cache":
            core_pool = False
            prev_cache_id = int(device["id"])
            devices["caches"].update(
                {
                    int(device["id"]): {
                        "device": device["disk"],
                        "status": device["status"],
                    }
                }
            )
        elif device["type"] == "core":
            core = {"device": device["disk"], "status": device["status"]}
            if core_pool:
                try:
                    device_path = os.path.realpath(core["device"])
                except ValueError:
                    device_path = core["device"]

                devices["core_pool"].update({device_path: core})
            else:
                core.update({"cache_id": prev_cache_id})
                devices["cores"].update(
                    {(prev_cache_id, int(device["id"])): core}
                )

    return devices


def wait_for_cas_ctrl():
    for i in range(30):  # timeout 30s
        if os.path.exists('/dev/cas_ctrl'):
            return
        time.sleep(1)


def _get_uninitialized_devices(target_dev_state):
    not_initialized = []

    runtime_dev_state = get_devices_state()

    for core in target_dev_state.cores:
        try:
            runtime_state = (
                runtime_dev_state["cores"].get((core.cache_id, core.core_id))
                or runtime_dev_state["core_pool"].get(os.path.realpath(core.device))
            )
        except ValueError:
            runtime_state = None

        if not runtime_state or runtime_state["status"] == "Inactive":
            not_initialized.append(core)

    for cache in target_dev_state.caches.values():
        runtime_state = runtime_dev_state["caches"].get(cache.cache_id)

        if not runtime_state:
            not_initialized.append(cache)

    return not_initialized


def wait_for_startup(timeout=300, interval=5):
    def start_device(dev):
        if os.path.exists(dev.device):
            if type(dev) is cas_config.core_config:
                add_core(dev, try_add=True)
            elif type(dev) is cas_config.cache_config:
                start_cache(dev, load=True)

    stop_time = time.time() + int(timeout)

    try:
        config = cas_config.from_file(
            cas_config.default_location, allow_incomplete=True
        )
    except Exception as e:
        raise Exception(f"Unable to load opencas config. Reason: {str(e)}")

    not_initialized = _get_uninitialized_devices(config)
    if not not_initialized:
        return []

    result = subprocess.run(["udevadm", "settle"])

    for dev in not_initialized:
        start_device(dev)

    while stop_time > time.time():
        not_initialized = _get_uninitialized_devices(config)
        wait = False

        for dev in not_initialized:
            wait = wait or not dev.is_lazy()
            start_device(dev)

        if not wait:
            break

        time.sleep(interval)

    return not_initialized
