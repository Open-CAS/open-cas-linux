/*
* Copyright(c) 2012-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
*/

#define _GNU_SOURCE
#include <stdio.h>
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <sys/ioctl.h>
#include <sys/types.h>
#include <time.h>
#include <stdbool.h>
#include "cas_lib.h"
#include "extended_err_msg.h"
#include "cas_lib_utils.h"
#include "safeclib/safe_str_lib.h"
#include <pthread.h>
#include <unistd.h>
#include <signal.h>
#include <poll.h>
#include <execinfo.h>
extern cas_printf_t cas_printf;

#define IOCTL_RETRIES			3 /* this is how many times ioctl is called */

#define VT100_CLEARLINE		"[K"
#define ESCAPE				0x1b
#define CARRIAGE_RETURN		0xd
#define INVALID_DIRTY_NO ((uint64_t) (-1))

/* file descriptors for pipe */
/* 1 is writing end, 0 is reading end of a pipe */
int fdspipe[2];
/* these must be global for handling signals */
volatile static int interrupted = 0;	/*!< signal was caught, interrupt the
					 *!< management operation now! */
static int finished = 0;		/*!< if management operation has finished
					 *!< (so that progressbar drawing thread
					 *!< can either display "100%" or exit quietly */
static int device_id = 0;		/*!< id of caching device to which management
					 *!< operation that is underway, applies */


/**
 * Default signal handling function exists so that SIGINT wan't interrupt management
 * operations in unpredicted/disallowed way.
 */
void sig_handler_default(int x)
{
	static int inter_counter = 0;
	inter_counter++;
	if (inter_counter>4) {
		cas_printf(LOG_ERR,
			   "Can't interrupt CAS management process\n");
	}
}

/**
 * If management operation was interrupted due to user action (SIGINT)
 */
int was_ioctl_interrupted()
{
	return interrupted;
}

void sig_handler_interrupt_flushing(int x)
{
	struct kcas_interrupt_flushing cmd_info;
	int fd = open(CTRL_DEV_PATH, 0);
	close(fdspipe[1]);
	interrupted = 1;

	if (fd < 0) {
		cas_printf(LOG_ERR, "Device " CTRL_DEV_PATH " not found\n");
		return;
	}

	memset(&cmd_info, 0, sizeof(cmd_info));
	cmd_info.cache_id = device_id;

	int res =
		run_ioctl(fd, KCAS_IOCTL_INTERRUPT_FLUSHING, &cmd_info);

	close(fd);
	if (!res) {
		set_default_sig_handler();
	}
}

/**
 * print current backtrace
 */
void dump_stack()
{
	const int sym_max = 512;
	void *sym_buf[sym_max];
	int nsym;
	nsym = backtrace(sym_buf, sym_max);
	backtrace_symbols_fd(sym_buf, nsym, 2);
}

/**
 * Sad CAS :(
 * dump stack to allow debugging.
 */
void segv_handler_default(int i)
{
	cas_printf(LOG_ERR, "Segmentation fault\n");
	dump_stack();
	exit(EXIT_FAILURE);
}

/**
 * register default signal handling function
 */
void set_default_sig_handler()
{
	signal(SIGINT, sig_handler_default);
	signal(SIGSEGV, segv_handler_default);
}

/**
 * handle errors of cafe c library (wrong parameters passed)
 */
static void safe_lib_constraint_handler(const char *msg, void *ptr, errno_t error)
{
	cas_printf(LOG_ERR, "Safe C lib error\n");
	if (msg) {
		cas_printf(LOG_ERR, "%s (%d)\n", msg, error);
	}
	dump_stack();
	exit(EXIT_FAILURE);
}

/**
 * Register constraint handler for safe_string_library
 */
void set_safe_lib_constraint_handler()
{
	set_mem_constraint_handler_s(safe_lib_constraint_handler);
	set_str_constraint_handler_s(safe_lib_constraint_handler);
}

int _open_ctrl_device(int quiet)
{
	int fd;
	fd = open(CTRL_DEV_PATH, 0);

	if (fd < 0) {
		if (!quiet) {
			cas_printf(LOG_ERR, "Device " CTRL_DEV_PATH
				" not found\n");
			cas_printf(LOG_INFO, "Is the kernel module loaded?\n");
		}
		return -1;
	}

	return fd;
}

int open_ctrl_device_quiet()
{
	return _open_ctrl_device(true);
}

