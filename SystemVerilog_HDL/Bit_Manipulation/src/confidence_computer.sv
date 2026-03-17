module confidence_computer #(
	parameter int unsigned IMAGE_DIM    = 128,
	parameter int unsigned IMAGE_DIM_BS = 7
)(
	input  wire                     clk,
	input  wire                     epi_valid_in,
	input  wire [14:0]              epi_column_in [0:8],
	input  wire [IMAGE_DIM_BS-1:0]  epi_column_idx_in,
	input  wire [IMAGE_DIM_BS-1:0]  epi_idx_in,
	input  wire                     orientation_in,
	output logic                    derivative_valid_out,
	output logic signed [15:0]      derivative_column_out [0:6],
	output logic [IMAGE_DIM_BS-1:0] derivative_row_idx_out,
	output logic [IMAGE_DIM_BS-1:0] derivative_column_idx_out,
	output logic                    derivative_orientation_out,
	output logic                    confidence_valid_out,
	output logic [14:0]             confidence_pixel_out,
	output logic [IMAGE_DIM_BS-1:0] confidence_row_idx_out,
	output logic [IMAGE_DIM_BS-1:0] confidence_column_idx_out,
	output logic                    confidence_orientation_out
);

	// -------------------------------------------------------------------------
	// Extra delay stage for confidence control
	// -------------------------------------------------------------------------
	logic derivative_valid_d;
	logic derivative_valid_2d;
	logic derivative_orientation_d;
	logic derivative_orientation_2d;
	logic [IMAGE_DIM_BS-1:0] derivative_column_idx_d;
	logic [IMAGE_DIM_BS-1:0] derivative_column_idx_2d;
	logic [IMAGE_DIM_BS-1:0] derivative_idx_d;
	logic [IMAGE_DIM_BS-1:0] derivative_idx_2d;

	// -------------------------------------------------------------------------
	// Set outputs
	// -------------------------------------------------------------------------
	always_ff @(posedge clk) begin : Remember_Last_Valid_Inputs_And_Set_Outputs
		// Derivative metadata
		derivative_valid_out	   <= epi_valid_in;
		derivative_orientation_out <= orientation_in;
		derivative_column_idx_out  <= epi_column_idx_in;
		derivative_row_idx_out	   <= epi_idx_in;

		// Confidence metadata computed using derivative shift registers
		derivative_valid_d   <= derivative_valid_out;
		derivative_valid_2d  <= derivative_valid_d;
		confidence_valid_out <= derivative_valid_2d;

		derivative_orientation_d   <= derivative_orientation_out;
		derivative_orientation_2d  <= derivative_orientation_d;
		confidence_orientation_out <= derivative_orientation_2d;

		derivative_column_idx_d  <= derivative_column_idx_out;
		derivative_column_idx_2d <= derivative_column_idx_d;

		derivative_idx_d         <= derivative_row_idx_out;
		derivative_idx_2d        <= derivative_idx_d;

		// Force outputs to always mean:
		//   row_idx    = image row
		//   column_idx = image column
		if (derivative_orientation_2d == 1'b0) begin
			// Horizontal:
			// epi_idx    = row
			// epi_colidx = col
			confidence_row_idx_out    <= derivative_idx_2d;
			confidence_column_idx_out <= derivative_column_idx_2d;
		end
		else begin
			// Vertical:
			// epi_idx    = col
			// epi_colidx = row
			confidence_row_idx_out    <= derivative_column_idx_2d;
			confidence_column_idx_out <= derivative_idx_2d;
		end
	end
	

	// -------------------------------------------------------------------------
	// Angular derivative computations
	// -------------------------------------------------------------------------
	always_ff @(posedge clk) begin : Angular_Derivative_Computations_dLdU_dLdV
		// We are effectively using a 1x3 kernel, where the transposed form is [-1/2, 0, 1/2]
		// Since top and bottom row pixels cannot have a derivation, they are not parsed and are assumed as zero moving forwards
		// So [0] corresponds to row 1 and [6] corresponds to row 7
		derivative_column_out[0] <= ($signed({1'b0, epi_column_in[2]}) - $signed({1'b0, epi_column_in[0]})) >>> 1;
		derivative_column_out[1] <= ($signed({1'b0, epi_column_in[3]}) - $signed({1'b0, epi_column_in[1]})) >>> 1;
		derivative_column_out[2] <= ($signed({1'b0, epi_column_in[4]}) - $signed({1'b0, epi_column_in[2]})) >>> 1;
		derivative_column_out[3] <= ($signed({1'b0, epi_column_in[5]}) - $signed({1'b0, epi_column_in[3]})) >>> 1;
		derivative_column_out[4] <= ($signed({1'b0, epi_column_in[6]}) - $signed({1'b0, epi_column_in[4]})) >>> 1;
		derivative_column_out[5] <= ($signed({1'b0, epi_column_in[7]}) - $signed({1'b0, epi_column_in[5]})) >>> 1;
		derivative_column_out[6] <= ($signed({1'b0, epi_column_in[8]}) - $signed({1'b0, epi_column_in[6]})) >>> 1;
	end

	// -------------------------------------------------------------------------
	// Confidence computations
	// -------------------------------------------------------------------------
	localparam int unsigned DERIVATIVE_SIGNED_DATA_WIDTH = 16; // 15 bits from epi_column_in + 1 for signed
	logic signed [DERIVATIVE_SIGNED_DATA_WIDTH-1:0] absolute_derivative_column [0:6];
	logic [18:0] absolute_derivative_sum;

	always_ff @(posedge clk) begin : Absolute_Derivative
		// If the signed bit is negative we set to negative, else we keep as positive (removing the signed bit)
		absolute_derivative_column[0] <= derivative_column_out[0][DERIVATIVE_SIGNED_DATA_WIDTH-1] ? -derivative_column_out[0] : derivative_column_out[0];
		absolute_derivative_column[1] <= derivative_column_out[1][DERIVATIVE_SIGNED_DATA_WIDTH-1] ? -derivative_column_out[1] : derivative_column_out[1];
		absolute_derivative_column[2] <= derivative_column_out[2][DERIVATIVE_SIGNED_DATA_WIDTH-1] ? -derivative_column_out[2] : derivative_column_out[2];
		absolute_derivative_column[3] <= derivative_column_out[3][DERIVATIVE_SIGNED_DATA_WIDTH-1] ? -derivative_column_out[3] : derivative_column_out[3];
		absolute_derivative_column[4] <= derivative_column_out[4][DERIVATIVE_SIGNED_DATA_WIDTH-1] ? -derivative_column_out[4] : derivative_column_out[4];
		absolute_derivative_column[5] <= derivative_column_out[5][DERIVATIVE_SIGNED_DATA_WIDTH-1] ? -derivative_column_out[5] : derivative_column_out[5];
		absolute_derivative_column[6] <= derivative_column_out[6][DERIVATIVE_SIGNED_DATA_WIDTH-1] ? -derivative_column_out[6] : derivative_column_out[6];

		// Confidence is the average of the absolute derivatives
		// We can just bit shift to decrease latency,
		// It is not underestimating confidence by 1/8, but is relatively accurate across a frame
		absolute_derivative_sum <=
			absolute_derivative_column[0] +
			absolute_derivative_column[1] +
			absolute_derivative_column[2] +
			absolute_derivative_column[3] +
			absolute_derivative_column[4] +
			absolute_derivative_column[5] +
			absolute_derivative_column[6];

		confidence_pixel_out <= absolute_derivative_sum[17:3];
	end
endmodule