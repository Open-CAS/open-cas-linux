/*
* Copyright(c) 2012-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
*/

#define _GNU_SOURCE
#include <stdlib.h>
#include <ctype.h>
#include <stdio.h>
#include <stdbool.h>
#include <string.h>
#include <sys/ioctl.h>
#include "vt100codes.h"
#include "csvparse.h"
#include "statistics_view.h"
#include "statistics_view_structs.h"
#include "statistics_view_text.h"
#include "table.h"
#include "intvector.h"
#include <assert.h>
#include <unistd.h>
#include <stdint.h>
#include "safeclib/safe_mem_lib.h"
#include "safeclib/safe_str_lib.h"
#include <cas_ioctl_codes.h>
#include "cas_lib.h"

#define NUMBER_COLOR FG_COLOR_YELLOW
#define UNIT_COLOR FG_COLOR_CYAN
#define PATH_COLOR FG_COLOR_MAGENTA
#define TREE_BRANCH_COLOR FG_COLOR_BLUE

/**
 * table drawing character set
 */
struct table_draw_characters {
	int outer_horiz;	/**< thin horizontal line */
	int outer_right;	/**< T facing right border */
	int outer_left;	/**< T facing left border */
	int outer_vert;	/**< bold vertical line */
	int outer_x;		/**< intersection of bold lines */

	int outer_lt;		/**< Left top corner of a frame */
	int outer_lb;		/**< Left bottom corner of a frame */
	int outer_rt;		/**< Right top corner of a frame */
	int outer_rb;		/**< Right bottom corner of a frame */

	int inner_horiz;	/**< thin horizontal line */
	int inner_right;	/**< T facing right border */
	int inner_left;	/**< T facing right border */
	int inner_top;		/**< T facing top border */
	int inner_bottom;	/**< T facing bottom border */
	int inner_vert;	/**< thin vertical line */
	int inner_x;		/**< intersection of thin lines */

	int tree_node;		/**< tree node (but not last) */
	int tree_node_last;	/**< last tree node */
};

/**
 * private data of text output formatter
 */
struct text_out_prv {
	struct table *t;	/**< currently processed table (freed and reallocated frequently */
	struct intvector col_w; /**< set of column widths */
	struct intvector row_types; /**< set of row types (whenever table rows are headers,
				       sections or regulars */
	struct table_draw_characters tc; /**< set of table draw characters */
	bool dec_fmt; /**< whenever output shall utilize xterm/DEC VT1xx features */
	/**
	 * actual number of columns - may be less than number of
	 * columns in t array, when line breaking is used */
	int num_cols;
	/** size of buffer for reconstructed cell */
	int cell_buffer_size;
	/** buffer for reconstructed cell */
	char *cell_buffer;
	int col_ptr; /**< column pointer for key value printing */
};

