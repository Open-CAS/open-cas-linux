/*
* Copyright(c) 2012-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
*/

#include <stdio.h>
#include <stdlib.h>
#include <assert.h>
#include <stdbool.h>
#include <string.h>
#include <ctype.h>
#include <stdint.h>
#include "csvparse.h"
#include "cas_lib_utils.h"
#include "safeclib/safe_lib.h"
#include <cas_ioctl_codes.h>

#define SUCCESS 0
#define FAILURE 1

struct CSVFILE_t {
	FILE *f; /**< underlying byte stream*/
	int num_columns; /**< number of columns in recently read
			    line of CSV file */
	int alloc_column_ptrs; /**< number of pointers to columns
				  that can be fit in columns buffer */
	char **columns;	/**< buffer contains exactly one pointer to each
			   column of a csv file */
	char *buffer; /**< buffer to which recently read line of a csv file
			 is stored */
	int buffer_size; /**< size of a buffer */

	char csv_comment; /**< character markng whole line comment. if set to null,
			     comments in file are not respected */
	char csv_separator; /**< csv separator (by default coma, but in some csv formats
			       it is something different */
};

#define DEF_ALLOC_COL_PTRS 2
#define DEF_CSV_FILE_BUFFER_SIZE 20

/* return error when input dataset size exceeds some common sense limitations */
#define MAX_NUM_COLUMNS 100
#define MAX_LINE_LENGTH 8192

CSVFILE *csv_open(const char *path, const char *mode)
{
	CSVFILE *csv;

	if (!path || !mode) {
		return NULL;
	}

	/* open underlying file as a character stream */
	FILE *f = fopen(path, mode);
	if (!f) {
		return NULL;
	}

	csv = csv_fopen(f);
	if (NULL == csv) {
		fclose(f);
		return NULL;
	}

	return csv;
}

CSVFILE *csv_fopen(FILE *f)
{
	CSVFILE *cf = malloc(sizeof(*cf));
	if (!cf) {
		return NULL;
	}
	/* allocate storage for columns of CSV file */
	cf->num_columns = 0;
	cf->alloc_column_ptrs = DEF_ALLOC_COL_PTRS;

	cf->columns = malloc(cf->alloc_column_ptrs * sizeof(char *));
	if (!cf->columns) {
		free(cf);
		return NULL;
	}

	/* allocate storage for line of CSV file */
	cf->buffer_size = DEF_CSV_FILE_BUFFER_SIZE;
	cf->buffer = malloc(cf->buffer_size);
	if (!cf->buffer) {
		free(cf->columns);
		free(cf);
		return NULL;
	}

	/* assign underlying file as a character stream */
	cf->f = f;

	cf->csv_separator = ',';
	cf->csv_comment = 0;

	return cf;
}

void csv_close(CSVFILE *cf)
{
	fclose(cf->f);
	csv_close_nu(cf);
}

void csv_close_nu(CSVFILE *cf)
{
	free(cf->columns);
	free(cf->buffer);
	memset(cf, 0, sizeof(*cf));
	free(cf);
}

/**
 * internal helper function for the library.
 */
static int ensure_items_array(CSVFILE *cf)
{
	if (cf->num_columns > MAX_NUM_COLUMNS) {
		return FAILURE;
	} else if (cf->num_columns < cf->alloc_column_ptrs) {
		return SUCCESS;
	} else {
		char **tmp;
		cf->alloc_column_ptrs = cf->num_columns * 2;
		tmp =
		    realloc(cf->columns,
			    cf->alloc_column_ptrs * sizeof(char *));
		if (!tmp) {
			return FAILURE;
		} else {
			cf->columns = tmp;
			return SUCCESS;
		}
	}
}

/**
 * Function checks if CSV file is a valid one.
 */
bool csv_is_valid(CSVFILE *cf)
{
	if (!cf) {
		return false;
	} else if (!cf->f) {
		return false;
	} else if (!cf->columns) {
		return false;
	} else if (!cf->buffer) {
		return false;
	} else {
		return true;
	}
}

