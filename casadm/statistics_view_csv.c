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
#include "statistics_view_csv.h"

#define VALS_BUFFER_INIT_SIZE 10

/**
 * private data of CSV output formatter
 */
struct csv_out_prv {
	int data_set; /* current data set number */
	int record; /* current record number */
	int column; /* current column number */
	char **vals;
	char **titles;
	int max_vals;
	int cur_val;
	int max_titles;
	int cur_title;
};

static inline int csv_is_first_record(struct view_t *this)
{
	return 1 == this->ctx.csv_prv->record;
}

static inline int csv_is_unit_string(const char *s)
{
	return NULL != s && '[' == s[0];
}

static void csv_output_column(struct view_t *this, const char *s)
{
	struct csv_out_prv *prv = this->ctx.csv_prv;

	if (prv->column) {
		putc(',', this->outfile);
	}

	if (strstr(s, ",")) {
		fprintf(this->outfile, "\"%s\"", s);
	} else {
		fprintf(this->outfile, "%s", s);
	}
	prv->column++;
}

static char **csv_check_container(char **container, int *max_vals,
					 int cur_val)
{
	if (!container) {
		*max_vals = VALS_BUFFER_INIT_SIZE;
		container = calloc(sizeof(char *), *max_vals);
		if (!container) {
			return NULL;
		}
	}

	/* Resize val pointers array if needed */
	if (*max_vals < cur_val) {
		*max_vals = *max_vals * 2;
		if (*max_vals < cur_val) {
			*max_vals = cur_val;
		}
		container = realloc(container, sizeof(char *) * (*max_vals));
		if (!container) {
			return NULL;
		}
	}

	return container;
}

static int csv_output_data(struct view_t *this, const char *s)
{
	struct csv_out_prv *prv = this->ctx.csv_prv;
	if (csv_is_first_record(this)) {
		prv->vals = csv_check_container(prv->vals, &prv->max_vals,
						prv->cur_val+1);
		if (!prv->vals) {
			return 1;
		}

		/* Store value */
		prv->vals[prv->cur_val] = strdup(s);
		if (!prv->vals[prv->cur_val]) {
			return 1;
		}
		prv->cur_val++;
	} else {
		csv_output_column(this, s);
	}
	return 0;
}

static int csv_add_column_subtitle(struct view_t *this, const char *s)
{
	struct csv_out_prv *prv = this->ctx.csv_prv;

	prv->titles = csv_check_container(prv->titles, &prv->max_titles,
					  prv->cur_title+1);
	if (!prv->titles) {
		return 1;
	}

	/* Store value */
	prv->titles[prv->cur_title] = strdup(s);
	if (!prv->titles[prv->cur_title]) {
		return 1;
	}
	prv->cur_title++;

	return 0;
}

static void csv_output_header(struct view_t *this, const char *title,
				     const char *unit)
{
	static char buff[64];
	if (unit) {
		if (csv_is_unit_string(unit)) {
			snprintf(buff, sizeof(buff), "%s %s", title, unit);
		} else {
			snprintf(buff, sizeof(buff), "%s [%s]", title, unit);
		}
		csv_output_column(this, buff);
	} else {
		csv_output_column(this, title);
	}
}

static void csv_finish_record(struct view_t *this)
{
	struct csv_out_prv *prv = this->ctx.csv_prv;
	int i;

	if (prv->column) {
		putc('\n', this->outfile);
	}

	/*
	 * For first record we need to output stored data values
	 */
	if (csv_is_first_record(this)) {
		prv->column = 0;
		for (i = 0; i < prv->cur_val; ++i) {
			csv_output_column(this, prv->vals[i]);
		}
		if (prv->column) {
			putc('\n', this->outfile);
		}
	}
	fflush(this->outfile);
}

