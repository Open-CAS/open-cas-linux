/*
* Copyright(c) 2012-2020 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause-Clear
*/

#ifndef __VOL_ATOMIC_DEV_BOTTOM_H__
#define __VOL_ATOMIC_DEV_BOTTOM_H__

#include "../cas_cache.h"

enum atomic_metadata_mode {
	ATOMIC_METADATA_MODE_ELBA,
	ATOMIC_METADATA_MODE_SEPBUF,
	ATOMIC_METADATA_MODE_NONE,
};

struct atomic_dev_params {
	unsigned int nsid;
	uint64_t size;
	enum atomic_metadata_mode metadata_mode;
	unsigned is_mode_optimal : 1;

	/* IMPORTANT: If this field is 0, the other fields are invalid! */
	unsigned is_atomic_capable : 1;
};

int atomic_dev_init(void);

#endif /* __VOL_ATOMIC_DEV_BOTTOM_H__ */
