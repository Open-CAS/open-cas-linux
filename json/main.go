/*
* Copyright(c) 2012-2021 Intel Corporation
* SPDX-License-Identifier: BSD-Clause-Clear
*/

/*
 *	Prototype of JSON RESTful API
 */

package main

import (
	"fmt"

	"example.com/json/ioctl"
	"example.com/json/rest"
)

func main() {
	fmt.Println("open-cas-linux-RestAPI")

	// test RestAPI
	
	// test request json file
	var req rest.Request
	req.Read_req()
	req.Show_req()
	req.Write_req()

	// get file descriptor
	fd := ioctl.Read_fd()

	// JSON requests control
	if req.Req_list_caches {
		rest.List_caches(fd)
	}

	if req.Req_get_stats {
		rest.Get_stats(fd, req.Get_stats)
	}

	// test cmd flags
	//rest.RestAPI()
	//rest.Flags()
	/*
	 */
}
