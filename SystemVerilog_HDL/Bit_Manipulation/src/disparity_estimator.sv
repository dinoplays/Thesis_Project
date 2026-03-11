module disparity_estimator #(
	parameter int unsigned IMAGE_DIM    = 128,
	parameter int unsigned IMAGE_DIM_BS = 7
)(
	input  wire                     clk,
	input  wire                     epi_valid_in,
	input  wire [14:0]              epi_column_in [0:8],
	input  wire [IMAGE_DIM_BS-1:0]  epi_column_idx_in,
	input  wire [IMAGE_DIM_BS-1:0]  epi_idx_in,
	input  wire                     epi_orientation_in,
	input  wire                     derivative_valid_in,
	input  wire [14:0]              derivative_column_in [0:6],
	input  wire [IMAGE_DIM_BS-1:0]  derivative_column_idx_in,
	input  wire [IMAGE_DIM_BS-1:0]  derivative_idx_in,
	input  wire                     derivative_orientation_in,
	output logic                    disparity_valid_out,
	output logic [14:0]             disparity_pixel_out,
	output logic [IMAGE_DIM_BS-1:0] disparity_row_idx_out,
	output logic [IMAGE_DIM_BS-1:0] disparity_column_idx_out,
	output logic                    orientation_out
);

	assign disparity_valid_out		= 0;
	assign disparity_pixel_out		= 0;
	assign disparity_row_idx_out	= 0;
	assign disparity_column_idx_out = 0;
	assign orientation_out			= 0;

	// -------------------------------------------------------------------------
	// Spatial derivative computations
	// -------------------------------------------------------------------------
	// Inputs are coming in by column
	// So we need to store previous 2 columns before we can compute (n-2, n-1)
	logic [14:0] epi_column_in_nm2 [0:8];
	logic [14:0] epi_column_in_nm1 [0:8];

	// Columns of signed values to store derivative
	logic signed [15:0] spatial_derivatives [0:8];

	always_ff @(posedge clk) begin : Spatial_Derivative_Computations
		if (epi_valid_in) begin
			// Store previous 2 columns
			epi_column_in_nm1[0] <= epi_column_in[0];
			epi_column_in_nm1[1] <= epi_column_in[1];
			epi_column_in_nm1[2] <= epi_column_in[2];
			epi_column_in_nm1[3] <= epi_column_in[3];
			epi_column_in_nm1[4] <= epi_column_in[4];
			epi_column_in_nm1[5] <= epi_column_in[5];
			epi_column_in_nm1[6] <= epi_column_in[6];
			epi_column_in_nm1[7] <= epi_column_in[7];
			epi_column_in_nm1[8] <= epi_column_in[8];

			epi_column_in_nm2[0] <= epi_column_in_nm1[0];
			epi_column_in_nm2[1] <= epi_column_in_nm1[1];
			epi_column_in_nm2[2] <= epi_column_in_nm1[2];
			epi_column_in_nm2[3] <= epi_column_in_nm1[3];
			epi_column_in_nm2[4] <= epi_column_in_nm1[4];
			epi_column_in_nm2[5] <= epi_column_in_nm1[5];
			epi_column_in_nm2[6] <= epi_column_in_nm1[6];
			epi_column_in_nm2[7] <= epi_column_in_nm1[7];
			epi_column_in_nm2[8] <= epi_column_in_nm1[8];

			// Compute spatial derivative
			// We are effectively using a 3x1 kernel, which is [-1/2, 0, 1/2]
			spatial_derivatives[0] <= (epi_column_in[0] - epi_column_in_nm2[0]) >> 1;
			spatial_derivatives[1] <= (epi_column_in[1] - epi_column_in_nm2[1]) >> 1;
			spatial_derivatives[2] <= (epi_column_in[2] - epi_column_in_nm2[2]) >> 1;
			spatial_derivatives[3] <= (epi_column_in[3] - epi_column_in_nm2[3]) >> 1;
			spatial_derivatives[4] <= (epi_column_in[4] - epi_column_in_nm2[4]) >> 1;
			spatial_derivatives[5] <= (epi_column_in[5] - epi_column_in_nm2[5]) >> 1;
			spatial_derivatives[6] <= (epi_column_in[6] - epi_column_in_nm2[6]) >> 1;
			spatial_derivatives[7] <= (epi_column_in[7] - epi_column_in_nm2[7]) >> 1;
			spatial_derivatives[8] <= (epi_column_in[8] - epi_column_in_nm2[8]) >> 1;
		end
	end

endmodule