/**
 * calls open on control device; returns either error (-1) or a valid file descriptor
 */
int open_ctrl_device()
{
	return _open_ctrl_device(false);
}

/**
 * @brief print spinning wheel
 */
void print_progress_indicator(float prog, struct progress_status *ps)
{
	static const char prog_indicator[] = { '|', '/', '-', '\\', '|', '/', '-', '\\'};
	/*!< set of characters implementing "spinning wheel" progress indicator */
	static int max_i = ARRAY_SIZE(prog_indicator);
	static int i = 0;

	printf("%c%s... [%c]%c" VT100_CLEARLINE,
		CARRIAGE_RETURN, ps->friendly_name, prog_indicator[i], ESCAPE);
	if (50 < prog) {
		/* we're almost there. Ignore all signals at this stage */
		set_default_sig_handler();
	}

	i = (i + 1) % max_i;
	fflush(stdout);
}

/**
 * @brief print progress bar once
 * @param prog degree of progress (0-100)
 * @param ps structure holding status between progressbar and caller
 */
void print_progress_bar(float prog, struct progress_status *ps)
{
	/* constants affecting look of progressbar/activity indicator */
	static const char progress_full = '=';	/*!< represents progress_step of progress */
	static const char progress_partial = '-';/*!< represents progress of more than 0
						  *!< but less than progress_step */
	static const char progress_empty = ' '; /*!< progressbar didn't reach here */
	static const char delimiter_left = '['; /*!< left delimiter of progress bar */
	static const char delimiter_right = ']';/*!< right delimiter of progress bar */
	static const int progress_step = 2;	/*!< progress step - percentage of progress to
						 *!< be represented by one character. i.e. if
						 *!< progress stepis set to 2, entire
						 *!< progressbar is 50 chars wide+2 chars for
						 *!< delimiters */

	int i, remaining_m;
	time_t elapsed, remaining_s;

	printf("%c%s... ", CARRIAGE_RETURN, ps->friendly_name);
	/* carriage return and "name of op"*/
	putchar(delimiter_left);

	/* make sure, progressbar always moves forward and never backward */
	if (prog < ps->progress_accumulated) {
		prog = ps->progress_accumulated;
	} else {
		ps->progress_accumulated = prog;
	}

	/* print actual progress bar */
	for (i = progress_step; i <= prog; i += progress_step){
		putchar(progress_full);
	}

	if (((int)prog) % progress_step) {
		putchar(progress_partial);
		i += progress_step;
	}

	for (; i <= 100; i += progress_step){
		putchar(progress_empty);
	}

	elapsed = time(NULL) - ps->time_started;

	remaining_s = ((100 - prog) * elapsed) / (prog ?: 1);
	remaining_m = remaining_s / 60;
	remaining_s -= remaining_m * 60;

	if (remaining_m) {
		/* ESCAPE VT100_CLEARLINE is terminal control sequence to clear "rest
		 * of the line */
		printf("%c %3.1f%% [%dm%02lds remaining]%c" VT100_CLEARLINE,
			delimiter_right, prog, remaining_m, remaining_s, ESCAPE);
	} else {
		printf("%c %3.1f%% [%lds remaining]%c" VT100_CLEARLINE,
			delimiter_right, prog, remaining_s, ESCAPE);
	}

	fflush(stdout);
}

/**
 * @brief either print a progressbar or spinning wheel depending on prog
 */
void print_progress_bar_or_indicator(float prog, struct progress_status *ps)
{
	if (0.01 > prog || 99.99 < prog) {
		print_progress_indicator(prog, ps);
	} else {
		print_progress_bar(prog, ps);
	}
}

/**
 * initialize progressbar structure;
 */
void init_progress_bar(struct progress_status *ps)
{
	if (NULL != ps) {
		memset(ps, 0, sizeof(*ps));
		ps->dirty_clines_curr = INVALID_DIRTY_NO;
		ps->dirty_clines_initial = INVALID_DIRTY_NO;
		ps->time_started = time(NULL);
	}
}

void get_core_flush_progress(int fd, int cache_id, int core_id, float *prog)
{
	struct kcas_core_info cmd_info;

	memset(&cmd_info, 0, sizeof(cmd_info));
	cmd_info.cache_id = cache_id;
	cmd_info.core_id = core_id;

	if (0 == ioctl(fd, KCAS_IOCTL_CORE_INFO, &cmd_info)) {
		*prog = calculate_flush_progress(cmd_info.info.dirty,
				cmd_info.info.flushed);
	}
}

