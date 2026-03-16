transcript on
if {[file exists rtl_work]} {
	vdel -lib rtl_work -all
}
vlib rtl_work
vmap work rtl_work

# ------------------------------------------------------------
# Compile RTL
# ------------------------------------------------------------
vlog -sv -work work +incdir+/home/daniel/Thesis_Project/SystemVerilog_HDL/Bit_Manipulation/src {/home/daniel/Thesis_Project/SystemVerilog_HDL/Bit_Manipulation/src/frame_ram.sv}
vlog -sv -work work +incdir+/home/daniel/Thesis_Project/SystemVerilog_HDL/Bit_Manipulation/src {/home/daniel/Thesis_Project/SystemVerilog_HDL/Bit_Manipulation/src/shared_frame_storage.sv}
vlog -sv -work work +incdir+/home/daniel/Thesis_Project/SystemVerilog_HDL/Bit_Manipulation/src {/home/daniel/Thesis_Project/SystemVerilog_HDL/Bit_Manipulation/src/epi_compiler.sv}

# ------------------------------------------------------------
# Compile Testbench
# ------------------------------------------------------------
vlog -sv -work work /home/daniel/Thesis_Project/SystemVerilog_HDL/Bit_Manipulation/tb/epi_compiler_tb.sv

# ------------------------------------------------------------
# Simulate
# ------------------------------------------------------------
vsim -voptargs=+acc work.epi_compiler_tb

# ------------------------------------------------------------
# Add waves
# ------------------------------------------------------------
add wave -r sim:/epi_compiler_tb/*

# ------------------------------------------------------------
# Run
# ------------------------------------------------------------
run -all