int text_construct(struct view_t *this)
{
	struct text_out_prv *prv = calloc(sizeof(struct text_out_prv),1);
	struct table_draw_characters *tc = &prv->tc;
	this->ctx.text_prv = prv;
	if (!prv) {
		return 1;
	}
	prv->t = table_alloc();
	if (!prv->t) {
		return 1;
	}
	if (vector_alloc_placement(&prv->col_w)) {
		table_free(prv->t);
		return 1;
	}
	if (vector_alloc_placement(&prv->row_types)) {
		table_free(prv->t);
		vector_free_placement(&prv->col_w);
		return 1;
	}
	const char *term = getenv("TERM");
	if (term && (!strncmp(term, "xterm", 5) || !strcmp(term, "screen"))) {
		prv->dec_fmt = true;
	} else {
		prv->dec_fmt = false;
	}

	/* use "Lang" to detect if utf8 is about to be used.
	 * additionally use UTF8 frames only for dec_fmt-style terminal (others
	 * typically lack utf8 fonts */
	const char *lang = getenv("LANG");

	if (prv->dec_fmt && lang && strcasestr(lang, "UTF-8")) {
		/*
		 * if you want to add more box drawing characters to this mechanism,
		 * please look up for their UNICODE codes i.e. here:
		 * https://en.wikipedia.org/wiki/Box-drawing_character#Unicode
		 *
		 * (don't enter those sequences in code directly as some editors
		 * badly display them - and vi Emacs are OK, current Eclipse is good
		 * too, but others cause problem. Also external tools don't like
		 * them too much)
		 */
		tc->outer_horiz = 0x2550;
		tc->outer_right = 0x2563; /* T facing right border */
		tc->outer_left = 0x2560;
		tc->outer_vert = 0x2551;
		tc->outer_x = 0x256a;

		tc->outer_lt = 0x2554;
		tc->outer_lb = 0x255a;
		tc->outer_rt = 0x2557;
		tc->outer_rb = 0x255d;

		tc->inner_horiz = 0x2500;
		tc->inner_vert = 0x2502;
		tc->inner_left = 0x255f;
		tc->inner_top = 0x2564;
		tc->inner_bottom = 0x2567;
		tc->inner_right = 0x2562;
		tc->inner_x = 0x253c;

		tc->tree_node = 0x2514;
		tc->tree_node_last = 0x251c;
	} else {
		tc->outer_horiz = '=';
		tc->outer_right = '+'; /* T facing right border */
		tc->outer_left = '+';
		tc->outer_vert = '|';
		tc->outer_x = '+';

		tc->outer_lt = '+';
		tc->outer_lb = '+';
		tc->outer_rt = '+';
		tc->outer_rb = '+';

		tc->inner_horiz = '-';
		tc->inner_vert = '|';
		tc->inner_right = '+'; /* T facing right border */
		tc->inner_left = '+';
		tc->inner_top = '+';
		tc->inner_bottom = '+';
		tc->inner_x = '+';

		tc->tree_node = '+';
		tc->tree_node_last = '+';
	}

	if (!isatty(fileno(this->outfile))) {
		prv->dec_fmt = false; /* if output is NOT a tty, don't use
				       * dec_fmt features */
	}

	const char *casadm_colors = getenv("CASADM_COLORS");
	if (casadm_colors && casadm_colors[0]) {
		prv->dec_fmt = true;
	}

	prv->cell_buffer = 0;
	prv->cell_buffer_size = 0;

	return 0;
}

int text_destruct(struct view_t *this)
{
	struct text_out_prv *prv = this->ctx.text_prv;
	table_free(prv->t);
	vector_free_placement(&prv->col_w);
	vector_free_placement(&prv->row_types);
	if (prv->cell_buffer) {
		free(prv->cell_buffer);
	}
	free(prv);
	return 0;
}

/**
 * utf8-encoding version of putc
 */
void putcu8(int c, FILE *out)
{
	if (c < (1 << 7)) /* 7 bit Unicode encoded as plain ascii */ {
		putc(c, out);
		return;
	}
	if (c < (1 << 11)) /* 11 bit Unicode encoded in 2 UTF-8 bytes */ {
		putc((c >> 6) | 0xC0, out);
		putc((c & 0x3F) | 0x80, out);
		return;
	}
	if (c < (1 << 16)) /* 16 bit Unicode encoded in 3 UTF-8 bytes */ {
		putc(((c >> 12)) | 0xE0, out);
		putc(((c >> 6) & 0x3F) | 0x80, out);
		putc((c & 0x3F) | 0x80, out);
		return;
	}
	if (c < (1 << 21))/* 21 bit Unicode encoded in 4 UTF-8 bytes */ {
		putc(((c >> 18)) | 0xF0, out);
		putc(((c >> 12) & 0x3F) | 0x80, out);
		putc(((c >> 6) & 0x3F) | 0x80, out);
		putc((c & 0x3F) | 0x80, out);
		return;
	}
}

/**
 * Types of table horizontal rule
 */
enum hr_type {
	TOP,
	AFTER_HEADER,
	INTERNAL,
	BOTTOM
};

