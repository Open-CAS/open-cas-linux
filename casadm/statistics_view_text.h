/*
* Copyright(c) 2012-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
*/

#ifndef __STATS_VIEW_TEXT
#define __STATS_VIEW_TEXT

int text_process_row(struct view_t *this, int type, int num_fields, char *fields[]);

int text_end_input(struct view_t *this);

int text_construct(struct view_t *this);

int text_destruct(struct view_t *this);


#endif
