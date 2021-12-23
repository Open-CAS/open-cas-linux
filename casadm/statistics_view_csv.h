/*
* Copyright(c) 2012-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
*/

#ifndef __STATS_VIEW_CSV
#define __STATS_VIEW_CSV

int csv_process_row(struct view_t *this, int type, int num_fields, char *fields[]);

int csv_end_input(struct view_t *this);

int csv_construct(struct view_t *this);

int csv_destruct(struct view_t *this);


#endif
