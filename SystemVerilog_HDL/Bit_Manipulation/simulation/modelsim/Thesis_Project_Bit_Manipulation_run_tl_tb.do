transcript on
if {[file exists rtl_work]} {
	vdel -lib rtl_work -all
}
vlib rtl_work
vmap work rtl_work

# ------------------------------------------------------------
# Compile RTL
# ------------------------------------------------------------
vlog -sv -work work +incdir+/home/daniel/Thesis_Project/SystemVerilog_HDL/Bit_Manipulation/src {/home/daniel/Thesis_Project/SystemVerilog_HDL/Bit_Manipulation/src/bit_shift_low_pass_filter.sv}
vlog -sv -work work +incdir+/home/daniel/Thesis_Project/SystemVerilog_HDL/Bit_Manipulation/src {/home/daniel/Thesis_Project/SystemVerilog_HDL/Bit_Manipulation/src/frame_ram.sv}
vlog -sv -work work +incdir+/home/daniel/Thesis_Project/SystemVerilog_HDL/Bit_Manipulation/src {/home/daniel/Thesis_Project/SystemVerilog_HDL/Bit_Manipulation/src/shared_frame_storage.sv}
vlog -sv -work work +incdir+/home/daniel/Thesis_Project/SystemVerilog_HDL/Bit_Manipulation/src {/home/daniel/Thesis_Project/SystemVerilog_HDL/Bit_Manipulation/src/epi_compiler.sv}
vlog -sv -work work +incdir+/home/daniel/Thesis_Project/SystemVerilog_HDL/Bit_Manipulation/src {/home/daniel/Thesis_Project/SystemVerilog_HDL/Bit_Manipulation/src/confidence_computer.sv}
vlog -sv -work work +incdir+/home/daniel/Thesis_Project/SystemVerilog_HDL/Bit_Manipulation/src {/home/daniel/Thesis_Project/SystemVerilog_HDL/Bit_Manipulation/src/disparity_estimator.sv}
vlog -sv -work work +incdir+/home/daniel/Thesis_Project/SystemVerilog_HDL/Bit_Manipulation/src {/home/daniel/Thesis_Project/SystemVerilog_HDL/Bit_Manipulation/src/fused_aligned_output.sv}
vlog -sv -work work +incdir+/home/daniel/Thesis_Project/SystemVerilog_HDL/Bit_Manipulation/src {/home/daniel/Thesis_Project/SystemVerilog_HDL/Bit_Manipulation/src/top_level.sv}

# ------------------------------------------------------------
# Compile Testbench
# ------------------------------------------------------------
vlog -sv -work work /home/daniel/Thesis_Project/SystemVerilog_HDL/Bit_Manipulation/tb/top_level_tb.sv

# ------------------------------------------------------------
# Simulate
# ------------------------------------------------------------
vsim -voptargs=+acc work.top_level_tb

# ------------------------------------------------------------
# Add waves
# ------------------------------------------------------------
add wave -r sim:/top_level_tb/*

# ------------------------------------------------------------
# Run
# ------------------------------------------------------------
run -all