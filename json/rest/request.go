/*
* Copyright(c) 2012-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause-Clear
*/

package rest

import (
	"encoding/json"
	"fmt"
	"io/ioutil"
	"log"
)

type Request struct {
	Req_list_caches bool       `json:"Requested list cache(s) and core(s)"`
	Req_get_stats             bool       `json:"Requested get statistics"`
	Get_stats                 Stats_info `json:"Get statistics"`
}

type Stats_info struct {
	Cache_id          uint16 `json:"cache id"`
	Core_id           uint16 `json:"Core id"`
	Io_class          uint32 `json:"IO class"`
	Req_cache_info    bool   `json:"Requested cache info"`
	Req_core_info     bool   `json:"Requested core info"`
	Req_io_class_info bool   `json:"Requested io classinfo"`
}

/** debug read and write json requests */
func (req *Request) Write_req() {
	file, err := json.MarshalIndent(req, "", "  ")
	_ = ioutil.WriteFile("request.json", file, 0644)
	if err != nil {
		log.Fatal(err)
	}
}

func (req *Request) Read_req() {
	data, err := ioutil.ReadFile("request.json")
	if err != nil {
		log.Fatal(err)
	}
	json.Unmarshal(data, req)
}

func (req *Request) Show_req() {
	req_b, err := json.MarshalIndent(req, "", "  ")
	if err != nil {
		log.Fatal(err)
	}
	fmt.Print("Request: ", string(req_b), "\n")
}
