transcript on
if {[file exists rtl_work]} {
	vdel -lib rtl_work -all
}
vlib rtl_work
vmap work rtl_work

# ------------------------------------------------------------
# Compile RTL
# ------------------------------------------------------------
vlog -sv -work work +incdir+/home/daniel/Thesis_Project/SystemVerilog_HDL/Bit_Manipulation/src {/home/daniel/Thesis_Project/SystemVerilog_HDL/Bit_Manipulation/src/confidence_computer.sv}

# ------------------------------------------------------------
# Compile Testbench
# ------------------------------------------------------------
vlog -sv -work work /home/daniel/Thesis_Project/SystemVerilog_HDL/Bit_Manipulation/tb/confidence_computer_tb.sv

# ------------------------------------------------------------
# Simulate
# ------------------------------------------------------------
vsim -voptargs=+acc work.confidence_computer_tb

# ------------------------------------------------------------
# Add waves
# ------------------------------------------------------------
add wave -r sim:/confidence_computer_tb/*

# ------------------------------------------------------------
# Run
# ------------------------------------------------------------
run -all
