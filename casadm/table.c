/*
* Copyright(c) 2012-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
*/
#include <stdlib.h>
#include <string.h>
#include <assert.h>
#include "table.h"
#include "safeclib/safe_str_lib.h"
#include <cas_ioctl_codes.h>

#define MIN_STR_SIZE 64

struct table_row
{
	int width;
	int max_width;
	char **cells;
};


struct table
{
	int width;
	int height;
	int max_height;
	struct table_row *r;
};

struct table *table_alloc()
{
	struct table *out = malloc(sizeof(*out));
	if (!out) {
		return NULL;
	}

	out->width = 0;
	out->height = 0;
	out->max_height = 0;

	out->r = 0;
	return out;
}

void table_free(struct table *t)
{
	int i, j;
	if (t->r) {
		for (i = 0 ; i!= t->max_height; ++i) {
			if (t->r[i].cells) {
				for (j = 0 ; j!= t->r[i].max_width; ++j) {
					if (t->r[i].cells[j]) {
						free(t->r[i].cells[j]);
					}
				}
				free(t->r[i].cells);
			}
		}
		free(t->r);
	}
	free(t);
}
int table_reset(struct table *t)
{
	int i,j;
	if (t->r) {
		for (i = 0 ; i!= t->max_height; ++i) {
			if (t->r[i].cells) {
				for (j = 0 ; j!= t->r[i].max_width; ++j) {
					if (t->r[i].cells[j]) {
						(t->r[i].cells[j])[0] = 0;
					}
				}
			}
			t->r[i].width = 0;
		}
	}
	t->width = 0;
	t->height = 0;
	return 0;
}


int maxi(int x, int y)
{
	if (x > y) {
		return x;
	} else {
		return y;
	}
}

char *table_get(struct table *t,int y, int x)
{
	static const char * empty="";
	if (y >= t->height || x >= t->width) {
		assert(0);
		return (char*)empty;
	}

	/* within assigned boundaries but without allocated boundaries */
	if (y >= t->max_height) {
		return (char*)empty;
	}

	if (x >= t->r[y].max_width) {
		return (char*)empty;
	}

	if (!t->r[y].cells) {
		return (char*)empty;
	}

	if (!t->r[y].cells[x]) {
		return (char*)empty;
	}

	return t->r[y].cells[x];
}

int table_set(struct table *t, int y, int x, char *c)
{
	int i;
	int len = strnlen(c, MAX_STR_LEN);
	if (len >= MAX_STR_LEN) {
		return 1;
	}

	/* step 1: ensure that space for row y is allocated */
	if (!t->r) {
		t->r = calloc(sizeof(struct table_row), y + 1);
		if (!t->r) {
			return 1;
		}
		t->max_height = y + 1;
	} else if (t->max_height <= y) {
		struct table_row *tmp;
		int new_m_h = t->max_height*2;
		if (new_m_h <= y) {
			new_m_h = y+1;
		}

		tmp = realloc(t->r, sizeof(struct table_row)*new_m_h);
		if (!tmp) {
			return 1;
		}

		t->r=tmp;
		for (i = t->max_height; i!= new_m_h; ++i) {
			t->r[i].width = t->r[i].max_width = 0;
			t->r[i].cells = 0;
		}
		t->max_height = new_m_h;

	} /* else everything is OK */

	/* step 2: ensure that column x within row y is allocated */
	if (!t->r[y].cells) {
		t->r[y].cells = calloc(sizeof(char*), x + 1);
		t->r[y].max_width = x + 1;
	} else if (t->r[y].max_width <= x) {
		char **tmp;
		int new_m_w = t->r[y].max_width*2;
		if (new_m_w <= x) {
			new_m_w = x+1;
		}

		tmp = realloc(t->r[y].cells, sizeof(char*)*new_m_w);
		if (!tmp) {
			return 1;
		}

		t->r[y].cells = tmp;
		memset(&tmp[t->r[y].max_width], 0,
		       sizeof(char*)*(new_m_w-t->r[y].max_width));
		t->r[y].max_width = new_m_w;
	}

	/* step 3: allocate space for string to be contained in cell */
	if (t->r[y].cells[x] && len+1>MIN_STR_SIZE) {
		char *tmp = realloc(t->r[y].cells[x], len+1);
		if (!tmp) {
			return 1;
		}
		t->r[y].cells[x] = tmp;

	} else if (!t->r[y].cells[x]){
		t->r[y].cells[x] = malloc(maxi(MIN_STR_SIZE,len+1));
		if (!t->r[y].cells[x]) {
			return 1;
		}
	}

	/* step 4: actually overwrite contents of a cell */
	strncpy_s(t->r[y].cells[x], len + 1, c, len);

	/* step 5: update width and height of a table */

	t->height = maxi(t->height, y + 1);
	t->width = maxi(t->width, x + 1);
	t->r[y].width = maxi(t->r[y].width, x + 1);
	return 0;
}

/**
 * get last available row of table that was added either via
 */
int table_get_width(struct table *t)
{
	return t->width;
}

int table_get_height(struct table *t)
{
	return t->height;
}

int table_set_height(struct table *t, int h)
{
	t->height = h;
	return 0;
}


int table_set_width(struct table *t, int h)
{
	t->width = h;
	return 0;
}