/**
 * print table horizontal rule.
 * @param this output formatter object
 * @param mode style of horizontal rule to be printed,
 * as per enum hr_type
 */
static int print_table_hr(struct view_t *this, int mode)
{
	struct text_out_prv *prv = this->ctx.text_prv;
	struct table_draw_characters *tc = &prv->tc;
	int i,j;
	int w = prv->num_cols;

	for (j = 0 ; j != w ; ++j) {
		if (0 == j) {
			if (TOP == mode) {
				putcu8(tc->outer_lt, this->outfile);
			} else if (AFTER_HEADER == mode) {
				putcu8(tc->outer_left, this->outfile);
			} else if (INTERNAL == mode) {
				putcu8(tc->inner_left, this->outfile);
			} else {
				putcu8(tc->outer_lb, this->outfile);
			}
		} else {
			if (TOP == mode) {
				putcu8(tc->inner_top, this->outfile);
			} else if (AFTER_HEADER == mode) {
				putcu8(tc->outer_x, this->outfile);
			} else if (INTERNAL == mode) {
				putcu8(tc->inner_x, this->outfile);
			} else {
				putcu8(tc->inner_bottom, this->outfile);
			}
		}
		for (i = 0 ; i != vector_get(&prv->col_w, j) + 2; ++i) {
			if (INTERNAL == mode) {
				putcu8(tc->inner_horiz, this->outfile);
			} else {
				putcu8(tc->outer_horiz, this->outfile);
			}
		}
	}

	if (TOP == mode) {
		putcu8(tc->outer_rt, this->outfile);
	} else if (AFTER_HEADER == mode) {
		putcu8(tc->outer_right, this->outfile);
	} else if (INTERNAL == mode) {
		putcu8(tc->inner_right, this->outfile);
	} else {
		putcu8(tc->outer_rb, this->outfile);
	}
	putc('\n', this->outfile);
	return 0;
}

/**
 * configure formatting attribute, if DEC-style formatting is supported by
 * output terminal. otherwise don't print anything.
 * @param this formatter object
 * @param attr formatting attribute to be set (color, bold etc...)
 * @return 0 when no error happened.
 */
static int conditional_fmt(struct view_t *this, int attr) {
	struct text_out_prv *prv = this->ctx.text_prv;
	if (prv->dec_fmt) {
		if (fprintf(this->outfile, SET_ATTR, attr)) {
			return 0;
		} else {
			return 1;
		}
	} else {
		return 0;
	}
}

/**
 * @brief return true if cell is a decimal number or %. Signed numbers ae NOT
 * recognized.
 */
static bool isnumber(const char *str)
{
	int num_dots = 0;
	const char *c = str;
	do {
		if (isdigit(*c)) {
			continue;
		} else if ('.' == *c) {
			if (num_dots++ || c==str) {
				return false; /* more than one '.' within
						 string, or '.' as a first
						 characterr */
			}
		} else if ('%' == *c) {
			if (c[1] || c==str || c[-1]=='.' ) {
				return false; /* '%' occured and it is not
						 the last character or '%'
						 as a first character */
			}
		} else {
			return false; /* character outside of set [0-9%.] */
		}

	} while (*(++c));
	return true;
}

static void print_spaces(FILE *outfile, int spaces_no)
{
	int i;
	for (i = 0; i < spaces_no; i++) {
		fputc(' ', outfile);
	}
	return;
}

static int calculate_total_width(struct view_t *this)
{
	struct text_out_prv *prv = this->ctx.text_prv;
	int i;
	int w = prv->num_cols;
	int result = 0;
	for (i = 0 ; i != w ; ++i) {
		result += vector_get(&prv->col_w, i);
	}
	return result;
}

static int get_window_width()
{
	struct winsize w;
	if (getenv("CASADM_NO_LINE_BREAK")) {
		return MAX_STR_LEN;
	} else if (ioctl(0, TIOCGWINSZ, &w)) {
		char *cols = getenv("COLUMNS");
		int ncols;
		if (cols && str_to_int(cols, NULL, &ncols)) {
			return ncols;
		} else {
			return 80;
			/* return default width of 80
			   if actual width of screen
			   cannot be determined */
		}
	} else {
		return w.ws_col;
	}
}

