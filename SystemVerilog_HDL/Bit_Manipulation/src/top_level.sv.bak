module top_level (
	// -------- Clock --------
	input wire CLOCK_50,


	// -------- Board inputs --------
	input wire [1:0] SW,

	// Input is 24 bit RGB for rectified, colour corrected images
	input logic [23:0] SIM_PIXEL_BIT_DATA,

	// Start/end of capture in, start/end of light feild in
	input wire PIXEL_VALID_IN,
	input wire SOC_IN,
	input wire EOC_IN,
	input wire SOLF_IN,
	input wire EOLF_IN,


	// -------- Board outputs --------
	output [1:0] LEDR,

	// Start/end of capture out, start/end of light feild out
	output logic PIXEL_VALID_OUT,
	output logic SOC_OUT,
	output logic EOC_OUT,
	output logic SOLF_OUT,
	output logic EOLF_OUT,

	output logic [23:0] CONFIDENCE_PIXEL_BIT_DATA,
	output logic [23:0] DISPARITY_PIXEL_BIT_DATA,
	output logic [23:0] ABOVE_ARE_R_G_THIS_IS_B
);
	// Code compiled for DE1-SoC (5CSEMA5F31C6)

	// ---------- Low pass filter (blur) ----------

	// Switches 0 & 1 determine kernel size:
	wire [1:0] filter_kernel_size;
	assign filter_kernel_size = SW[1:0];

	// Start/end of capture, start/end of light field
	logic soc_filtered_out  = 0;
	logic eoc_filtered_out  = 0;
	logic solf_filtered_out = 0;
	logic eolf_filtered_out = 0;

	// Output blurred pixel in Q12.12 format
	// We are using unsigned Q12.12
	logic [23:0] filtered_pixel_red   = 0;
	logic [23:0] filtered_pixel_green = 0;
	logic [23:0] filtered_pixel_blue  = 0;

	bit_shift_low_pass_filter BSLPF (
		.clk(CLOCK_50),
		.kernel_size(filter_kernel_size),
		.pixel_valid_in(PIXEL_VALID_IN),
		.soc_in(SOC_IN),
		.eoc_in(EOC_IN),
		.solf_in(SOLF_IN),
		.eolf_in(EOLF_IN),
		.pixel_in(SIM_PIXEL_BIT_DATA),
		.pixel_valid_out(PIXEL_VALID_OUT),
		.soc_out(soc_filtered_out),
		.eoc_out(eoc_filtered_out),
		.solf_out(solf_filtered_out),
		.eolf_out(eolf_filtered_out),
		.pixel_out_red(filtered_pixel_red),
		.pixel_out_green(filtered_pixel_green),
		.pixel_out_blue(filtered_pixel_blue)
	);

	// ---------- Show the state of the switch with LED ----------
	assign LEDR[1:0] = SW[1:0];
	
	// ---------- Assign incomplete variables (development) ----------
	assign SOC_OUT = soc_filtered_out;
	assign EOC_OUT = eoc_filtered_out;
	assign SOLF_OUT = solf_filtered_out;
	assign EOLF_OUT = eolf_filtered_out;
	
	assign CONFIDENCE_PIXEL_BIT_DATA = filtered_pixel_red;
	assign DISPARITY_PIXEL_BIT_DATA = filtered_pixel_green;
	assign ABOVE_ARE_R_G_THIS_IS_B = filtered_pixel_blue;

endmodule