void get_cache_flush_progress(int fd, int cache_id, float *prog)
{
	struct kcas_cache_info cmd_info;

	memset(&cmd_info, 0, sizeof(cmd_info));
	cmd_info.cache_id = cache_id;

	if (0 == ioctl(fd, KCAS_IOCTL_CACHE_INFO, &cmd_info)) {
		*prog = calculate_flush_progress(cmd_info.info.dirty,
				cmd_info.info.flushed);
	}
}

/**
 * pthread thread handling function - runs during proper ioctl execution. Prints command progress
 */
void *print_command_progress(void *th_arg)
{
	static const int
		show_progressbar_after = 2;	/*!< threshold in seconds */

	int do_print_progress_bar = 0;
	int mseconds = 0; /*< milliseconds */
	int fd;
	float prog = 0.;
	struct progress_status *ps = th_arg;
	/* argument of command progress of which is monitored */
	/*1,2,0 are descriptors of stdout, err and in respectively*/
	int running_tty = isatty(1) && isatty(2) && isatty(0);
	struct sigaction new_action, old_action;

	fd = open(CTRL_DEV_PATH, 0);
	if (fd < 0) {
		cas_printf(LOG_ERR, "Device " CTRL_DEV_PATH " not found\n");
		return NULL; /* FAILURE; */
	}

	device_id = ps->cache_id;

	sigaction(SIGINT, NULL, &old_action);
	if (old_action.sa_handler != SIG_IGN) {
		new_action.sa_handler = sig_handler_interrupt_flushing;
		sigemptyset(&new_action.sa_mask);
		new_action.sa_flags = 0;
		sigaction(SIGINT, &new_action, NULL);
	}

	sched_yield();

	while (1) {
		struct pollfd pfd;
		struct timespec ts;
		sigset_t sigmask;
		int ppoll_res;
		sigemptyset(&sigmask);
		ts.tv_sec = 1;
		ts.tv_nsec = 0;
		pfd.fd = fdspipe[0];
		pfd.events = POLLIN | POLLRDHUP;
		ppoll_res =  ppoll(&pfd, 1, &ts, &sigmask);
		if (ppoll_res < 0) {
			if (ENOMEM == errno) {
				sleep(1);
				/* ppoll call failed due to insufficient memory */
			} else if (EINTR == errno) {
				interrupted = 1;
			} else { /* other error conditions are EFAULT or EINVAL
				  * cannot happen in realistic conditions,
				  * and are likely to refer to OS errors, which
				  * cannot possibly be handled. Perform abortion.
				  */
				cas_printf(LOG_ERR, "Failed ppoll");
				abort();
			}
		}
		mseconds += 1000;

		if (interrupted) {
			/* if flushing is interrupted by signal, don't proceed with displaying
			 * any kind of progress bar. if bar was previously printed,
			 * print indicator instead */
			if (do_print_progress_bar) {
				print_progress_indicator(100, ps);
			}
			break;
		} else if (finished) {
			if (do_print_progress_bar) {
				print_progress_bar_or_indicator(100., ps);
			}
			break;
		}

		if (ps->core_id == OCF_CORE_ID_INVALID) {
			get_cache_flush_progress(fd, ps->cache_id, &prog);
		} else {
			get_core_flush_progress(fd, ps->cache_id, ps->core_id, &prog);
		}

		/* it is normal that ioctl to get statistics
		 * fails from time to time. Most common cases
		 * of it are:
		 * - during --start-cache when cache isn't added
		 * - during --stopping-cache, when progress is
		 *   supposed to read "100%", but cache is actually
		 *   already removed and its stopping progress can't
		 *   be queried at all.
		 */
		if (mseconds >= show_progressbar_after * 1000
		    && running_tty && prog < 50) {
			do_print_progress_bar = 1;
		}

		if (do_print_progress_bar) {
			print_progress_bar_or_indicator(prog, ps);
		}
	}
	close(fdspipe[0]);

	close(fd);

	/* if progressbar was displayed at least one, clear line */
	if (do_print_progress_bar) {
		printf("%c%c" VT100_CLEARLINE, CARRIAGE_RETURN, ESCAPE);
	}
	fflush(stdout);
	return NULL;
}

