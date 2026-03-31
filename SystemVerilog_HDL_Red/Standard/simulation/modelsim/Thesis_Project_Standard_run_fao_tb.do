transcript on
if {[file exists rtl_work]} {
	vdel -lib rtl_work -all
}
vlib rtl_work
vmap work rtl_work

# ------------------------------------------------------------
# Compile RTL
# ------------------------------------------------------------
vlog -sv -work work +incdir+/home/daniel/Thesis_Project/SystemVerilog_HDL_Red/Standard/src {/home/daniel/Thesis_Project/SystemVerilog_HDL_Red/Standard/src/frame_ram.sv}
vlog -sv -work work +incdir+/home/daniel/Thesis_Project/SystemVerilog_HDL_Red/Standard/src {/home/daniel/Thesis_Project/SystemVerilog_HDL_Red/Standard/src/shared_frame_storage.sv}
vlog -sv -work work +incdir+/home/daniel/Thesis_Project/SystemVerilog_HDL_Red/Standard/src {/home/daniel/Thesis_Project/SystemVerilog_HDL_Red/Standard/src/fused_aligned_output.sv}

# ------------------------------------------------------------
# Compile Testbench
# ------------------------------------------------------------
vlog -sv -work work /home/daniel/Thesis_Project/SystemVerilog_HDL_Red/Standard/tb/fused_aligned_output_tb.sv

# ------------------------------------------------------------
# Simulate
# ------------------------------------------------------------
vsim -voptargs=+acc work.fused_aligned_output_tb

# ------------------------------------------------------------
# Add waves
# ------------------------------------------------------------
add wave -r sim:/fused_aligned_output_tb/*

# ------------------------------------------------------------
# Run
# ------------------------------------------------------------
run -all
