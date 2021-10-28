/*
* Copyright(c) 2012-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
*/


#ifndef __TABLE_H
#define __TABLE_H

struct table;

/**
 * setup "table" structure.
 */
struct table *table_alloc();

/**
 * deallocate table.
 */
void table_free(struct table *t);

/**
 * max value of two integers
 */
int maxi(int x, int y);

/**
 * retrieve a field of a table
 */
char *table_get(struct table *t,int y, int x);

int table_set(struct table *t, int y, int x, char *c);

/**
 * reduce number of columns and rows to 0;
 */
int table_reset(struct table *t);

/**
 * get last available column of table that was added via table_set
 */
int table_get_width(struct table *t);

/**
 * get last available row of table that was added either via table_set or table_set_height
 */
int table_get_height(struct table *t);

/**
 * set height of a table (additional rows will contain empty strings
 */
int table_set_height(struct table *t, int h);
/**
 * set with of a table (additional rows will contain empty strings
 */
int table_set_width(struct table *t, int h);

#endif