/**
 * reconstruct entire cell even if it is splitted into "rows"
 * due to line breaks;
 */
static char* get_entire_cell(struct view_t *this, int i, int j)
{
	struct text_out_prv *prv = this->ctx.text_prv;
	int w = table_get_width(prv->t);
	int k;
	int t;
	int buffer_len = 0;
	/* calculate buffer length required */
	for (k = j % prv->num_cols ; k < w; k += prv->num_cols) {
		char *sub_cell = (char*)table_get(prv->t, i, k);
		buffer_len += strnlen(sub_cell, MAX_STR_LEN);
	}

	/* make sure, that buffer is allocated */
	if (!prv->cell_buffer) {
		prv->cell_buffer = malloc(1 + buffer_len);
		if (!prv->cell_buffer) {
			return 0;
		}
		prv->cell_buffer_size = buffer_len;
	} else if (prv->cell_buffer_size <= buffer_len) {
		char *tmp = realloc(prv->cell_buffer,
				    1 + buffer_len);
		if (tmp) {
			prv->cell_buffer = tmp;
			prv->cell_buffer_size = buffer_len;
		} else {
			return 0;
		}
	}

	/* reconstruct cell */
	t = 0;
	for (k = j % prv->num_cols ; k < w; k += prv->num_cols) {
		char *sub_cell = (char*)table_get(prv->t, i, k);
		int len = strnlen(sub_cell, MAX_STR_LEN);
		if (len) {
			memcpy_s(prv->cell_buffer + t,
				 buffer_len - t,
				 sub_cell, len);
		}
		t += len;
	}

	prv->cell_buffer[buffer_len] = 0;

	return prv->cell_buffer;
}

/**
 * finish printing table (upon last row of table)
 */
static int finish_table(struct view_t *this)
{
	struct text_out_prv *prv = this->ctx.text_prv;
	struct table_draw_characters *tc = &prv->tc;
	int i, j;
	int w = table_get_width(prv->t);
	int h = table_get_height(prv->t);
	int half_space; /* half of space around item (for center-alignment) */
	print_table_hr(this, TOP);
	for (i = 0 ; i!= h ; ++i) {

		for (j = 0 ; j != w ; ++j) {
			char *cell_text = (char*)table_get(prv->t, i, j);
			char *cell = get_entire_cell(this, i, j);
			int cell_len;
			int cell_text_len = strnlen(cell_text, MAX_STR_LEN);
			half_space = 0;

			if (!cell) {
				return FAILURE;
			}

			cell_len = strnlen(cell, MAX_STR_LEN);

			/* 0 == j % means first column */
			if (0 == j % prv->num_cols) {
				putcu8(tc->outer_vert, this->outfile);
			} else {
				putcu8(tc->inner_vert, this->outfile);
			}
			/* digits are right aligned */

			if (isnumber(cell)) {
				print_spaces(this->outfile,
					     vector_get(&prv->col_w,
							j % prv->num_cols) -
					     cell_text_len);
				conditional_fmt(this, NUMBER_COLOR);

				/* highlight first column */
			} else if (0 == j % prv->num_cols) {
				conditional_fmt(this, ATTR_BRIGHT);

				/* handle table headers specially */
			} else if (vector_get(&prv->row_types, i) == TABLE_HEADER) {
				half_space = (vector_get(&prv->col_w, j)
						  - cell_text_len) / 2;

				if ('[' == cell[0] && ']' == cell[cell_len-1]) {
					if (j < prv->num_cols) {
						cell_text += 1;
						cell_text_len --;
					}
					if (cell_text[cell_text_len - 1] == ']') {
						cell_text[cell_len - 2] = 0;
						cell_text_len --;
					}
					cell_len -= 2;
				}
				print_spaces(this->outfile, half_space);
				conditional_fmt(this, ATTR_BRIGHT);

			} else {

				if (cell[0]=='[' && cell[cell_len-1]==']') {
					conditional_fmt(this, UNIT_COLOR);
					if (j < prv->num_cols) {
						cell_text += 1;
						cell_text_len --;
					}
					if (cell_text[cell_text_len - 1] == ']') {
						cell_text[cell_len - 2] = 0;
						cell_text_len --;
					}
				}

			}

			putc(' ', this->outfile);
			if (cell_text_len != fwrite(cell_text, 1, cell_text_len,
						   this->outfile)) {
				abort();
			}
			putc(' ', this->outfile);

			if (!isnumber(cell)) {
				print_spaces(this->outfile,
					     vector_get(&prv->col_w,
							j % prv->num_cols) -
					     cell_text_len - half_space);
			}
			conditional_fmt(this, ATTR_RESET);
			fflush(this->outfile);

			if (j % prv->num_cols
			    == prv->num_cols - 1
				|| j == w - 1) {
				putcu8(tc->outer_vert, this->outfile);
				putc('\n', this->outfile);
				/* additionally check if anything worth printing is
				 * in subsequent lines */

				int k;
				bool nothing_more = true;
				for (k = j + 1; k != w ; ++k) {
					cell = (char*)table_get(prv->t, i, k);
					if (cell[0]) {
						nothing_more = false;
					}
				}
				if (nothing_more) {
					break;
				}
			}
		}

		if (vector_get(&prv->row_types, i) == TABLE_HEADER) {
			print_table_hr(this, AFTER_HEADER);

		} else if (i + 1 < h &&
			   vector_get(&prv->row_types, i+1) == TABLE_SECTION) {
			print_table_hr(this, INTERNAL);

		}

		fflush(this->outfile);
	}
	print_table_hr(this, BOTTOM);
	return 0;
}

