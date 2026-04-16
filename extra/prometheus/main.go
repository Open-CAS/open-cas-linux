/*
 * Copyright(c) 2026 Unvertical
 * SPDX-License-Identifier: BSD-3-Clause
 */

/*
 * Open CAS Prometheus exporter.
 *
 * Collects cache/core/IO-class telemetry via Generic Netlink and serves
 * it as Prometheus metrics.
 *
 * Usage:
 *	./opencas_exporter [-listen :9493]
 */

package main

import (
	"flag"
	"fmt"
	"log"
	"net/http"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

func main() {
	listen := flag.String("listen", ":9493", "address:port to listen on")
	flag.Parse()

	collector := NewCollector()
	prometheus.MustRegister(collector)

	http.Handle("/metrics", promhttp.Handler())
	http.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html")
		fmt.Fprint(w, `<html>
<head><title>Open CAS Exporter</title></head>
<body>
<h1>Open CAS Exporter</h1>
<p><a href="/metrics">Metrics</a></p>
</body>
</html>`)
	})

	log.Printf("Open CAS Prometheus exporter listening on %s", *listen)
	log.Fatal(http.ListenAndServe(*listen, nil))
}
