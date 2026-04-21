transcript on
if {[file exists rtl_work]} {
	vdel -lib rtl_work -all
}
vlib rtl_work
vmap work rtl_work

vlog -sv -work work +incdir+/home/daniel/Thesis_Project/SystemVerilog_HDL_Red_Small/Bit_Manipulation_Power/src {/home/daniel/Thesis_Project/SystemVerilog_HDL_Red_Small/Bit_Manipulation_Power/src/shared_frame_storage.sv}
vlog -sv -work work +incdir+/home/daniel/Thesis_Project/SystemVerilog_HDL_Red_Small/Bit_Manipulation_Power/src {/home/daniel/Thesis_Project/SystemVerilog_HDL_Red_Small/Bit_Manipulation_Power/src/fused_aligned_output.sv}
vlog -sv -work work +incdir+/home/daniel/Thesis_Project/SystemVerilog_HDL_Red_Small/Bit_Manipulation_Power/src {/home/daniel/Thesis_Project/SystemVerilog_HDL_Red_Small/Bit_Manipulation_Power/src/disparity_estimator.sv}
vlog -sv -work work +incdir+/home/daniel/Thesis_Project/SystemVerilog_HDL_Red_Small/Bit_Manipulation_Power/src {/home/daniel/Thesis_Project/SystemVerilog_HDL_Red_Small/Bit_Manipulation_Power/src/confidence_computer.sv}
vlog -sv -work work +incdir+/home/daniel/Thesis_Project/SystemVerilog_HDL_Red_Small/Bit_Manipulation_Power/src {/home/daniel/Thesis_Project/SystemVerilog_HDL_Red_Small/Bit_Manipulation_Power/src/frame_ram.sv}
vlog -sv -work work +incdir+/home/daniel/Thesis_Project/SystemVerilog_HDL_Red_Small/Bit_Manipulation_Power/src {/home/daniel/Thesis_Project/SystemVerilog_HDL_Red_Small/Bit_Manipulation_Power/src/epi_compiler.sv}
vlog -sv -work work +incdir+/home/daniel/Thesis_Project/SystemVerilog_HDL_Red_Small/Bit_Manipulation_Power/src {/home/daniel/Thesis_Project/SystemVerilog_HDL_Red_Small/Bit_Manipulation_Power/src/top_level.sv}
vlog -sv -work work +incdir+/home/daniel/Thesis_Project/SystemVerilog_HDL_Red_Small/Bit_Manipulation_Power/src {/home/daniel/Thesis_Project/SystemVerilog_HDL_Red_Small/Bit_Manipulation_Power/src/bit_shift_low_pass_filter.sv}

