transcript on
if {[file exists rtl_work]} {
	vdel -lib rtl_work -all
}
vlib rtl_work
vmap work rtl_work

vlog -sv -work work +incdir+/home/daniel/Thesis_Project/SystemVerilog_HDL_Red/Standard/src {/home/daniel/Thesis_Project/SystemVerilog_HDL_Red/Standard/src/low_pass_filter.sv}
vlog -sv -work work +incdir+/home/daniel/Thesis_Project/SystemVerilog_HDL_Red/Standard/src {/home/daniel/Thesis_Project/SystemVerilog_HDL_Red/Standard/src/top_level.sv}
vlog -sv -work work +incdir+/home/daniel/Thesis_Project/SystemVerilog_HDL_Red/Standard/src {/home/daniel/Thesis_Project/SystemVerilog_HDL_Red/Standard/src/shared_frame_storage.sv}
vlog -sv -work work +incdir+/home/daniel/Thesis_Project/SystemVerilog_HDL_Red/Standard/src {/home/daniel/Thesis_Project/SystemVerilog_HDL_Red/Standard/src/fused_aligned_output.sv}
vlog -sv -work work +incdir+/home/daniel/Thesis_Project/SystemVerilog_HDL_Red/Standard/src {/home/daniel/Thesis_Project/SystemVerilog_HDL_Red/Standard/src/frame_ram.sv}
vlog -sv -work work +incdir+/home/daniel/Thesis_Project/SystemVerilog_HDL_Red/Standard/src {/home/daniel/Thesis_Project/SystemVerilog_HDL_Red/Standard/src/epi_compiler.sv}
vlog -sv -work work +incdir+/home/daniel/Thesis_Project/SystemVerilog_HDL_Red/Standard/src {/home/daniel/Thesis_Project/SystemVerilog_HDL_Red/Standard/src/disparity_estimator.sv}
vlog -sv -work work +incdir+/home/daniel/Thesis_Project/SystemVerilog_HDL_Red/Standard/src {/home/daniel/Thesis_Project/SystemVerilog_HDL_Red/Standard/src/confidence_computer.sv}

