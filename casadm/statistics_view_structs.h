/*
* Copyright(c) 2012-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
*/

#ifndef __STATS_VIEW_S_H
#define __STATS_VIEW_S_H

struct csv_out_prv;

struct text_out_prv;

struct view_t
{
	FILE *outfile;
	union {
		struct csv_out_prv *csv_prv;
		struct text_out_prv *text_prv;
	} ctx;
	/* type specific init */
	int (*construct)(struct view_t *this);
	int (*process_row)(struct view_t *this, int type, int num_fields, char *fields[]);
	int (*end_input)(struct view_t *this);
	int (*destruct)(struct view_t *this);
};


#endif

