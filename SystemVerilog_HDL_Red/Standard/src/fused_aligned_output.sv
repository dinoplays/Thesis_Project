module fused_aligned_output #(
	parameter int unsigned IMAGE_DIM    = 128,
	parameter int unsigned IMAGE_DIM_BS = 7
)(
    input  wire                                   clk,

	input  wire                                   confidence_valid_in,
	input  wire [9:0]                             confidence_pixel_in,
	input  wire [IMAGE_DIM_BS-1:0]                confidence_row_idx_in,
	input  wire [IMAGE_DIM_BS-1:0]                confidence_column_idx_in,
	input  wire                                   confidence_orientation_in,

	input  wire                                   disparity_valid_in,
	input  wire signed [15:0]                     disparity_pixel_in,
	input  wire [IMAGE_DIM_BS-1:0]                disparity_row_idx_in,
	input  wire [IMAGE_DIM_BS-1:0]                disparity_column_idx_in,
	input  wire                                   disparity_orientation_in,

	input  wire                                   shared_banks_available,

	output logic                                  shared_we [0:3],
	output logic [((2*IMAGE_DIM_BS)-1):0]         shared_wr_addr [0:3],
	output logic [14:0]                           shared_wr_data [0:3],
	output logic [((2*IMAGE_DIM_BS)-1):0]         shared_rd_addr [0:3],
	input  wire [14:0]                            shared_rd_data [0:3],

	output logic                                  solf_out,
	output logic                                  eolf_out,
	output logic                                  pixel_valid_out,
	output logic [IMAGE_DIM_BS-1:0]               row_idx_out,
	output logic [IMAGE_DIM_BS-1:0]               column_idx_out,
	output logic [9:0]                            confidence_pixel_bit_data,
	output logic signed [15:0]                    weighted_disparity_pixel_bit_data
);

	localparam int unsigned ADDR_W = 2 * IMAGE_DIM_BS;
	localparam int unsigned IMAGE_LAST_INT = IMAGE_DIM - 1;
	localparam logic [IMAGE_DIM_BS-1:0] LAST_VALID_PIXEL = IMAGE_LAST_INT[IMAGE_DIM_BS-1:0];

	localparam logic [IMAGE_DIM_BS-1:0] TRIM_PIXELS   = 4;
	localparam logic [IMAGE_DIM_BS-1:0] MAX_VALID_IDX = LAST_VALID_PIXEL - TRIM_PIXELS;

	localparam int unsigned DIVIDEND_W = 27;
	localparam int unsigned DIVISOR_W  = 11;
	localparam int unsigned QUOTIENT_W = DIVIDEND_W;
	localparam int unsigned DIV_STAGES = DIVIDEND_W;

	function automatic [ADDR_W-1:0] addr_row_col(
		input logic [IMAGE_DIM_BS-1:0] row_i,
		input logic [IMAGE_DIM_BS-1:0] col_i
	);
		begin
			addr_row_col = {row_i, col_i};
		end
	endfunction

	function automatic [9:0] sat_u10_sum(
		input logic [9:0] a,
		input logic [9:0] b
	);
		logic [10:0] tmp;
		begin
			tmp = a + b;
			if (tmp > 11'd1023) begin
				sat_u10_sum = 10'h3FF;
			end
			else begin
				sat_u10_sum = tmp[9:0];
			end
		end
	endfunction

	function automatic logic [DIVIDEND_W-1:0] abs27(
		input logic signed [26:0] x
	);
		begin
			if (x < 0) begin
				abs27 = $unsigned(-x);
			end
			else begin
				abs27 = $unsigned(x);
			end
		end
	endfunction

	function automatic logic signed [15:0] saturate_q8_8_from_sign_mag(
		input logic                    sign_bit,
		input logic [QUOTIENT_W-1:0]   magnitude
	);
		logic signed [15:0] tmp16;
		begin
			if (sign_bit == 1'b0) begin
				if (magnitude > 32'd32767) begin
					saturate_q8_8_from_sign_mag = 16'sh7FFF;
				end
				else begin
					saturate_q8_8_from_sign_mag = $signed(magnitude[15:0]);
				end
			end
			else begin
				if (magnitude >= 32'd32768) begin
					saturate_q8_8_from_sign_mag = 16'sh8000;
				end
				else begin
					tmp16 = $signed(magnitude[15:0]);
					saturate_q8_8_from_sign_mag = -tmp16;
				end
			end
		end
	endfunction

	// ---------------------------------------------------------------------
	// Shared address helpers
	// ---------------------------------------------------------------------
	logic [ADDR_W-1:0] conf_addr_in;
	logic [ADDR_W-1:0] disp_addr_in;

	assign conf_addr_in = addr_row_col(confidence_row_idx_in, confidence_column_idx_in);
	assign disp_addr_in = addr_row_col(disparity_row_idx_in, disparity_column_idx_in);

	// ---------------------------------------------------------------------
	// Stage 1:
	// Capture vertical disparity request metadata
	// ---------------------------------------------------------------------
	logic                    fuse_req_d            = 1'b0;
	logic [IMAGE_DIM_BS-1:0] fuse_row_idx_d        = '0;
	logic [IMAGE_DIM_BS-1:0] fuse_column_idx_d     = '0;
	logic signed [15:0]      v_disp_q8_8_d         = '0;
	logic                    v_conf_bypass_d       = 1'b0;
	logic [9:0]              v_conf_bypass_pixel_d = '0;

	// ---------------------------------------------------------------------
	// Stage 2:
	// RAM latency matching
	// ---------------------------------------------------------------------
	logic                    fuse_req_2d_pre            = 1'b0;
	logic [IMAGE_DIM_BS-1:0] fuse_row_idx_2d_pre        = '0;
	logic [IMAGE_DIM_BS-1:0] fuse_column_idx_2d_pre     = '0;
	logic signed [15:0]      v_disp_q8_8_2d_pre         = '0;
	logic                    v_conf_bypass_2d_pre       = '0;
	logic [9:0]              v_conf_bypass_pixel_2d_pre = '0;

	// ---------------------------------------------------------------------
	// Stage 3:
	// Gather RAM outputs
	// ---------------------------------------------------------------------
	logic                    fuse_pair_valid_d          = 1'b0;
	logic [IMAGE_DIM_BS-1:0] fuse_row_idx_2d            = '0;
	logic [IMAGE_DIM_BS-1:0] fuse_column_idx_2d         = '0;
	logic [9:0]              conf_h_2d                  = '0;
	logic [9:0]              conf_v_2d                  = '0;
	logic signed [15:0]      disp_h_2d                  = '0;
	logic signed [15:0]      disp_v_2d                  = '0;
	logic                    fused_pixel_inside_crop_2d = '0;

	// ---------------------------------------------------------------------
	// Stage 4:
	// Operand alignment register
	// ---------------------------------------------------------------------
	logic                    fuse_pair_valid_3r          = 1'b0;
	logic [IMAGE_DIM_BS-1:0] fuse_row_idx_3r            = '0;
	logic [IMAGE_DIM_BS-1:0] fuse_column_idx_3r         = '0;
	logic [9:0]              conf_h_3r                  = '0;
	logic [9:0]              conf_v_3r                  = '0;
	logic signed [15:0]      disp_h_3r                  = '0;
	logic signed [15:0]      disp_v_3r                  = '0;
	logic                    fused_pixel_inside_crop_3r = '0;

	// ---------------------------------------------------------------------
	// Stage 5:
	// Multiply disparity by confidence weights
	// ---------------------------------------------------------------------
	logic                    fuse_pair_valid_4d = 1'b0;
	logic [IMAGE_DIM_BS-1:0] fuse_row_idx_4d    = '0;
	logic [IMAGE_DIM_BS-1:0] fuse_column_idx_4d = '0;
	logic [9:0]              conf_sum_4d        = '0;
	logic [10:0]             weight_sum_4d      = '0;
	logic signed [25:0]      weighted_h_4d      = '0;
	logic signed [25:0]      weighted_v_4d      = '0;
	logic                    crop_ok_4d         = 1'b0;

	// ---------------------------------------------------------------------
	// Stage 6:
	// Numerator
	// ---------------------------------------------------------------------
	logic                    fuse_pair_valid_5d   = 1'b0;
	logic [IMAGE_DIM_BS-1:0] fuse_row_idx_5d      = '0;
	logic [IMAGE_DIM_BS-1:0] fuse_column_idx_5d   = '0;
	logic [9:0]              conf_sum_5d          = '0;
	logic [10:0]             weight_sum_5d        = '0;
	logic signed [26:0]      weighted_numerator_5d = '0;
	logic                    crop_ok_5d           = 1'b0;

	// ---------------------------------------------------------------------
	// Divider pipes
	// This restoring divider consumes the dividend MSB-first.
	// Therefore DIV_STAGES must equal DIVIDEND_W; using only 18 stages would
	// process only the upper 18 bits and lose useful quotient bits.
	// ---------------------------------------------------------------------
	logic [DIVIDEND_W-1:0] dividend_pipe     [0:DIV_STAGES];
	logic [DIVISOR_W-1:0]  divisor_pipe      [0:DIV_STAGES];
	logic [DIVISOR_W:0]    remainder_pipe    [0:DIV_STAGES];
	logic [QUOTIENT_W-1:0] quotient_pipe     [0:DIV_STAGES];

	logic                    valid_pipe        [0:DIV_STAGES];
	logic                    sign_pipe         [0:DIV_STAGES];
	logic                    div_zero_pipe     [0:DIV_STAGES];
	logic                    crop_ok_pipe      [0:DIV_STAGES];
	logic [IMAGE_DIM_BS-1:0] row_idx_pipe      [0:DIV_STAGES];
	logic [IMAGE_DIM_BS-1:0] column_idx_pipe   [0:DIV_STAGES];
	logic [9:0]              conf_sum_pipe     [0:DIV_STAGES];

	// ---------------------------------------------------------------------
	// Stage 0:
	// Shared storage I/O
	// ---------------------------------------------------------------------
	always_ff @(posedge clk) begin : Stage0_Register_Inputs_And_Storage_IO
		shared_we[0]      <= 1'b0;
		shared_we[1]      <= 1'b0;
		shared_we[2]      <= 1'b0;
		shared_we[3]      <= 1'b0;

		shared_wr_addr[0] <= '0;
		shared_wr_addr[1] <= '0;
		shared_wr_addr[2] <= '0;
		shared_wr_addr[3] <= '0;

		shared_wr_data[0] <= 15'd0;
		shared_wr_data[1] <= 15'd0;
		shared_wr_data[2] <= 15'd0;
		shared_wr_data[3] <= 15'd0;

		shared_rd_addr[0] <= '0;
		shared_rd_addr[1] <= '0;
		shared_rd_addr[2] <= '0;
		shared_rd_addr[3] <= '0;

		if (shared_banks_available) begin
			if (confidence_valid_in && (confidence_orientation_in == 1'b0)) begin
				shared_we[0]      <= 1'b1;
				shared_wr_addr[0] <= conf_addr_in;
				shared_wr_data[0] <= confidence_pixel_in;
			end

			if (confidence_valid_in && (confidence_orientation_in == 1'b1)) begin
				shared_we[1]      <= 1'b1;
				shared_wr_addr[1] <= conf_addr_in;
				shared_wr_data[1] <= confidence_pixel_in;
			end

			if (disparity_valid_in && (disparity_orientation_in == 1'b0)) begin
				shared_we[2]      <= 1'b1;
				shared_wr_addr[2] <= disp_addr_in;
				shared_wr_data[2] <= disparity_pixel_in[9:0];

				shared_we[3]      <= 1'b1;
				shared_wr_addr[3] <= disp_addr_in;
				shared_wr_data[3] <= disparity_pixel_in[15:10];
			end

			if (disparity_valid_in && (disparity_orientation_in == 1'b1)) begin
				shared_rd_addr[0] <= disp_addr_in;
				shared_rd_addr[1] <= disp_addr_in;
				shared_rd_addr[2] <= disp_addr_in;
				shared_rd_addr[3] <= disp_addr_in;
			end
		end
	end

	// ---------------------------------------------------------------------
	// Stage 1:
	// Capture vertical request
	// ---------------------------------------------------------------------
	always_ff @(posedge clk) begin : Fusion_Request_Capture
		fuse_req_d            <= 1'b0;
		v_conf_bypass_d       <= 1'b0;
		v_conf_bypass_pixel_d <= '0;
		fuse_row_idx_d        <= '0;
		fuse_column_idx_d     <= '0;
		v_disp_q8_8_d         <= '0;

		if (shared_banks_available &&
		    disparity_valid_in &&
		    (disparity_orientation_in == 1'b1)) begin
			fuse_req_d       <= 1'b1;
			fuse_row_idx_d    <= disparity_row_idx_in;
			fuse_column_idx_d <= disparity_column_idx_in;
			v_disp_q8_8_d     <= disparity_pixel_in;

			if (confidence_valid_in &&
			    (confidence_orientation_in == 1'b1) &&
			    (confidence_row_idx_in == disparity_row_idx_in) &&
			    (confidence_column_idx_in == disparity_column_idx_in)) begin
				v_conf_bypass_d       <= 1'b1;
				v_conf_bypass_pixel_d <= confidence_pixel_in;
			end
		end
	end

	// ---------------------------------------------------------------------
	// Stage 2:
	// RAM latency matching
	// ---------------------------------------------------------------------
	always_ff @(posedge clk) begin : Register_For_RAM_Latency
		fuse_req_2d_pre            <= fuse_req_d;
		fuse_row_idx_2d_pre        <= fuse_row_idx_d;
		fuse_column_idx_2d_pre     <= fuse_column_idx_d;
		v_disp_q8_8_2d_pre         <= v_disp_q8_8_d;
		v_conf_bypass_2d_pre       <= v_conf_bypass_d;
		v_conf_bypass_pixel_2d_pre <= v_conf_bypass_pixel_d;
	end

	// ---------------------------------------------------------------------
	// Stage 3:
	// Gather RAM outputs and crop flag
	// ---------------------------------------------------------------------
	always_ff @(posedge clk) begin : Gather_RAM_Outputs
		fuse_pair_valid_d <= 1'b0;
		fuse_row_idx_2d   <= '0;
		fuse_column_idx_2d <= '0;
		conf_h_2d <= '0;
		conf_v_2d <= '0;
		disp_h_2d <= '0;
		disp_v_2d <= '0;
		fused_pixel_inside_crop_2d <= 1'b0;

		if (fuse_req_2d_pre) begin
			fuse_pair_valid_d <= 1'b1;
			fuse_row_idx_2d    <= fuse_row_idx_2d_pre;
			fuse_column_idx_2d <= fuse_column_idx_2d_pre;

			conf_h_2d <= shared_rd_data[0][9:0];

			if (v_conf_bypass_2d_pre) begin
				conf_v_2d <= v_conf_bypass_pixel_2d_pre;
			end
			else begin
				conf_v_2d <= shared_rd_data[1][9:0];
			end

			disp_h_2d <= $signed({shared_rd_data[3][5:0], shared_rd_data[2][9:0]});
			disp_v_2d <= v_disp_q8_8_2d_pre;

			fused_pixel_inside_crop_2d <=
				(fuse_row_idx_2d_pre    >= TRIM_PIXELS)   &&
				(fuse_row_idx_2d_pre    <= MAX_VALID_IDX) &&
				(fuse_column_idx_2d_pre >= TRIM_PIXELS)   &&
				(fuse_column_idx_2d_pre <= MAX_VALID_IDX);
		end
	end

	// ---------------------------------------------------------------------
	// Stage 4:
	// Operand alignment register
	// ---------------------------------------------------------------------
	always_ff @(posedge clk) begin : Register_Gathered_Fusion_Operands
		fuse_pair_valid_3r         <= 1'b0;
		fuse_row_idx_3r            <= '0;
		fuse_column_idx_3r         <= '0;
		conf_h_3r                  <= '0;
		conf_v_3r                  <= '0;
		disp_h_3r                  <= '0;
		disp_v_3r                  <= '0;
		fused_pixel_inside_crop_3r <= 1'b0;

		if (fuse_pair_valid_d) begin
			fuse_pair_valid_3r         <= 1'b1;
			fuse_row_idx_3r            <= fuse_row_idx_2d;
			fuse_column_idx_3r         <= fuse_column_idx_2d;
			conf_h_3r                  <= conf_h_2d;
			conf_v_3r                  <= conf_v_2d;
			disp_h_3r                  <= disp_h_2d;
			disp_v_3r                  <= disp_v_2d;
			fused_pixel_inside_crop_3r <= fused_pixel_inside_crop_2d;
		end
	end

	// ---------------------------------------------------------------------
	// Stage 5:
	// Multiply disparity by confidence weights
	// ---------------------------------------------------------------------
	always_ff @(posedge clk) begin : Compute_Weighted_Terms
		fuse_pair_valid_4d <= 1'b0;
		fuse_row_idx_4d    <= '0;
		fuse_column_idx_4d <= '0;
		conf_sum_4d        <= '0;
		weight_sum_4d      <= '0;
		weighted_h_4d      <= '0;
		weighted_v_4d      <= '0;
		crop_ok_4d         <= 1'b0;

		if (fuse_pair_valid_3r) begin
			fuse_pair_valid_4d <= 1'b1;
			fuse_row_idx_4d    <= fuse_row_idx_3r;
			fuse_column_idx_4d <= fuse_column_idx_3r;
			conf_sum_4d        <= sat_u10_sum(conf_h_3r, conf_v_3r);
			weight_sum_4d      <=  conf_h_3r + conf_v_3r;
			weighted_h_4d      <= $signed(disp_h_3r) * $signed(conf_h_3r);
			weighted_v_4d      <= $signed(disp_v_3r) * $signed(conf_v_3r);
			crop_ok_4d         <= fused_pixel_inside_crop_3r;
		end
	end

	// ---------------------------------------------------------------------
	// Stage 6:
	// Numerator
	// ---------------------------------------------------------------------
	always_ff @(posedge clk) begin : Compute_Numerator
		fuse_pair_valid_5d    <= 1'b0;
		fuse_row_idx_5d       <= '0;
		fuse_column_idx_5d    <= '0;
		conf_sum_5d           <= '0;
		weight_sum_5d         <= '0;
		weighted_numerator_5d <= '0;
		crop_ok_5d            <= 1'b0;

		if (fuse_pair_valid_4d) begin
			fuse_pair_valid_5d    <= 1'b1;
			fuse_row_idx_5d       <= fuse_row_idx_4d;
			fuse_column_idx_5d    <= fuse_column_idx_4d;
			conf_sum_5d           <= conf_sum_4d;
			weight_sum_5d         <= weight_sum_4d;
			weighted_numerator_5d <= $signed({weighted_h_4d[25], weighted_h_4d}) + $signed({weighted_v_4d[25], weighted_v_4d});
			crop_ok_5d            <= crop_ok_4d;
		end
	end

	// ---------------------------------------------------------------------
	// Divider stage 0
	// ---------------------------------------------------------------------
	always_ff @(posedge clk) begin : Divider_Stage0_Load
		valid_pipe[0]    <= fuse_pair_valid_5d;
		sign_pipe[0]     <= weighted_numerator_5d[26];
		div_zero_pipe[0] <= (weight_sum_5d == 11'd0);
		crop_ok_pipe[0]  <= crop_ok_5d;

		row_idx_pipe[0]    <= fuse_row_idx_5d;
		column_idx_pipe[0] <= fuse_column_idx_5d;
		conf_sum_pipe[0]   <= conf_sum_5d;

		if (fuse_pair_valid_5d && (weight_sum_5d != 11'd0)) begin
			dividend_pipe[0]  <= abs27(weighted_numerator_5d);
			divisor_pipe[0]   <= weight_sum_5d;
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
				valid_pipe[s+1]    <= valid_pipe[s];
				sign_pipe[s+1]     <= sign_pipe[s];
				div_zero_pipe[s+1] <= div_zero_pipe[s];
				crop_ok_pipe[s+1]  <= crop_ok_pipe[s];

				row_idx_pipe[s+1]    <= row_idx_pipe[s];
				column_idx_pipe[s+1] <= column_idx_pipe[s];
				conf_sum_pipe[s+1]   <= conf_sum_pipe[s];

				divisor_pipe[s+1] <= divisor_pipe[s];

				if (!valid_pipe[s] || div_zero_pipe[s]) begin
					dividend_pipe[s+1]  <= '0;
					remainder_pipe[s+1] <= '0;
					quotient_pipe[s+1]  <= '0;
				end
				else begin
					if ({remainder_pipe[s][DIVISOR_W-1:0], dividend_pipe[s][DIVIDEND_W-1]} >= divisor_pipe[s]) begin
						remainder_pipe[s+1] <= {remainder_pipe[s][DIVISOR_W-1:0], dividend_pipe[s][DIVIDEND_W-1]} - divisor_pipe[s];
						quotient_pipe[s+1]  <= (quotient_pipe[s][QUOTIENT_W-2:0] * 2) + 1;
					end
					else begin
						remainder_pipe[s+1] <= {remainder_pipe[s][DIVISOR_W-1:0], dividend_pipe[s][DIVIDEND_W-1]};
						quotient_pipe[s+1]  <= quotient_pipe[s][QUOTIENT_W-2:0] * 2;
					end

					dividend_pipe[s+1] <= dividend_pipe[s][DIVIDEND_W-2:0] * 2;
				end
			end
		end
	endgenerate

	// ---------------------------------------------------------------------
	// Final output
	// ---------------------------------------------------------------------
	always_ff @(posedge clk) begin : Final_Output
		solf_out                           <= 1'b0;
		eolf_out                           <= 1'b0;
		pixel_valid_out                    <= 1'b0;
		row_idx_out                        <= '0;
		column_idx_out                     <= '0;
		confidence_pixel_bit_data          <= '0;
		weighted_disparity_pixel_bit_data  <= '0;

		if (valid_pipe[DIV_STAGES] && crop_ok_pipe[DIV_STAGES] && !div_zero_pipe[DIV_STAGES]) begin
			pixel_valid_out                   <= 1'b1;
			row_idx_out                       <= row_idx_pipe[DIV_STAGES];
			column_idx_out                    <= column_idx_pipe[DIV_STAGES];
			confidence_pixel_bit_data         <= conf_sum_pipe[DIV_STAGES];
			weighted_disparity_pixel_bit_data <= saturate_q8_8_from_sign_mag(
				sign_pipe[DIV_STAGES],
				quotient_pipe[DIV_STAGES]
			);

			if ((row_idx_pipe[DIV_STAGES] == TRIM_PIXELS) &&
			    (column_idx_pipe[DIV_STAGES] == TRIM_PIXELS)) begin
				solf_out <= 1'b1;
			end

			if ((row_idx_pipe[DIV_STAGES] == MAX_VALID_IDX) &&
			    (column_idx_pipe[DIV_STAGES] == MAX_VALID_IDX)) begin
				eolf_out <= 1'b1;
			end
		end
	end

endmodule