/*
* Copyright(c) 2012-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause-Clear
*/

package rest

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
)

func RestAPI() {
	handleRequests()
}

func homePage(w http.ResponseWriter, r *http.Request) {
	fmt.Fprintf(w, "Open CAS - RestAPI")
	fmt.Print("Endpoint hit: homePage")
}

func handleRequests() {
	http.HandleFunc("/", homePage)

	/** handling requests */
	http.HandleFunc("/request", returnRequest)
	//http.HandleFunc("/get_stats", )
	//http.HandleFunc("/list_caches", )

	log.Fatal(http.ListenAndServe(":10000", nil))
}

func returnRequest(w http.ResponseWriter, r *http.Request) {
	fmt.Println("Endpoint hit: returnRequest")
	var req Request
	req.Read_req()
	json.NewEncoder(w).Encode(req)
}
