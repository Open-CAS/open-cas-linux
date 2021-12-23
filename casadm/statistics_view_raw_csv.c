/*
* Copyright(c) 2012-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
*/

#define _GNU_SOURCE
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "statistics_view.h"
#include "statistics_view_structs.h"
#include "statistics_view_raw_csv.h"

#define VALS_BUFFER_INIT_SIZE 10

int raw_csv_process_row(struct view_t *this, int type, int num_fields, char *fields[])
{
	int i;
	if (RECORD != type && DATA_SET != type) {
		for (i = 0; i < num_fields; i++) {
			if (i) {
				fputc(',', this->outfile);
			}
			if (strstr(fields[i], ",")) {
				fprintf(this->outfile, "\"%s\"", fields[i]);
			} else {
				fprintf(this->outfile, "%s", fields[i]);
			}
		}
		fputc('\n', this->outfile);

	}
	return 0;
}

int raw_csv_end_input(struct view_t *this)
{
	return 0;
}
int raw_csv_construct(struct view_t *this)
{
	return 0;
}

int raw_csv_destruct(struct view_t *this)
{
	return 0;
}

