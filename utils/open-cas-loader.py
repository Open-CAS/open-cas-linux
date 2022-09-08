#!/usr/bin/env python3
#
# Copyright(c) 2012-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import subprocess
import opencas
import sys
import os
import syslog as sl

try:
    subprocess.call(['/sbin/modprobe', 'cas_cache'])
except:
    sl.syslog(sl.LOG_ERR, 'Unable to probe cas_cache module')
    exit(1)

try:
    config = opencas.cas_config.from_file('/etc/opencas/opencas.conf',
                                          allow_incomplete=True)
except Exception as e:
    sl.syslog(sl.LOG_ERR, f'Unable to load opencas config. Reason: {str(e)}')
    exit(1)

for cache in config.caches.values():
    if sys.argv[1] == os.path.realpath(cache.device):
        try:
            opencas.wait_for_cas_ctrl()
            opencas.start_cache(cache, True)
        except opencas.casadm.CasadmError as e:
            sl.syslog(sl.LOG_WARNING,
                      f'Unable to load cache {cache.cache_id} ({cache.device}). '
                      f'Reason: {e.result.stderr}')
            exit(e.result.exit_code)
        exit(0)
    for core in cache.cores.values():
        if sys.argv[1] == os.path.realpath(core.device):
            try:
                opencas.wait_for_cas_ctrl()
                opencas.add_core(core, True)
            except opencas.casadm.CasadmError as e:
                sl.syslog(sl.LOG_WARNING,
                          f'Unable to attach core {core.device} from cache {cache.cache_id}. '
                          f'Reason: {e.result.stderr}')
                exit(e.result.exit_code)
            exit(0)
