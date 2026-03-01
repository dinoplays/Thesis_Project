transcript on
if {[file exists rtl_work]} {
	vdel -lib rtl_work -all
}
vlib rtl_work
vmap work rtl_work

vlog -sv -work work +incdir+/home/daniel/Thesis_Project/SystemVerilog_HDL/Bit_Manipulation/src {/home/daniel/Thesis_Project/SystemVerilog_HDL/Bit_Manipulation/src/top_level.sv}
vlog -sv -work work +incdir+/home/daniel/Thesis_Project/SystemVerilog_HDL/Bit_Manipulation/src {/home/daniel/Thesis_Project/SystemVerilog_HDL/Bit_Manipulation/src/bit_shift_low_pass_filter.sv}