static void csv_free_vals(struct view_t *this)
{
	struct csv_out_prv *prv = this->ctx.csv_prv;
	int i;

	if (prv->vals) {
		for (i = 0; i < prv->cur_val; ++i) {
			free(prv->vals[i]);
		}
		free(prv->vals);
		prv->vals = NULL;
		prv->cur_val = 0;
		prv->max_vals = 0;
	}
}

static void csv_free_titles(struct view_t *this)
{
	struct csv_out_prv *prv = this->ctx.csv_prv;
	int i;

	if (prv->titles) {
		for (i = 0; i < prv->cur_title; ++i) {
			free(prv->titles[i]);
		}
		free(prv->titles);
		prv->titles = NULL;
		prv->cur_title = 0;
		prv->max_titles = 0;
	}
}

int csv_process_row(struct view_t *this, int type, int num_fields, char *fields[])
{
	int i;
	struct csv_out_prv *prv = this->ctx.csv_prv;
	const char *unit = NULL;

	switch (type) {
	case DATA_SET:
		if (prv->record) {
			csv_finish_record(this);
		}
		csv_free_titles(this);
		csv_free_vals(this);
		if (prv->data_set) {
			putc('\n', this->outfile);
		}
		if (num_fields > 0) {
			fprintf(this->outfile, "%s\n", fields[0]);
		}
		prv->record = 0;
		prv->data_set++;
		break;
	case RECORD:
		if (prv->record) {
			csv_finish_record(this);
		}
		prv->column = 0;
		prv->record++;
		break;

	/*
	 * For KV pair assume that values are interleaved
	 * with units, so output every second value,
	 * and use units to construct column headers.
	 * For example:
	 * KV_PAIR,Cache Size,10347970,[4KiB Blocks],39.47,[GiB]
	 * will result in:
	 * data row:   10347970,39.47
	 * header row: Cache Size [4KiB Blocks],Cache Size [GiB]
	 */
	case KV_PAIR:
		for (i = 1; i < num_fields; i += 2) {
			if (csv_is_first_record(this)) {
				if (i + 1 < num_fields) {
					csv_output_header(this, fields[0],
							  fields[i+1]);
				} else {
					csv_output_header(this, fields[0], NULL);
				}
			}
			if (csv_output_data(this, fields[i])) {
				return 1;
			}
		}
		break;

	/*
	 * For table rows assume the following format:
	 * TABLE_{ROW,SECTION},Title,value1,value2,value3,...,unit
	 * This will result in:
	 * data row:   value1,value2,value3,...
	 * header row: Title [unit],Title [col1_title],Title [col2_title],...
	 */
	case TABLE_HEADER:
		csv_free_titles(this);
		csv_add_column_subtitle(this, "");
		for (i = 2; i < num_fields; i++) {
			if (csv_add_column_subtitle(this, fields[i])) {
				return 1;
			}
		}
		break;
	case TABLE_SECTION:
	case TABLE_ROW:
		if (csv_is_first_record(this)) {
			unit = NULL;
			if (csv_is_unit_string(fields[num_fields-1])) {
				unit = fields[num_fields-1];
			}
			csv_output_header(this, fields[0], unit);
			for (i = 2; i < num_fields; i++) {
				if (!csv_is_unit_string(prv->titles[i-1])) {
					csv_output_header(this, fields[0],
							  prv->titles[i-1]);
				}
			}
		}
		for (i = 1; i < num_fields; i++) {
			if (!csv_is_unit_string(prv->titles[i-1])) {
				if (csv_output_data(this, fields[i])) {
					return 1;
				}
			}
		}
		break;
	}
	return 0;
}

int csv_end_input(struct view_t *this)
{
	csv_finish_record(this);
	return 0;
}
int csv_construct(struct view_t *this)
{
	struct csv_out_prv *prv = calloc(sizeof(struct csv_out_prv), 1);

	if (!prv) {
		return 1;
	}
	this->ctx.csv_prv = prv;

	return 0;
}

int csv_destruct(struct view_t *this)
{
	csv_free_vals(this);
	csv_free_titles(this);
	free(this->ctx.csv_prv);
	return 0;
}

