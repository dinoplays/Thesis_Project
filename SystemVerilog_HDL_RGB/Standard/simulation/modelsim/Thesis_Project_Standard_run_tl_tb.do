transcript on
if {[file exists rtl_work]} {
	vdel -lib rtl_work -all
}
vlib rtl_work
vmap work rtl_work

# ------------------------------------------------------------
# Compile RTL
# ------------------------------------------------------------
vlog -sv -work work +incdir+/home/daniel/Thesis_Project/SystemVerilog_HDL_RGB/Standard/src {/home/daniel/Thesis_Project/SystemVerilog_HDL_RGB/Standard/src/low_pass_filter.sv}
vlog -sv -work work +incdir+/home/daniel/Thesis_Project/SystemVerilog_HDL_RGB/Standard/src {/home/daniel/Thesis_Project/SystemVerilog_HDL_RGB/Standard/src/frame_ram.sv}
vlog -sv -work work +incdir+/home/daniel/Thesis_Project/SystemVerilog_HDL_RGB/Standard/src {/home/daniel/Thesis_Project/SystemVerilog_HDL_RGB/Standard/src/shared_frame_storage.sv}
vlog -sv -work work +incdir+/home/daniel/Thesis_Project/SystemVerilog_HDL_RGB/Standard/src {/home/daniel/Thesis_Project/SystemVerilog_HDL_RGB/Standard/src/epi_compiler.sv}
vlog -sv -work work +incdir+/home/daniel/Thesis_Project/SystemVerilog_HDL_RGB/Standard/src {/home/daniel/Thesis_Project/SystemVerilog_HDL_RGB/Standard/src/confidence_computer.sv}
vlog -sv -work work +incdir+/home/daniel/Thesis_Project/SystemVerilog_HDL_RGB/Standard/src {/home/daniel/Thesis_Project/SystemVerilog_HDL_RGB/Standard/src/disparity_estimator.sv}
vlog -sv -work work +incdir+/home/daniel/Thesis_Project/SystemVerilog_HDL_RGB/Standard/src {/home/daniel/Thesis_Project/SystemVerilog_HDL_RGB/Standard/src/fused_aligned_output.sv}
vlog -sv -work work +incdir+/home/daniel/Thesis_Project/SystemVerilog_HDL_RGB/Standard/src {/home/daniel/Thesis_Project/SystemVerilog_HDL_RGB/Standard/src/top_level.sv}

# ------------------------------------------------------------
# Compile Testbench
# ------------------------------------------------------------
vlog -sv -work work /home/daniel/Thesis_Project/SystemVerilog_HDL_RGB/Standard/tb/top_level_tb.sv

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
vcd file /home/daniel/Thesis_Project/SystemVerilog_HDL_RGB/Standard/simulation/modelsim/dump_tl.vcd
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