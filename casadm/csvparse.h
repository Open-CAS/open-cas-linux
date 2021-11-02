/*
* Copyright(c) 2012-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
*/

#ifndef __CSVPARSE_H_
#define __CSVPARSE_H_
#include <stdio.h>
/**
 * @file
 * @brief Generic CSV input/output library
 *
 */

/**
 * data structure holding info about CSV file being read.
 * @note there is no need to directly manipulate any field of this structure.
 * Csvparse library handles everything.
 */
struct CSVFILE_t;

/**
 * This is to mimic semantics of stdio FILE*, which also is a typedef for a structure.
 */
typedef struct CSVFILE_t CSVFILE;


CSVFILE *csv_open(const char *path, const char *mode);

CSVFILE *csv_fopen(FILE *f);
CSVFILE *csv_fdopen(int fd);


/**
 * close csv file. this is a direct counterpart to csv_open
 */
void csv_close(CSVFILE *cf);

/**
 * close a csv without closing underlying plain fle object (so that all
 * structures allocated by csv parsere are freed but syscall close(2) isn't issued
 * - this is designed as counterpart to csv_fopen or csv_fdopen
 */
void csv_close_nu(CSVFILE *cf);

/**
 * @param cf csv file handle to read
 *
 * Read line from CSV file; return 0 if line was successfully read
 * return nonzero if eof or error was observed
 * Error may mean end of file or i.e. memory allocation error for temporary buffers
 */
int csv_read(CSVFILE *cf);

/**
 * @return true if end of file occured.
 */
int csv_feof(CSVFILE *cf);

/**
 * return number of columns
 * @return # of columns in a csv file
 */
unsigned int csv_count_cols(CSVFILE *line);

/**
 * return given column of recently read row
 * @param coln - column number
 * @return pointer to field of csv file as a string; no range checking is performed,
 * so if coln given exceeds actual number of columns defined in this row, error will occur
 */
char* csv_get_col(CSVFILE *cf, int coln);

/**
 * return entire row as a set of pointers to individual columns (unchecked function
 * returns internal representation. state is guaranteed to be correct only when
 * csv_read returned success;
 */
char** csv_get_col_ptr(CSVFILE *cf);

/**
 * Check if current line is empty
 *
 * @param cf - CVS file instance
 * @retval 1 - empty line
 * @retval 0 - no empty line
 */
int csv_empty_line(CSVFILE *cf);

/**
 * Seek to the begining of CSV file; this allows reading file again, from the begining
 */
void csv_seek_beg(CSVFILE *cf);

/**
 * This function prints CVS file in human readable format to the STD output
 *
 * @param path - Path to the CVS file
 * @return Operation status. 0 - Success, otherwise error during printing
 */
int csv_print(const char *path);

#endif
