create_clock -name CLOCK_100 -period 10.000 [get_ports {CLOCK_50}]
derive_clock_uncertainty