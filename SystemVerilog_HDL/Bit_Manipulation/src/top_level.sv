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

	// Start/end of light field out
	output logic SOLF_OUT,
	output logic EOLF_OUT,

	// Output confidence and pixel validity
	output logic CONFIDENCE_PIXEL_VALID_OUT,
	output logic [23:0] CONFIDENCE_PIXEL_BIT_DATA,

	// Output disparity and pixel validity
	output logic DISPARITY_PIXEL_VALID_OUT,
	output logic [23:0] DISPARITY_PIXEL_BIT_DATA
);
	// Code compiled for DE1-SoC (5CSEMA5F31C6)

	// Set expected image size to 128x128
	parameter int unsigned IMAGE_DIM = 128;
	parameter int unsigned IMAGE_DIM_BS = 7; // 1 << 7 = 128

	// ---------- Low pass filter (blur) ----------

	// Switches 0 & 1 determine kernel size:
	wire [1:0] filter_kernel_size;
	assign filter_kernel_size = SW[1:0];

	// Start/end of capture, start/end of light field
	logic soc_filtered_out  = 0;
	logic eoc_filtered_out  = 0;
	logic solf_filtered_out = 0;
	logic eolf_filtered_out = 0;
	
	// To know which filtered outputs are valid
	logic filtered_pixel_valid = 0;

	// Output blurred pixel in Q8.7 format
	// We are using unsigned Q8.7
	logic [14:0] filtered_pixel_red   = 0;
	logic [14:0] filtered_pixel_green = 0;
	logic [14:0] filtered_pixel_blue  = 0;

	// Bit shift low pass filter module
	// Input pixels are RGB 888
	// Output pixels are formatted with each channel as Q8.8
	bit_shift_low_pass_filter #(
		.IMAGE_DIM(IMAGE_DIM),
		.IMAGE_DIM_BS(IMAGE_DIM_BS)
		) BSLPF (
		.clk(CLOCK_50),
		.kernel_size(filter_kernel_size),
		.pixel_valid_in(PIXEL_VALID_IN),
		.soc_in(SOC_IN),
		.eoc_in(EOC_IN),
		.solf_in(SOLF_IN),
		.eolf_in(EOLF_IN),
		.pixel_in(SIM_PIXEL_BIT_DATA),
		.pixel_valid_out(filtered_pixel_valid),
		.soc_out(soc_filtered_out),
		.eoc_out(eoc_filtered_out),
		.solf_out(solf_filtered_out),
		.eolf_out(eolf_filtered_out),
		.pixel_out_red(filtered_pixel_red),
		.pixel_out_green(filtered_pixel_green),
		.pixel_out_blue(filtered_pixel_blue)
	);
	
	// ---------- EPI compiler modules ----------

	logic epi_valid_out_red = 0;
	logic orientation_out_red = 0;

	// Output EPIs in unsigned Q8.7 format
	// Each axis has 9 images, we bit shift by parmaeter instead of multiplying
	// Output EPI should have dimensions 9x128
	logic [14:0] epi_column_out_red [0:8];
	logic [IMAGE_DIM_BS-1:0] epi_column_idx_out_red;
	logic [IMAGE_DIM_BS-1:0] epi_idx_out_red;
	
	epi_compiler #(
			.IMAGE_DIM(IMAGE_DIM),
			.IMAGE_DIM_BS(IMAGE_DIM_BS)
		) EPIC_RED (
		.clk(CLOCK_50),
		.pixel_valid_in(filtered_pixel_valid),
		.soc_in(soc_filtered_out),
		.eoc_in(eoc_filtered_out),
		.solf_in(solf_filtered_out),
		.eolf_in(eolf_filtered_out),
		.pixel_in(filtered_pixel_red),
		.epi_valid_out(epi_valid_out_red),
		.epi_column_out(epi_column_out_red),
		.epi_column_idx_out(epi_column_idx_out_red),
		.epi_idx_out(epi_idx_out_red),
		.orientation_out(orientation_out_red)
	);

	// ---------- Show the state of the switch with LED ----------
	assign LEDR[1:0] = filter_kernel_size;
	
	// ---------- Assign incomplete variables (development) ----------
	assign CONFIDENCE_PIXEL_VALID_OUT = 0;
	assign DISPARITY_PIXEL_VALID_OUT  = 0;

	assign SOLF_OUT = 0;
	assign EOLF_OUT = 0;

	// Read unsed variables
	assign CONFIDENCE_PIXEL_BIT_DATA = ((filtered_pixel_blue == 0) && (filtered_pixel_green == 0) && (epi_valid_out_red == 0) && (epi_column_out_red[0] == 0) && (epi_column_out_red[1] == 0) && (epi_column_out_red[2] == 0) && (epi_column_out_red[3] == 0) && (epi_column_out_red[4] == 0) && (epi_column_out_red[5] == 0) && (epi_column_out_red[6] == 0) && (epi_column_out_red[7] == 0) && (epi_column_out_red[8] == 0) && (epi_column_idx_out_red == 0) && (epi_idx_out_red == 0) && (orientation_out_red == 0));
	assign DISPARITY_PIXEL_BIT_DATA  = ((filtered_pixel_blue == 0) && (filtered_pixel_green == 0) && (epi_valid_out_red == 0) && (epi_column_out_red[0] == 0) && (epi_column_out_red[1] == 0) && (epi_column_out_red[2] == 0) && (epi_column_out_red[3] == 0) && (epi_column_out_red[4] == 0) && (epi_column_out_red[5] == 0) && (epi_column_out_red[6] == 0) && (epi_column_out_red[7] == 0) && (epi_column_out_red[8] == 0) && (epi_column_idx_out_red == 0) && (epi_idx_out_red == 0) && (orientation_out_red == 0));

endmodule