transcript on
if {[file exists rtl_work]} {
	vdel -lib rtl_work -all
}
vlib rtl_work
vmap work rtl_work

# ------------------------------------------------------------
# Compile RTL
# ------------------------------------------------------------
vlog -sv -work work +incdir+/home/daniel/Thesis_Project/SystemVerilog_HDL_RGB/Bit_Manipulation_Power/src {/home/daniel/Thesis_Project/SystemVerilog_HDL_RGB/Bit_Manipulation_Power/src/bit_shift_low_pass_filter.sv}
vlog -sv -work work +incdir+/home/daniel/Thesis_Project/SystemVerilog_HDL_RGB/Bit_Manipulation_Power/src {/home/daniel/Thesis_Project/SystemVerilog_HDL_RGB/Bit_Manipulation_Power/src/frame_ram.sv}
vlog -sv -work work +incdir+/home/daniel/Thesis_Project/SystemVerilog_HDL_RGB/Bit_Manipulation_Power/src {/home/daniel/Thesis_Project/SystemVerilog_HDL_RGB/Bit_Manipulation_Power/src/shared_frame_storage.sv}
vlog -sv -work work +incdir+/home/daniel/Thesis_Project/SystemVerilog_HDL_RGB/Bit_Manipulation_Power/src {/home/daniel/Thesis_Project/SystemVerilog_HDL_RGB/Bit_Manipulation_Power/src/epi_compiler.sv}
vlog -sv -work work +incdir+/home/daniel/Thesis_Project/SystemVerilog_HDL_RGB/Bit_Manipulation_Power/src {/home/daniel/Thesis_Project/SystemVerilog_HDL_RGB/Bit_Manipulation_Power/src/confidence_computer.sv}
vlog -sv -work work +incdir+/home/daniel/Thesis_Project/SystemVerilog_HDL_RGB/Bit_Manipulation_Power/src {/home/daniel/Thesis_Project/SystemVerilog_HDL_RGB/Bit_Manipulation_Power/src/disparity_estimator.sv}
vlog -sv -work work +incdir+/home/daniel/Thesis_Project/SystemVerilog_HDL_RGB/Bit_Manipulation_Power/src {/home/daniel/Thesis_Project/SystemVerilog_HDL_RGB/Bit_Manipulation_Power/src/fused_aligned_output.sv}
vlog -sv -work work +incdir+/home/daniel/Thesis_Project/SystemVerilog_HDL_RGB/Bit_Manipulation_Power/src {/home/daniel/Thesis_Project/SystemVerilog_HDL_RGB/Bit_Manipulation_Power/src/top_level.sv}

# ------------------------------------------------------------
# Compile Testbench
# ------------------------------------------------------------
vlog -sv -work work /home/daniel/Thesis_Project/SystemVerilog_HDL_RGB/Bit_Manipulation_Power/tb/top_level_tb.sv

# ------------------------------------------------------------
# Simulate
# +acc keeps internal hierarchical signals accessible for VCD/power
# ------------------------------------------------------------
vsim -voptargs=+acc work.top_level_tb

# ------------------------------------------------------------
# Add waves
# Full testbench hierarchy for debug
# ------------------------------------------------------------
add wave -r sim:/top_level_tb/*

# ------------------------------------------------------------
# VCD dump for power analysis
# Dump full DUT hierarchy recursively
# Assumes DUT instance name is DUT inside top_level_tb
# ------------------------------------------------------------
vcd file /home/daniel/Thesis_Project/SystemVerilog_HDL_RGB/Bit_Manipulation_Power/simulation/modelsim/dump_tl.vcd
vcd add -r sim:/top_level_tb/DUT/*

# Optional: also dump TB-level signals if you want them in the VCD
# vcd add -r sim:/top_level_tb/*

# ------------------------------------------------------------
# Run
# ------------------------------------------------------------
run -all

# ------------------------------------------------------------
# Finalize VCD
# ------------------------------------------------------------
vcd flush