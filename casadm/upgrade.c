/*
* Copyright(c) 2012-2019 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause-Clear
*/
#include <stdlib.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <sys/ioctl.h>
#include "cas_lib.h"
#include "cas_lib_utils.h"
#include <cas_ioctl_codes.h>

extern cas_printf_t cas_printf;

int upgrade_start()
{
	int fd;
	struct kcas_upgrade cmd_info;

	if ((fd = open_ctrl_device()) == -1) {
		return -1;
	}

	if (run_ioctl_interruptible(fd, KCAS_IOCTL_UPGRADE, &cmd_info,
				    "Starting upgrade", 0, OCF_CORE_ID_INVALID) < 0) {
		close(fd);
		if (OCF_ERR_FLUSHING_INTERRUPTED == cmd_info.ext_err_code) {
			return INTERRUPTED;
		} else {
			cas_printf(LOG_ERR, "Error starting upgrade\n");
			print_err(cmd_info.ext_err_code);
			return FAILURE;
		}
	}

	close(fd);
	return SUCCESS;
}