static int csv_read_line(CSVFILE *cf)
{
	char *line;
	char *c;
	int i, len;
	int already_read = 0;
	/* fgets reads at most buffer_size-1 characters and always places NULL
	 * at the end. */

	while (true) {
		line = fgets(cf->buffer + already_read,
			     cf->buffer_size - already_read, cf->f);
		if (!line) {
			return FAILURE;
		}
		line = cf->buffer;
		/* check that entire line was read; if failed, expand buffer and retry
		 * or (in case of eof) be happy with what we have */
		c = line;
		i = 0;

		while (*c && *c != '\n') {
			c++;
			i++;
		}
		len = i;
		if (len > MAX_LINE_LENGTH) {
			return FAILURE;
		}

		/* buffer ends with 0 while it is not an EOF - sign that we have NOT read entire line
		 * - try to expand buffer*/
		if (!*c && !feof(cf->f)) {
			already_read = cf->buffer_size - 1;
			cf->buffer_size *= 2;
			char *tmp = realloc(cf->buffer, cf->buffer_size);

			if (tmp) {
				cf->buffer = tmp;
				continue;
			} else {
				return FAILURE;
			}
		}

		if (cf->buffer[i] == '\n') {
			cf->buffer[i] = 0;
		}
		break;
	}
	return SUCCESS;
}

int csv_read(CSVFILE *cf)
{
	int i, j, spaces_at_end;
	bool parsing_token = false;	/* if false, "cursor" is over whitespace, otherwise
					 * it is over part of token */

	bool quotation = false;
	if (!csv_is_valid(cf)) {
		return FAILURE;
	}
	if (csv_read_line(cf)) {
		return FAILURE;
	}

	i = 0;
	cf->num_columns = 0;
	cf->columns[0] = 0;
	spaces_at_end = 0;

	while (cf->buffer[i]) {
		if (quotation) {	/* handling text within quotation marks -
					 * ignore commas in this kind of text and don't strip spaces */
			if (cf->buffer[i] == '"' && cf->buffer[i + 1] == '"') {
				/* double quotation mark is considered escaped quotation by
				 * Micros~1 Excel. We should do likewise */
				if (!parsing_token) {	/* start of an cf->buffer */
					cf->columns[cf->num_columns] =
					    &cf->buffer[i];
					parsing_token = true;
				}
				++i;
				memmove_s(cf->columns[cf->num_columns] + 1,
					cf->buffer_size - (cf->columns[cf->num_columns] - cf->buffer),
					cf->columns[cf->num_columns],
					&cf->buffer[i] - cf->columns[cf->num_columns]);
				cf->columns[cf->num_columns]++;
			} else if (cf->buffer[i] == '"') {
				quotation = false;
				parsing_token = false;
				cf->buffer[i] = 0;
			} else if (!parsing_token) {	/* start of an cf->buffer */
				cf->columns[cf->num_columns] = &cf->buffer[i];
				parsing_token = true;
			}
		} else {	/* handling text outside quotation mark */
			if (cf->buffer[i] == cf->csv_separator) {
				(cf->num_columns)++;
				if (ensure_items_array(cf)) {
					return FAILURE;
				}
				cf->columns[cf->num_columns] = 0;
				parsing_token = false;
				cf->buffer[i] = 0;
				for (j = i - spaces_at_end; j != i; ++j) {
					cf->buffer[j] = 0;
				}

			} else if (cf->buffer[i] == '"') {
				quotation = true;
				spaces_at_end = 0;
			} else if (cf->csv_comment
				   && cf->buffer[i] == cf->csv_comment) {
				cf->buffer[i] = 0;
				break;
			} else if (!isspace(cf->buffer[i])) {
				if (!parsing_token) {	/* start of an cf->buffer */
					if (!cf->columns[cf->num_columns]) {
						cf->columns[cf->num_columns] =
						    &cf->buffer[i];
					}
					parsing_token = true;
				}
				spaces_at_end = 0;
			} else {	/* no token.; clear spaces, possibly */
				parsing_token = false;
				spaces_at_end++;
			}
		}
		++i;
	}

	for (j = i - spaces_at_end; j != i; ++j) {
		cf->buffer[j] = 0;
	}

	/*always consider empty line to have exactly one empty column */
	cf->num_columns++;

	for (j = 0; j != cf->num_columns; ++j) {
		/* if no columns were detected during parse, make sure that columns[x]
		 * points to an empty string and not into (NULL) */
		if (!cf->columns[j]) {	/* so that empty columns will return empty string and
					   not a null-pointer */
			cf->columns[j] = &cf->buffer[i];
		}
	}

	return SUCCESS;
}

unsigned int csv_count_cols(CSVFILE *line)
{
	return line->num_columns;
}

