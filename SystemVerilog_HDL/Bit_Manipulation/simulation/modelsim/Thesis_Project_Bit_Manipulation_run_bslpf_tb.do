transcript on
if {[file exists rtl_work]} {
	vdel -lib rtl_work -all
}
vlib rtl_work
vmap work rtl_work

# ------------------------------------------------------------
# Compile RTL
# ------------------------------------------------------------
vlog -sv -work work +incdir+/home/daniel/Thesis_Project/SystemVerilog_HDL/Bit_Manipulation/src {/home/daniel/Thesis_Project/SystemVerilog_HDL/Bit_Manipulation/src/top_level.sv}
vlog -sv -work work +incdir+/home/daniel/Thesis_Project/SystemVerilog_HDL/Bit_Manipulation/src {/home/daniel/Thesis_Project/SystemVerilog_HDL/Bit_Manipulation/src/bit_shift_low_pass_filter.sv}

# ------------------------------------------------------------
# Compile Testbench
# ------------------------------------------------------------
vlog -sv -work work /home/daniel/Thesis_Project/SystemVerilog_HDL/Bit_Manipulation/tb/bit_shift_low_pass_filter_tb.sv

# ------------------------------------------------------------
# Simulate
# ------------------------------------------------------------
vsim -voptargs=+acc work.bit_shift_low_pass_filter_tb

# ------------------------------------------------------------
# Add waves
# ------------------------------------------------------------
add wave -r sim:/bit_shift_low_pass_filter_tb/*

# ------------------------------------------------------------
# Run
# ------------------------------------------------------------
run -all