/**
 * finish printing table (upon last row of table)
 */
static int finish_tree(struct view_t *this)
{
	struct text_out_prv *prv = this->ctx.text_prv;
	struct table_draw_characters *tc = &prv->tc;
	int i, j;
	int w = table_get_width(prv->t);
	int h = table_get_height(prv->t);
	for (i = 0 ; i!= h ; ++i) {

		for (j = 0 ; j != w ; ++j) {
			char *mother_cell = (char*)table_get(prv->t, i,
							     j % prv->num_cols);
			char *cell = (char*)table_get(prv->t, i, j);
			int cell_len = strnlen(cell, MAX_STR_LEN);
			int out_len = cell_len;

			/* digits are right aligned */
			if (0 == j &&
			    (vector_get(&prv->row_types, i) == TREE_LEAF)) {
				if (h - 1 == i ||
				    (i < h - 1 &&
				     vector_get(&prv->row_types, i + 1)
				     == TREE_BRANCH)) {
					putcu8(tc->tree_node, this->outfile);
				} else {
					putcu8(tc->tree_node_last,
					       this->outfile);
				}
				cell_len++;
			}

			/* apply bright colors for all rows except leaves */
			if (0 == j ||
			    (vector_get(&prv->row_types, i) != TREE_LEAF)) {
				conditional_fmt(this, ATTR_BRIGHT);
			}

			if (3 == j) {
				if (!strncmp(cell, "Active", MAX_STR_LEN) ||
					(!strncmp(cell, "Running", MAX_STR_LEN)) ||
					(!strncmp(cell, "Stopping", MAX_STR_LEN))) {
					conditional_fmt(this, FG_COLOR_GREEN);
				}

				if (!strncmp(cell, "Inactive", MAX_STR_LEN) ||
					!strncmp(cell, "Detached", MAX_STR_LEN)) {
					conditional_fmt(this, FG_COLOR_RED);
					conditional_fmt(this, ATTR_BRIGHT);
				}

				if (!strncmp(cell, "Incomplete", MAX_STR_LEN)) {
					conditional_fmt(this, FG_COLOR_YELLOW);
					conditional_fmt(this, ATTR_BRIGHT);
				}
			}

			if (isnumber(cell)) {
				conditional_fmt(this, NUMBER_COLOR);
			}

			if ('/' == mother_cell[0]) {
				if (vector_get(&prv->row_types, i)
				    == TREE_BRANCH) {
					conditional_fmt(this, TREE_BRANCH_COLOR);
				} else {
					conditional_fmt(this, PATH_COLOR);
				}
			}

			if (out_len != fwrite(cell,
					      1, out_len, this->outfile)) {
				abort();
			}

			/* for column that is NOT last - fill spaces between
			 * columns accordingly */
			if (j % prv->num_cols != prv->num_cols - 1) {
				print_spaces(this->outfile,
					     vector_get(&prv->col_w, j
						     % prv->num_cols) -
					     cell_len + 3);
			}
			conditional_fmt(this, ATTR_RESET);
			fflush(this->outfile);

			/* for last column or last entry in a row */
			if (j % prv->num_cols == prv->num_cols - 1
				|| j == w - 1) {
				putc('\n', this->outfile);
				/* additionally check if anything worth printing is
				 * in subsequent lines */

				int k;
				bool nothing_more = true;
				for (k = j + 1; k != w ; ++k) {
					cell = (char*)table_get(prv->t, i, k);
					if (cell[0]) {
						nothing_more = false;
					}
				}
				if (nothing_more) {
					break;
				}
			}

			/* for last entry in last column (in case of line breaks)  */
			if (j % prv->num_cols == prv->num_cols - 1
				&& j != w - 1) {
				if (i == h - 1) {
					putc(' ', this->outfile);
				} else {
					putcu8(tc->inner_vert,
					       this->outfile);
				}
			}
		}

		fflush(this->outfile);
	}
	return 0;
}



