/*
* Copyright(c) 2012-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
*/

#include <stdlib.h>
#include <stdio.h>
#include "cas_lib.h"
#include "csvparse.h"
#include "string.h"
#include "statistics_view.h"
#include "statistics_view_structs.h"
#include "statistics_view_text.h"
#include "statistics_view_csv.h"
#include "statistics_view_raw_csv.h"

static struct view_t *construct_view(int format, FILE *outfile)
{
	struct view_t *out = calloc(1, sizeof(*out));
	if (!out) {
		return NULL;
	}

	switch (format) {
	case CSV:
		out->process_row = csv_process_row;
		out->end_input = csv_end_input;
		out->construct = csv_construct;
		out->destruct = csv_destruct;
		break;
	case RAW_CSV:
		out->process_row = raw_csv_process_row;
		out->end_input = raw_csv_end_input;
		out->construct = raw_csv_construct;
		out->destruct = raw_csv_destruct;
		break;
	case TEXT:
		out->process_row = text_process_row;
		out->end_input = text_end_input;
		out->construct = text_construct;
		out->destruct = text_destruct;
		break;
	}
	out->outfile = outfile;
	out->construct(out);
	return out;
};

void destruct_view(struct view_t* v)
{
	v->destruct(v);
	free(v);
}

#define RECOGNIZE_TYPE(t) if (!strcmp(cols[0], TAG_NAME(t))) {type = t;}

int stat_print_intermediate(FILE *infile, FILE *outfile)
{
	char buf[MAX_STR_LEN] = { 0 };
	while (fgets(buf, MAX_STR_LEN, infile)) {
		fprintf(outfile, "%s", buf);
	}

	return 0;
}
int stat_format_output(FILE *infile, FILE *outfile, int format)
{
	int result = 0;
	if (format == PLAIN) {
		return stat_print_intermediate(infile, outfile);
	}
	struct view_t *view = construct_view(format, outfile);
	if (!view) {
		cas_printf(LOG_ERR, "Failed to allocate memory for output generator\n");
		return 1;
	}
	CSVFILE *cf = csv_fopen(infile);
	if (!cf) {
		cas_printf(LOG_ERR, "Failed to allocate memory for CSV parser\n");
		destruct_view(view);
		return 1;
	}

	while (!csv_read(cf)) {
		int num_cols = csv_count_cols(cf);
		char **cols = csv_get_col_ptr(cf);
		int type = UNDEFINED_TAG;
		if (num_cols<1) {
			continue;
		}
		RECOGNIZE_TYPE(FREEFORM);
		RECOGNIZE_TYPE(KV_PAIR);
		RECOGNIZE_TYPE(TABLE_ROW);
		RECOGNIZE_TYPE(TABLE_HEADER);
		RECOGNIZE_TYPE(TABLE_SECTION);
		RECOGNIZE_TYPE(TREE_HEADER);
		RECOGNIZE_TYPE(TREE_BRANCH);
		RECOGNIZE_TYPE(TREE_LEAF);
		RECOGNIZE_TYPE(RECORD);
		RECOGNIZE_TYPE(DATA_SET);
		if (type == UNDEFINED_TAG) {
			cas_printf(LOG_ERR, "Unrecognized tag: %s\n", cols[0]);
			result = 1;
			break;
		}
		if (view->process_row(view, type, num_cols-1, cols+1)) {
			cas_printf(LOG_ERR, "Failed to process row starting with: %s\n", cols[0]);
			result = 1;
			break;
		}
	}
	view->end_input(view);

	csv_close_nu(cf);
	destruct_view(view);
	return result;
}
