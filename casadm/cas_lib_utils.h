/*
* Copyright(c) 2012-2022 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
*/

#ifndef __CAS_LIB_UTILS_H__
#define __CAS_LIB_UTILS_H__

struct progress_status {
	uint64_t
	dirty_clines_initial;	/*!< amount of dirty clines when command is initiated */

	uint64_t
	dirty_clines_curr;		/*!< amount of dirty clines at current progress level */

	int progress_accumulated;	/*!< this is to ensure that progressbar is always
					 *!< from 0 to 100% and progress indicated by it
					 *!< never actually drops. */
	time_t time_started;		/*!< time when particular long running
					 *!< operation was started */
	char *friendly_name;		/*!< name of management operation that shall
					 *!< be displayed in command prompt */
	int cache_id;			/*!< cache id */
	int core_id;			/*!< core id */
};


void init_progress_bar(struct progress_status *ps);
void print_progress_bar_or_indicator(float prog, struct progress_status *ps);
int run_ioctl(int fd, int command, void *cmd);
int run_ioctl_retry(int fd, int command, void *cmd);
int run_ioctl_interruptible(int fd, int command, void *cmd,
		char *friendly_name, int cache_id, int core_id);
int run_ioctl_interruptible_retry(int fd, int command, void *cmd,
		char *friendly_name, int cache_id, int core_id);
int open_ctrl_device();
int was_ioctl_interrupted();
void set_default_sig_handler();
void set_safe_lib_constraint_handler();


/**
 * function creates pair files representing an unnamed pipe.
 * this is highlevel counterpart to pipe syscall.
 *
 * null is returned upon failure;
 *
 * FILE *pipes[2] is returned upon success.
 * 1 is writing end, 0 is reading end of a pipe
 */
int create_pipe_pair(FILE **);

/**
 * Check if string is empty
 *
 * @param str - reference to the string
 * @retval 1 string is empty
 * @retval 0 string is not empty
 */
static inline int strempty(const char *str)
{
	if (NULL == str) {
		return 1;
	} else if ('\0' == str[0]) {
		return 1;
	} else {
		return 0;
	}
}

#endif