static int print_word_break_lines(struct view_t *this,
				  char *word,
				  int word_len,
				  int screen_width,
				  int *words_in_line)
{
	struct text_out_prv *prv = this->ctx.text_prv;
	if (prv->col_ptr + word_len > screen_width && *words_in_line) {
		putc('\n', this->outfile);
		prv->col_ptr = 1 + vector_get(&prv->col_w, 0);
		print_spaces(this->outfile, prv->col_ptr);
		*words_in_line = 0;
	}
	prv->col_ptr += word_len;
	(*words_in_line)++;
	return word_len != fwrite(word, 1, word_len, this->outfile);
}

static void print_spaces_state(struct view_t *this,
			       int spaces_no,
			       int screen_width)
{
	struct text_out_prv *prv = this->ctx.text_prv;
	int i;

	if (prv->col_ptr + spaces_no > screen_width) {
		putc('\n', this->outfile);
		prv->col_ptr = 1 + vector_get(&prv->col_w, 0);
		print_spaces(this->outfile, prv->col_ptr);
	} else {
		prv->col_ptr += spaces_no;
		for (i = 0; i < spaces_no; i++) {
			fputc(' ', this->outfile);
		}
	}
	return;
}

static int print_cell_break_lines(struct view_t *this,
				  char *cell,
				  int cell_len,
				  int screen_width)
{
	struct text_out_prv *prv = this->ctx.text_prv;
	if (prv->col_ptr + cell_len > screen_width) {
		int off = 0;
		int word_off = 0;
		int words_in_line = 0;
		do {
			if (' ' == cell[word_off + off] ||
			    !cell[word_off + off]) {
				if (off) {
					print_spaces_state(this, 1, screen_width);
				}
				print_word_break_lines(this, cell + off,
						       word_off, screen_width,
						       &words_in_line);
				off += word_off + 1;
				word_off = 0;
			} else {
				word_off ++;
			}
		} while (off + word_off <= cell_len);
		return 0;
	} else {
		prv->col_ptr += cell_len;
		return cell_len != fwrite(cell, 1, cell_len, this->outfile);
	}
}

/**
 * finish KV pairs...
 */
