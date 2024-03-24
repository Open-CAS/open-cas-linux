/*
* Copyright(c) 2012-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
 */

package api

import "C"
import (
	"encoding/json"
	"fmt"
)

/** error checking and logging system */
var err_sys Error_sys

type Error_sys struct {
	Log_error_list  map[string]string `json:"error log"`
	stack_error_msg []string
}

/** Error_sys constructor */
func NewError_sys(err_sys Error_sys) *Error_sys {
	err_sys.Log_error_list = make(map[string]string)
	return &err_sys
}

/** marshal error log to json and transfer to stdout */
func (err_sys *Error_sys) write_errors_to_console() {
	Log_error_list_b, marshall_err := json.MarshalIndent(err_sys.Log_error_list, "", "  ")
	if check_err(marshall_err) {
		log_console("failed marshaling JSON error response")
		return
	}
	fmt.Println(string(Log_error_list_b))
}

/** check whether error occured and log it's occurance */
func check_err(err error) bool {
	if err != nil {
		return true
	}
	return false
}

/** logs errors to console */
func log_console(msg string) {
	if err_sys.Log_error_list == nil {
		err_sys.Log_error_list = make(map[string]string)
		err_sys.stack_error_msg = make([]string, 1)
		err_sys.Log_error_list["error"] = msg
	}
	err_sys.stack_error_msg = append(err_sys.stack_error_msg, msg)
}

/** error of errno type even if everything went write is not nil and have message "errno 0" so we check that */
func errno_to_error(err error) error {
	if err == nil {
		return nil
	}
	if err.Error() == "errno 0" {
		return nil
	}
	return err
}
