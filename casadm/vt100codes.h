/*
* Copyright(c) 2012-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
*/

/* General setup */
#define               RESET_DEVICE "\033c"
//! enable line wrapping
#define           ENABLE_LINE_WRAP "\x1b[7h"
//! disable it
#define          DISABLE_LINE_WRAP "\x1b[7l"

/* Scrolling options. Note: there is no way to disable scrolling */
//! Whole screen is scrolled on SCROLL_UP/SCROLL_DOWN
#define       SCROLL_ENTIRE_SCREEN "\x1b[r"
//! Only rows from A to B are scrolled on  SCROLL_UP/SCROLL_DOWN, anything above A or below B is not scrolled
#define  SCROLL_SCREEN_REGION(A,B) "\x1b["  (A)   ";"   (B)   "r"

//! scroll up
#define                  SCROLL_UP "\x1b[M"
//! scroll down
#define                SCROLL_DOWN "\x1b[D"

//! make cursor invisible - xterm
#define                HIDE_CURSOR "\x1b[?25l"

//! restore it -xterm
#define                SHOW_CURSOR "\x1b[?25h"

/* Absolute cursor positioning. */
//! Set cursor position  to left-top position
#define                CURSOR_HOME "\x1b[H"
//! Set cursor position to specific y/x (note: y = 1..height, x = 1..width)
#define             CURSOR_YX "\x1b[%d;%dH"
/* Relative cursor positioning. */
//! move cursor one position up
#define                  CURSOR_UP "\x1b[A"
//! move cursor n positions up
#define              CURSOR_UP_N "\x1b[%dA"
//! move cursor one position down
#define                CURSOR_DOWN "\x1b[B"
//! move cursor n positions down
#define            CURSOR_DOWN_N "\x1b[%dB"
//! move cursor one position forward
#define             CURSOR_FORWARD "\x1b[C"
//! move cursor n positions forward
#define         CURSOR_FORWARD_N "\x1b[%dC"
//! move cursor one position backward
#define            CURSOR_BACKWARD "\x1b[D"
//! move cursor n positions backward
#define        CURSOR_BACKWARD_N "\x1b[%dD"
/* Unsave restores position after last save. */
//! One cursor position may be saved
#define                SAVE_CURSOR "\x1b[s"
//! and restored
#define              UNSAVE_CURSOR "\x1b[u"

/* Erase screen. */
//! Erase whole screen
#define                      ERASE "\x1b[2J"
//! same as above
#define               ERASE_SCREEN ERASE
//! erase above cursor
#define                   ERASE_UP "\x1b[1J"
//! erase below cursor
#define                 ERASE_DOWN "\x1b[J"


#define                INSERT_MODE  "\x1b[4h"
#define               REPLACE_MODE  "\x1b[4l"
/* Erase line. */
//! erase current line
#define                 ERASE_LINE "\x1b[K"
//! erase current line left from the cursor
#define        ERASE_START_OF_LINE "\x1b[1K"
//! erase current line right from the cursor
#define          ERASE_END_OF_LINE "\x1b[K"

/* a = one of following 23 attributes*/
//! set specific attribute
#define                   SET_ATTR "\x1b[%dm"
//! if you have to set more attributes, separate them by   ";"
#define                   AND_ATTR  ";"
/*generalattributes (0-8 without 3 and 6) */
//!resets terminal defaults
#define                 ATTR_RESET 0
//!sets brighter fg color
#define                ATTR_BRIGHT 1
//!turns off bright (sets darker fg color) note: not supported by most of platforms
#define                   ATTR_DIM 2
//!turns on text underline (not supported by MS Windows)
#define            ATTR_UNDERSCORE 4
//!turns on blink (Not supported by MS Windows, most of other implementations incompatible)
#define                 ATTR_BLINK 5
//! Inverts bg and fg color (incompatible implementation on MS windows)*/
#define               ATTR_REVERSE 7

#define                ATTR_HIDDEN 8 /*???*/

/*Foreground (text) colours*/
#define             FG_COLOR_BLACK 30
#define               FG_COLOR_RED 31
#define             FG_COLOR_GREEN 32
#define            FG_COLOR_YELLOW 33
#define              FG_COLOR_BLUE 34
#define           FG_COLOR_MAGENTA 35
#define              FG_COLOR_CYAN 36
#define             FG_COLOR_WHITE 37

/*Background colors*/
#define             BG_COLOR_BLACK 40
#define               BG_COLOR_RED 41
#define             BG_COLOR_GREEN 42
#define            BG_COLOR_YELLOW 43
#define              BG_COLOR_BLUE 44
#define           BG_COLOR_MAGENTA 45
#define              BG_COLOR_CYAN 46
#define             BG_COLOR_WHITE 47