static int finish_kvs(struct view_t *this)
{
	struct text_out_prv *prv = this->ctx.text_prv;
	int i,j;
	int screen_width = get_window_width();

	int w = prv->num_cols;
	int h = table_get_height(prv->t);
	for (i = 0 ; i!= h ; ++i) {
		prv->col_ptr = 0;
		for (j = 0 ; j != w ; ++j) {
			char *cell = table_get(prv->t, i, j);
			int cell_len = strnlen(cell, MAX_STR_LEN);
			if (j && !table_get(prv->t, i, j)[0]) {
				continue; /* don't bother with empty strings */
			}
			if (j == 0) {
				conditional_fmt(this, ATTR_BRIGHT);
			} else if (j==1) {
				print_spaces_state(this,
						   1, screen_width);
			} else if (cell[0] == '[') {
				print_spaces_state(this,
						   1, screen_width);
				conditional_fmt(this, UNIT_COLOR);
			} else {
				print_cell_break_lines(this, " / ", 3,
					screen_width);
			}

			if (isdigit(cell[0]) && (isdigit(cell[cell_len-1])
						|| '%'==cell[cell_len-1])) {
				conditional_fmt(this, NUMBER_COLOR);
			} else if ('/'==cell[0]) {
				conditional_fmt(this, PATH_COLOR);
			}
			if (print_cell_break_lines(this, cell, cell_len,
						   screen_width)) {
				abort();
			}
			if (j == 0) {
				print_spaces_state(this,
						   vector_get(&prv->col_w, 0)
						   - cell_len,
						   screen_width);
			}
			conditional_fmt(this, ATTR_RESET);
			fflush(this->outfile);
		}
		putc('\n', this->outfile);
		fflush(this->outfile);
	}
	return 0;
}


static void set_column_widths(struct view_t *this)
{
	struct text_out_prv *prv = this->ctx.text_prv;
	int i, j;
	int w = table_get_width(prv->t);
	int h = table_get_height(prv->t);

	vector_resize(&prv->col_w, w);
	vector_zero(&prv->col_w);
	for (i = 0 ; i!= h ; ++i) {
		for (j = 0 ; j != w ; ++j) {
			const char *cell = table_get(prv->t, i, j);
			int cell_len = strnlen(cell, MAX_STR_LEN);
			if (cell[0]=='[' && cell[cell_len-1]==']') {
				cell_len -= 2;
			}
			vector_set(&prv->col_w, j % prv->num_cols,
				   maxi(vector_get(&prv->col_w, j % prv->num_cols),
					cell_len));
		}
	}
}

/* if sum of column widths is less than width of a screen,
 * attempt to shrink some
 * @param tbl_margin space between left edge and start of cell 0 text
 * @param cell_margin space between cells;
 */
