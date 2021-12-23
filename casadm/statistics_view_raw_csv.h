/*
* Copyright(c) 2012-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
*/

#ifndef __STATS_VIEW_RAW_CSV
#define __STATS_VIEW_RAW_CSV

int raw_csv_process_row(struct view_t *this, int type, int num_fields, char *fields[]);

int raw_csv_end_input(struct view_t *this);

int raw_csv_construct(struct view_t *this);

int raw_csv_destruct(struct view_t *this);


#endif
