module disparity_estimator #(
	parameter int unsigned IMAGE_DIM    = 128,
	parameter int unsigned IMAGE_DIM_BS = 7
)(
	input  wire                             clk,
	input  wire                             epi_valid_in,
	input  wire [14:0]                      epi_column_in [0:8],
	input  wire [IMAGE_DIM_BS-1:0]          epi_column_idx_in,
	input  wire [IMAGE_DIM_BS-1:0]          epi_idx_in,
	input  wire                             epi_orientation_in,
	input  wire                             angular_derivative_valid_in,
	input  wire signed [15:0]               angular_derivative_column_in [0:6],
	input  wire [IMAGE_DIM_BS-1:0]          angular_derivative_row_idx_in,
	input  wire [IMAGE_DIM_BS-1:0]          angular_derivative_column_idx_in,
	input  wire                             angular_derivative_orientation_in,
	output logic                            disparity_valid_out,
	output logic signed [31:0]              disparity_pixel_out,   // signed Q15.16
	output logic [IMAGE_DIM_BS-1:0]         disparity_row_idx_out,
	output logic [IMAGE_DIM_BS-1:0]         disparity_column_idx_out,
	output logic                            orientation_out
);

	// -------------------------------------------------------------------------
	// Divider configuration
	// -------------------------------------------------------------------------
	localparam int unsigned DIVIDEND_W = 54;
	localparam int unsigned DIVISOR_W  = 38;
	localparam int unsigned QUOTIENT_W = 54;
	localparam int unsigned DIV_STAGES = DIVIDEND_W;

	// -------------------------------------------------------------------------
	// Helper functions
	// -------------------------------------------------------------------------
	function automatic logic [37:0] abs38(input logic signed [37:0] x);
		begin
			if (x < 0) begin
				abs38 = $unsigned(-x);
			end
			else begin
				abs38 = $unsigned(x);
			end
		end
	endfunction

	function automatic logic signed [31:0] saturate_q15_16(
		input logic sign_bit,
		input logic [QUOTIENT_W-1:0] magnitude
	);
		logic signed [31:0] tmp32;
		begin
			if (sign_bit == 1'b0) begin
				if (magnitude > 54'd2147483647) begin
					saturate_q15_16 = 32'sh7FFF_FFFF;
				end
				else begin
					saturate_q15_16 = $signed(magnitude[31:0]);
				end
			end
			else begin
				if (magnitude >= 54'd2147483648) begin
					saturate_q15_16 = 32'sh8000_0000;
				end
				else begin
					tmp32 = $signed(magnitude[31:0]);
					saturate_q15_16 = -tmp32;
				end
			end
		end
	endfunction

	// -------------------------------------------------------------------------
	// Delay variables
	// -------------------------------------------------------------------------
	logic signed [15:0] angular_derivative_column_in_d [0:6];
	logic angular_derivative_orientation_in_d;

	always_ff @(posedge clk) begin : Delays
		// Angular derivatives are one cycle to early compared to the spatial derivatives, so we wait one clock cycle
		angular_derivative_column_in_d[0] <= angular_derivative_column_in[0];
		angular_derivative_column_in_d[1] <= angular_derivative_column_in[1];
		angular_derivative_column_in_d[2] <= angular_derivative_column_in[2];
		angular_derivative_column_in_d[3] <= angular_derivative_column_in[3];
		angular_derivative_column_in_d[4] <= angular_derivative_column_in[4];
		angular_derivative_column_in_d[5] <= angular_derivative_column_in[5];
		angular_derivative_column_in_d[6] <= angular_derivative_column_in[6];

		angular_derivative_orientation_in_d <= angular_derivative_orientation_in;
	end

	// -------------------------------------------------------------------------
	// Spatial derivative computations
	// -------------------------------------------------------------------------
	logic [14:0] epi_column_in_nm3 [0:6];
	logic [14:0] epi_column_in_nm2 [0:6];
	logic [14:0] epi_column_in_nm1 [0:6];

	logic signed [15:0] spatial_derivatives [0:6];

	logic                    spatial_derivatives_valid      = 1'b0;
	logic [IMAGE_DIM_BS-1:0] spatial_derivatives_row_idx    = '0;
	logic [IMAGE_DIM_BS-1:0] spatial_derivatives_column_idx = '0;

	always_ff @(posedge clk) begin : Spatial_Derivative_Computations
		if (epi_valid_in) begin
			epi_column_in_nm1[0] <= epi_column_in[1];
			epi_column_in_nm1[1] <= epi_column_in[2];
			epi_column_in_nm1[2] <= epi_column_in[3];
			epi_column_in_nm1[3] <= epi_column_in[4];
			epi_column_in_nm1[4] <= epi_column_in[5];
			epi_column_in_nm1[5] <= epi_column_in[6];
			epi_column_in_nm1[6] <= epi_column_in[7];

			epi_column_in_nm2[0] <= epi_column_in_nm1[0];
			epi_column_in_nm2[1] <= epi_column_in_nm1[1];
			epi_column_in_nm2[2] <= epi_column_in_nm1[2];
			epi_column_in_nm2[3] <= epi_column_in_nm1[3];
			epi_column_in_nm2[4] <= epi_column_in_nm1[4];
			epi_column_in_nm2[5] <= epi_column_in_nm1[5];
			epi_column_in_nm2[6] <= epi_column_in_nm1[6];

			epi_column_in_nm3[0] <= epi_column_in_nm2[0];
			epi_column_in_nm3[1] <= epi_column_in_nm2[1];
			epi_column_in_nm3[2] <= epi_column_in_nm2[2];
			epi_column_in_nm3[3] <= epi_column_in_nm2[3];
			epi_column_in_nm3[4] <= epi_column_in_nm2[4];
			epi_column_in_nm3[5] <= epi_column_in_nm2[5];
			epi_column_in_nm3[6] <= epi_column_in_nm2[6];
		end

		spatial_derivatives[0] <= ($signed({1'b0, epi_column_in_nm1[0]}) - $signed({1'b0, epi_column_in_nm3[0]})) >>> 1;
		spatial_derivatives[1] <= ($signed({1'b0, epi_column_in_nm1[1]}) - $signed({1'b0, epi_column_in_nm3[1]})) >>> 1;
		spatial_derivatives[2] <= ($signed({1'b0, epi_column_in_nm1[2]}) - $signed({1'b0, epi_column_in_nm3[2]})) >>> 1;
		spatial_derivatives[3] <= ($signed({1'b0, epi_column_in_nm1[3]}) - $signed({1'b0, epi_column_in_nm3[3]})) >>> 1;
		spatial_derivatives[4] <= ($signed({1'b0, epi_column_in_nm1[4]}) - $signed({1'b0, epi_column_in_nm3[4]})) >>> 1;
		spatial_derivatives[5] <= ($signed({1'b0, epi_column_in_nm1[5]}) - $signed({1'b0, epi_column_in_nm3[5]})) >>> 1;
		spatial_derivatives[6] <= ($signed({1'b0, epi_column_in_nm1[6]}) - $signed({1'b0, epi_column_in_nm3[6]})) >>> 1;

		spatial_derivatives_valid      <= (angular_derivative_column_idx_in != 0) && (angular_derivative_column_idx_in != IMAGE_DIM-1) && angular_derivative_valid_in;
		spatial_derivatives_row_idx    <= angular_derivative_row_idx_in;
		spatial_derivatives_column_idx <= angular_derivative_column_idx_in;
	end

	// -------------------------------------------------------------------------
	// Product and sum stage
	// -------------------------------------------------------------------------
	logic signed [31:0] uv_0 = 0;
	logic signed [31:0] uv_1 = 0;
	logic signed [31:0] uv_2 = 0;
	logic signed [31:0] uv_3 = 0;
	logic signed [31:0] uv_4 = 0;
	logic signed [31:0] uv_5 = 0;
	logic signed [31:0] uv_6 = 0;

	logic signed [31:0] uu_0 = 0;
	logic signed [31:0] uu_1 = 0;
	logic signed [31:0] uu_2 = 0;
	logic signed [31:0] uu_3 = 0;
	logic signed [31:0] uu_4 = 0;
	logic signed [31:0] uu_5 = 0;
	logic signed [31:0] uu_6 = 0;

	logic signed [37:0] sum_uv = 0;
	logic signed [37:0] sum_uu = 0;

	logic                    prod_valid        = 1'b0;
	logic [IMAGE_DIM_BS-1:0] prod_row_idx      = '0;
	logic [IMAGE_DIM_BS-1:0] prod_column_idx   = '0;
	logic                    prod_orientation  = 1'b0;

	logic                    sum_valid         = 1'b0;
	logic [IMAGE_DIM_BS-1:0] sum_row_idx       = '0;
	logic [IMAGE_DIM_BS-1:0] sum_column_idx    = '0;
	logic                    sum_orientation   = 1'b0;

	always_ff @(posedge clk) begin : Product_And_Sum_Computations
		uv_0 <= (angular_derivative_column_in_d[0] * spatial_derivatives[0]);
		uv_1 <= (angular_derivative_column_in_d[1] * spatial_derivatives[1]);
		uv_2 <= (angular_derivative_column_in_d[2] * spatial_derivatives[2]);
		uv_3 <= (angular_derivative_column_in_d[3] * spatial_derivatives[3]);
		uv_4 <= (angular_derivative_column_in_d[4] * spatial_derivatives[4]);
		uv_5 <= (angular_derivative_column_in_d[5] * spatial_derivatives[5]);
		uv_6 <= (angular_derivative_column_in_d[6] * spatial_derivatives[6]);

		uu_0 <= (angular_derivative_column_in_d[0] * angular_derivative_column_in_d[0]);
		uu_1 <= (angular_derivative_column_in_d[1] * angular_derivative_column_in_d[1]);
		uu_2 <= (angular_derivative_column_in_d[2] * angular_derivative_column_in_d[2]);
		uu_3 <= (angular_derivative_column_in_d[3] * angular_derivative_column_in_d[3]);
		uu_4 <= (angular_derivative_column_in_d[4] * angular_derivative_column_in_d[4]);
		uu_5 <= (angular_derivative_column_in_d[5] * angular_derivative_column_in_d[5]);
		uu_6 <= (angular_derivative_column_in_d[6] * angular_derivative_column_in_d[6]);

		sum_uv <= uv_0 + uv_1 + uv_2 + uv_3 + uv_4 + uv_5 + uv_6;
		sum_uu <= uu_0 + uu_1 + uu_2 + uu_3 + uu_4 + uu_5 + uu_6;

		prod_valid       <= spatial_derivatives_valid;
		prod_orientation <= angular_derivative_orientation_in_d;

		if (angular_derivative_orientation_in_d == 1'b0) begin
			prod_row_idx    <= spatial_derivatives_row_idx;
			prod_column_idx <= spatial_derivatives_column_idx;
		end
		else begin
			prod_row_idx    <= spatial_derivatives_column_idx;
			prod_column_idx <= spatial_derivatives_row_idx;
		end

		sum_valid       <= prod_valid;
		sum_row_idx     <= prod_row_idx;
		sum_column_idx  <= prod_column_idx;
		sum_orientation <= prod_orientation;
	end

	// -------------------------------------------------------------------------
	// Fully pipelined exact divider
	// -------------------------------------------------------------------------
	logic [DIVIDEND_W-1:0] dividend_pipe    [0:DIV_STAGES];
	logic [DIVISOR_W-1:0]  divisor_pipe     [0:DIV_STAGES];
	logic [DIVISOR_W:0]    remainder_pipe   [0:DIV_STAGES];
	logic [QUOTIENT_W-1:0] quotient_pipe    [0:DIV_STAGES];

	logic                  valid_pipe       [0:DIV_STAGES];
	logic                  sign_pipe        [0:DIV_STAGES];
	logic                  div_zero_pipe    [0:DIV_STAGES];

	logic [IMAGE_DIM_BS-1:0] row_idx_pipe      [0:DIV_STAGES];
	logic [IMAGE_DIM_BS-1:0] column_idx_pipe   [0:DIV_STAGES];
	logic                    orientation_pipe  [0:DIV_STAGES];

	// Stage 0 load
	always_ff @(posedge clk) begin : Divider_Stage0_Load
		valid_pipe[0]       <= sum_valid;
		sign_pipe[0]        <= sum_uv[37];
		div_zero_pipe[0]    <= (sum_uu == 0);
		row_idx_pipe[0]     <= sum_row_idx;
		column_idx_pipe[0]  <= sum_column_idx;
		orientation_pipe[0] <= sum_orientation;

		if (sum_valid && (sum_uu != 0)) begin
			dividend_pipe[0]  <= {abs38(sum_uv), 16'd0};
			divisor_pipe[0]   <= sum_uu[37:0];
			remainder_pipe[0] <= '0;
			quotient_pipe[0]  <= '0;
		end
		else begin
			dividend_pipe[0]  <= '0;
			divisor_pipe[0]   <= '0;
			remainder_pipe[0] <= '0;
			quotient_pipe[0]  <= '0;
		end
	end

	genvar s;
	generate
		for (s = 0; s < DIV_STAGES; s = s + 1) begin : Divider_Pipeline
			always_ff @(posedge clk) begin
				valid_pipe[s+1]       <= valid_pipe[s];
				sign_pipe[s+1]        <= sign_pipe[s];
				div_zero_pipe[s+1]    <= div_zero_pipe[s];
				row_idx_pipe[s+1]     <= row_idx_pipe[s];
				column_idx_pipe[s+1]  <= column_idx_pipe[s];
				orientation_pipe[s+1] <= orientation_pipe[s];
				divisor_pipe[s+1]     <= divisor_pipe[s];

				if (!valid_pipe[s] || div_zero_pipe[s]) begin
					dividend_pipe[s+1]  <= '0;
					remainder_pipe[s+1] <= '0;
					quotient_pipe[s+1]  <= '0;
				end
				else begin
					if ({remainder_pipe[s][DIVISOR_W-1:0], dividend_pipe[s][DIVIDEND_W-1]} >= {1'b0, divisor_pipe[s]}) begin
						remainder_pipe[s+1] <= {remainder_pipe[s][DIVISOR_W-1:0], dividend_pipe[s][DIVIDEND_W-1]} - {1'b0, divisor_pipe[s]};
						quotient_pipe[s+1]  <= {quotient_pipe[s][QUOTIENT_W-2:0], 1'b1};
					end
					else begin
						remainder_pipe[s+1] <= {remainder_pipe[s][DIVISOR_W-1:0], dividend_pipe[s][DIVIDEND_W-1]};
						quotient_pipe[s+1]  <= {quotient_pipe[s][QUOTIENT_W-2:0], 1'b0};
					end

					dividend_pipe[s+1] <= {dividend_pipe[s][DIVIDEND_W-2:0], 1'b0};
				end
			end
		end
	endgenerate

	// -------------------------------------------------------------------------
	// Output stage
	// -------------------------------------------------------------------------
	always_ff @(posedge clk) begin : Output_Stage
		disparity_valid_out      <= 1'b0;
		disparity_pixel_out      <= 32'sd0;
		disparity_row_idx_out    <= '0;
		disparity_column_idx_out <= '0;
		orientation_out          <= 1'b0;

		if (valid_pipe[DIV_STAGES]) begin
			disparity_valid_out      <= 1'b1;
			disparity_row_idx_out    <= row_idx_pipe[DIV_STAGES];
			disparity_column_idx_out <= column_idx_pipe[DIV_STAGES];
			orientation_out          <= orientation_pipe[DIV_STAGES];

			if (div_zero_pipe[DIV_STAGES]) begin
				disparity_pixel_out <= 32'sd0;
			end
			else begin
				disparity_pixel_out <= saturate_q15_16(
					sign_pipe[DIV_STAGES],
					quotient_pipe[DIV_STAGES]
				);
			end
		end
	end

endmodule