static int adjust_column_widths(struct view_t *this,
				 int cell_margin, int tbl_margin) {
	struct text_out_prv *prv = this->ctx.text_prv;
	int i, j;
	int w = prv->num_cols;
	int h = table_get_height(prv->t);
	int screen_width = get_window_width();
	int table_width;
	int margins_width = (w - 1) * cell_margin + tbl_margin * 2;
	int avg_width;
	int above_avg_cols = 0;
	int excess_width;
	if (screen_width < 0) {
		return 0;
	}

	table_width = calculate_total_width(this);
	if (table_width + margins_width <= screen_width) {
		return 0;
	}
	/* perform magic to adjust table to a screen */
	avg_width = table_width / w;
	excess_width = table_width + margins_width - screen_width;
	for (i = 0 ; i != w ; ++i) {
		if (vector_get(&prv->col_w, i) > avg_width) {
			above_avg_cols ++;
		}
	}

	for (i = 0 ; i != w ; ++i) {
		int this_width = vector_get(&prv->col_w, i);
		/*
		 * This condition is exactly the same as in above loop, where
		 * above_avg_cols is incremented. So there is no risk of division by 0.
		 */
		if (this_width > avg_width) {
			int reduce_by = excess_width / above_avg_cols;
			vector_set(&prv->col_w, i, this_width - reduce_by);
			above_avg_cols --;
			excess_width -= reduce_by;
		}
	}

	/* proper widths set */
	/* now proceed with line breaking */
	for (i = 0 ; i!= h ; ++i) {
		for (j = 0 ; j != w ; ++j) {
			char *field = (char*)table_get(prv->t, i, j);
			int k;
			int col_w = vector_get(&prv->col_w, j);
			int strlen_f = strnlen(field, MAX_STR_LEN);
			int last_breakpoint = 0;
			int num_breakpoints = 0;
			int breakpoint = 0; /* offset at which line is broken */
			for (k = 0; k != strlen_f ; ++k) {
				if (field[k] == '/' ||
					field[k] == ' ' ||
					field[k] == '-') {
					breakpoint = k;
				}
				if (k - last_breakpoint >= col_w
				    && breakpoint > last_breakpoint) {
					if (k < strlen_f && breakpoint &&
					    table_set(prv->t, i,
						      j + w *
						      (1 + num_breakpoints),
						      field + breakpoint)) {
						return 1;
					}
					field[breakpoint] = 0;
					if (last_breakpoint) {
						((char*)table_get(prv->t, i,
								  j + w * num_breakpoints))
							[breakpoint - last_breakpoint] = 0;
					}
					last_breakpoint = breakpoint;
					num_breakpoints ++;
				}

			}
		}
	}

	table_set_width(prv->t, ((table_get_width(prv->t) + w - 1) / w ) * w);
	set_column_widths(this);
	return 0;
}

static int finish_structured_data(struct view_t *this) {
	struct text_out_prv *prv = this->ctx.text_prv;
	int w = table_get_width(prv->t);
	prv->num_cols = w;
	set_column_widths(this);

	if (vector_get(&prv->row_types, 0) == KV_PAIR) {
		finish_kvs(this);
	} else if (vector_get(&prv->row_types, 0) == TABLE_HEADER) {
		adjust_column_widths(this, 3, 4);
		finish_table(this);
	} else if (vector_get(&prv->row_types, 0) == TREE_HEADER) {
		adjust_column_widths(this, 3, 0);
		finish_tree(this);
	}

	table_reset(prv->t);
	vector_resize(&prv->row_types, 0);
	return 0;
}

/**
 * handle single line of text in intermediate format. (already split&parsed).
 * params as per interface.
 */
int text_process_row(struct view_t *this, int type, int num_fields, char *fields[])
{
	int i;
	struct text_out_prv *prv = this->ctx.text_prv;
	int table_h = table_get_height(prv->t);

	switch (type) {
	case FREEFORM:
		if (table_h) {
			finish_structured_data(this);
		}

		conditional_fmt(this, ATTR_BRIGHT);
		for (i = 0; i!= num_fields; ++i) {
			fprintf(this->outfile, "%s", fields[i]);
			fflush(this->outfile);
		}
		conditional_fmt(this, ATTR_RESET);
		putc('\n', this->outfile);
		break;
	case DATA_SET:
	case RECORD:
		if (table_h) {
			finish_structured_data(this);
			if (table_h) {
				putc('\n', this->outfile);
			}
			table_h = 0;
		}
		break;
	default:
		if (table_h && (TABLE_HEADER == type ||
				(vector_get(&prv->row_types, 0) == KV_PAIR
				 && type != KV_PAIR))) {
			finish_structured_data(this);
			table_h = 0;
			putc('\n', this->outfile);
		}

		for (i = 0; i!= num_fields; ++i) {
			if (table_set(prv->t, table_h, i, fields[i])) {
				return 1;
			}
		}
		vector_push_back(&prv->row_types, type);
		break;
	}

	return 0;
}

/**
 * @handles closing file.
 */
int text_end_input(struct view_t *this)
{
	struct text_out_prv *prv = this->ctx.text_prv;
	int table_h = table_get_height(prv->t);
	if (table_h) {
		finish_structured_data(this);
	}
	return 0;
}