int csv_empty_line(CSVFILE *cf)
{
	if (!csv_is_valid(cf)) {
		return FAILURE;
	}
	if (0 == csv_count_cols(cf)) {
		return 1;
	} else if (1 == csv_count_cols(cf)) {
		const char *value = csv_get_col(cf, 0);
		if (strempty(value)) {
			return 1;
		}
	}

	return 0;
}

char *csv_get_col(CSVFILE *cf, int coln)
{
	if (!csv_is_valid(cf)) {
		return NULL;
	}
	return cf->columns[coln];
}

char **csv_get_col_ptr(CSVFILE *cf)
{
	return cf->columns;
}

void csv_seek_beg(CSVFILE *cf)
{
	fseek(cf->f, 0, SEEK_SET);
}

int csv_feof(CSVFILE *cf)
{
	return feof(cf->f);
}

int csv_print(const char *path)
{
	int i, j, k; /* column, line, row, within column */
	int num_col_lengths = DEF_ALLOC_COL_PTRS;
	static const int def_col_len = 5;
	int actual_num_cols = 1;

	CSVFILE *cf = csv_open(path, "r");
	if (!cf) {
		return FAILURE;
	}

	int *col_lengths = malloc(num_col_lengths * sizeof(int));
	if (!col_lengths) {
		csv_close(cf);
		return FAILURE;
	}

	for (i = 0; i != num_col_lengths; ++i) {
		col_lengths[i] = def_col_len;
	}

	/*calculate length of each column */
	i = j = 0;
	while (!csv_read(cf)) {
		int num_cols = csv_count_cols(cf);
		if (num_cols > actual_num_cols) {
			actual_num_cols = num_cols;
		}

		if (num_cols > num_col_lengths) {
			/* CSV file happens to have more columns, than we have allocated
			 * memory for */
			int *tmp =
			    realloc(col_lengths, num_cols * 2 * sizeof(int));
			if (!tmp) {
				free(col_lengths);
				csv_close(cf);
				return FAILURE;
			}
			/* reallocation successful */
			col_lengths = tmp;
			for (i = num_col_lengths; i != num_cols * 2; ++i) {
				col_lengths[i] = def_col_len;
			}
			num_col_lengths = num_cols * 2;
		}

		for (i = 0; i != csv_count_cols(cf); ++i) {
			int len = strnlen(csv_get_col(cf, i), MAX_STR_LEN);
			if (col_lengths[i] < len) {
				col_lengths[i] = len;
			}
		}
		++j;
	}

	/*actually format pretty table */
	csv_seek_beg(cf);
	printf("     | ");

	for (i = 0; i != actual_num_cols; ++i) {
		int before = col_lengths[i] / 2;

		for (k = 0; k != before; ++k) {
			putchar(' ');
		}
		putchar(i + 'A');
		for (k = 0; k != col_lengths[i] - before - 1; ++k) {
			putchar(' ');
		}
		printf(" | ");
	}
	printf("\n-----|-");

	for (i = 0; i != actual_num_cols; ++i) {
		for (k = 0; k != col_lengths[i]; ++k) {
			putchar('-');
		}
		printf("-|-");
	}
	printf("\n");

	j = 1;
	while (!csv_read(cf)) {
		printf("%4d | ", j);
		int num_cols = csv_count_cols(cf);
		for (i = 0; i != actual_num_cols; ++i) {
			if (i < num_cols) {
				char *c = csv_get_col(cf, i);
				for (k = 0; c[k]; k++) {
					putchar(c[k]);
				}
			} else {
				k = 0;
			}
			for (; k != col_lengths[i]; ++k) {
				putchar(' ');
			}
			printf(" | ");
		}
		++j;
		putchar('\n');
	}

	free(col_lengths);
	csv_close(cf);
	return SUCCESS;
}

#ifdef __CSV_SAMPLE__
/**
 * usage example for csvparse library
 * gcc -ggdb csvparse.c -I../common -D__CSV_SAMPLE__ -ocsvsample
 */
int main()
{
	puts("Validated configurations to run Intel CAS");
	csv_print("../../tools/build_installer/utils/validated_configurations.csv");
	putchar('\n');

	puts("IO Classes for Intel CAS");
	csv_print("../../tools/build_installer/utils/default_ioclasses.csv");
	putchar('\n');

}
#endif