/*
 * Run ioctl in a way that displays progressbar (if flushing operation takes longer)
 * Catch SIGINT signal.
 * @param friendly_name name of management operation that shall
 * be displayed in command prompt
 * @param retry decide if ioctl attepmts should retry
 */
static int run_ioctl_interruptible_retry_option(int fd, int command, void *cmd,
		char *friendly_name, int cache_id, int core_id, bool retry)
{
	pthread_t thread;
	int ioctl_res;
	struct progress_status ps;
	sigset_t sigset;

	init_progress_bar(&ps);
	ps.friendly_name = friendly_name;
	ps.cache_id = cache_id;
	ps.core_id = core_id;
	if (pipe(fdspipe)) {
		cas_printf(LOG_ERR,"Failed to allocate pipes.\n");
		return -1;
	}
	interrupted = 0;

	sigemptyset(&sigset);
	sigaddset(&sigset, SIGINT);
	pthread_sigmask(SIG_BLOCK, &sigset, NULL);

	pthread_create(&thread, 0, print_command_progress, &ps);

	if (retry) {
		ioctl_res = run_ioctl_retry(fd, command, cmd);
	} else {
		ioctl_res = run_ioctl(fd, command, cmd);
	}
	
	if (!interrupted) {
		close(fdspipe[1]);
	}
	finished = 1;

	pthread_join(thread, 0);

	return ioctl_res;
}

/*
 * Run ioctl in a way that displays progressbar (if flushing operation takes longer)
 * Catch SIGINT signal.
 * @param friendly_name name of management operation that shall
 * be displayed in command prompt
 */
int run_ioctl_interruptible(int fd, int command, void *cmd,
		char *friendly_name, int cache_id, int core_id)
{
	return run_ioctl_interruptible_retry_option(fd, command, cmd, friendly_name, 
				cache_id, core_id, false);
}

/*
 * Run ioctl in a way that displays progressbar (if flushing operation 
 * takes longer) with retries.
 * Catch SIGINT signal.
 * @param friendly_name name of management operation that shall
 * be displayed in command prompt
 */
int run_ioctl_interruptible_retry(int fd, int command, void *cmd,
		char *friendly_name, int cache_id, int core_id)
{
	return run_ioctl_interruptible_retry_option(fd, command, cmd, friendly_name, 
				cache_id, core_id, true);
}

/*
 * @brief ioctl wrapper
 * @param[in] fd as for IOCTL(2)
 * @param[in] command as for IOCTL(2)
 * @param[inout] cmd_info as for IOCTL(2)
 */
int run_ioctl(int fd, int command, void *cmd)
{
	return ioctl(fd, command, cmd);
}

/*
 * @brief ioctl wrapper that retries ioctl attempts within one second timeouts
 * @param[in] fd as for IOCTL(2)
 * @param[in] command as for IOCTL(2)
 * @param[inout] cmd_info as for IOCTL(2)
 */
int run_ioctl_retry(int fd, int command, void *cmd)
{
	int i, ret;
	struct timespec timeout = {
			.tv_sec = 1,
			.tv_nsec = 0,
	};

	for (i = 0; i < IOCTL_RETRIES; i++) {
		ret = ioctl(fd, command, cmd);

		if (ret < 0) {
			if (interrupted) {
				return -EINTR;
			} if (EINTR == errno) {
				return -EINTR;
			} else if (EBUSY == errno) {
				int nret = nanosleep(&timeout, NULL);
				if (nret) {
					return -EINTR;
				}
			} else {
				return ret;
			}
		} else {
			break;
		}
	}

	return ret;
}


int create_pipe_pair(FILE **intermediate_file)
{
	/* 1 is writing end, 0 is reading end of a pipe */
	int pipefd[2];

	if (pipe(pipefd)) {
		cas_printf(LOG_ERR,"Failed to create unidirectional pipe.\n");
		return FAILURE;
	}

	intermediate_file[0] = fdopen(pipefd[0], "r");
	if (!intermediate_file[0]) {
		cas_printf(LOG_ERR,"Failed to open reading end of an unidirectional pipe.\n");
		close(pipefd[0]);
		close(pipefd[1]);
		return FAILURE;
	}
	intermediate_file[1] = fdopen(pipefd[1], "w");
	if (!intermediate_file[1]) {
		cas_printf(LOG_ERR,"Failed to open reading end of an unidirectional pipe.\n");
		fclose(intermediate_file[0]);
		close(pipefd[1]);
		return FAILURE;
	}
	return SUCCESS;
}
