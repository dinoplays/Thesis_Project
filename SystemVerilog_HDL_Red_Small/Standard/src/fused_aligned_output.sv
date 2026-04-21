module fused_aligned_output #(
	parameter int unsigned IMAGE_DIM    = 128
)(
    input  wire                                   clk,
	input  wire                                   confidence_valid_in,
	input  wire [14:0]                            confidence_pixel_in,
	input  wire [$clog2(IMAGE_DIM)-1:0]           confidence_row_idx_in,
	input  wire [$clog2(IMAGE_DIM)-1:0]           confidence_column_idx_in,
	input  wire                                   confidence_orientation_in,

	input  wire                                   disparity_valid_in,
	input  wire [31:0]                            disparity_pixel_in,
	input  wire [$clog2(IMAGE_DIM)-1:0]           disparity_row_idx_in,
	input  wire [$clog2(IMAGE_DIM)-1:0]           disparity_column_idx_in,
	input  wire                                   disparity_orientation_in,

	input  wire                                   shared_banks_available,

	output logic                                  shared_we [0:3],
	output logic [((2*$clog2(IMAGE_DIM))-1):0]    shared_wr_addr [0:3],
	output logic [14:0]                           shared_wr_data [0:3],
	output logic [((2*$clog2(IMAGE_DIM))-1):0]    shared_rd_addr [0:3],
	input  wire [14:0]                            shared_rd_data [0:3],

	output logic                                  solf_out,
	output logic                                  eolf_out,
	output logic                                  pixel_valid_out,
	output logic [$clog2(IMAGE_DIM)-1:0]          row_idx_out,
	output logic [$clog2(IMAGE_DIM)-1:0]          column_idx_out,
	output logic [14:0]                           confidence_pixel_bit_data,
	output logic [23:0]                           weighted_disparity_pixel_bit_data
);

	localparam int unsigned ADDR_W = 2 * $clog2(IMAGE_DIM);
	localparam int unsigned IMAGE_LAST_INT = IMAGE_DIM - 1;
	localparam logic [$clog2(IMAGE_DIM)-1:0] LAST_VALID_PIXEL = IMAGE_LAST_INT[$clog2(IMAGE_DIM)-1:0];

	localparam logic [$clog2(IMAGE_DIM)-1:0] TRIM_PIXELS   = 4;
	localparam logic [$clog2(IMAGE_DIM)-1:0] MAX_VALID_IDX = LAST_VALID_PIXEL - TRIM_PIXELS;

	localparam int unsigned DIVIDEND_W = 40;
	localparam int unsigned DIVISOR_W  = 16;
	localparam int unsigned QUOTIENT_W = 40;
	localparam int unsigned DIV_STAGES = DIVIDEND_W;

	function automatic [ADDR_W-1:0] addr_row_col(
		input logic [$clog2(IMAGE_DIM)-1:0] row_i,
		input logic [$clog2(IMAGE_DIM)-1:0] col_i
	);
		begin
			addr_row_col = {row_i, col_i};
		end
	endfunction

	function automatic [14:0] sat_u15_sum(
		input logic [14:0] a,
		input logic [14:0] b
	);
		logic [15:0] tmp;
		begin
			tmp = {1'b0, a} + {1'b0, b};
			if (tmp[15]) begin
				sat_u15_sum = 15'h7FFF;
			end
			else begin
				sat_u15_sum = tmp[14:0];
			end
		end
	endfunction

	function automatic logic signed [23:0] q15_16_to_q12_12_sat(
		input logic signed [31:0] x
	);
		logic signed [31:0] shifted;
		begin
			shifted = x / 16;
			if (shifted > 32'sd8388607) begin
				q15_16_to_q12_12_sat = 24'sh7F_FFFF;
			end
			else if (shifted < -32'sd8388608) begin
				q15_16_to_q12_12_sat = 24'sh80_0000;
			end
			else begin
				q15_16_to_q12_12_sat = shifted[23:0];
			end
		end
	endfunction

	function automatic logic [DIVIDEND_W-1:0] abs40(
		input logic signed [39:0] x
	);
		begin
			if (x < 0) begin
				abs40 = $unsigned(-x);
			end
			else begin
				abs40 = $unsigned(x);
			end
		end
	endfunction

	function automatic logic signed [23:0] saturate_q12_12_from_sign_mag(
		input logic                  sign_bit,
		input logic [QUOTIENT_W-1:0] magnitude
	);
		logic signed [23:0] tmp24;
		begin
			if (sign_bit == 1'b0) begin
				if (magnitude > 40'd8388607) begin
					saturate_q12_12_from_sign_mag = 24'sh7F_FFFF;
				end
				else begin
					saturate_q12_12_from_sign_mag = $signed(magnitude[23:0]);
				end
			end
			else begin
				if (magnitude >= 40'd8388608) begin
					saturate_q12_12_from_sign_mag = 24'sh80_0000;
				end
				else begin
					tmp24 = $signed(magnitude[23:0]);
					saturate_q12_12_from_sign_mag = -tmp24;
				end
			end
		end
	endfunction

	// ---------------------------------------------------------------------
	// Direct converted disparity input
	// ---------------------------------------------------------------------
	logic signed [23:0] disparity_q12_12_in;
	assign disparity_q12_12_in = q15_16_to_q12_12_sat($signed(disparity_pixel_in));

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
	logic                    	  fuse_req_d            = 1'b0;
	logic [$clog2(IMAGE_DIM)-1:0] fuse_row_idx_d        = '0;
	logic [$clog2(IMAGE_DIM)-1:0] fuse_column_idx_d     = '0;
	logic signed [23:0]      	  v_disp_q12_12_d       = '0;
	logic                    	  v_conf_bypass_d       = 1'b0;
	logic [14:0]             	  v_conf_bypass_pixel_d = '0;

	// ---------------------------------------------------------------------
	// Stage 2:
	// RAM latency matching
	// ---------------------------------------------------------------------
	logic                    	  fuse_req_2d_pre            = 1'b0;
	logic [$clog2(IMAGE_DIM)-1:0] fuse_row_idx_2d_pre        = '0;
	logic [$clog2(IMAGE_DIM)-1:0] fuse_column_idx_2d_pre     = '0;
	logic signed [23:0]      	  v_disp_q12_12_2d_pre       = '0;
	logic                    	  v_conf_bypass_2d_pre       = '0;
	logic [14:0]             	  v_conf_bypass_pixel_2d_pre = '0;

	// ---------------------------------------------------------------------
	// Stage 3:
	// Gather RAM outputs
	// ---------------------------------------------------------------------
	logic                    	  fuse_pair_valid_d          = 1'b0;
	logic [$clog2(IMAGE_DIM)-1:0] fuse_row_idx_2d            = '0;
	logic [$clog2(IMAGE_DIM)-1:0] fuse_column_idx_2d         = '0;
	logic [14:0]             	  conf_h_2d                  = '0;
	logic [14:0]             	  conf_v_2d                  = '0;
	logic signed [23:0]      	  disp_h_2d                  = '0;
	logic signed [23:0]      	  disp_v_2d                  = '0;
	logic                    	  fused_pixel_inside_crop_2d = '0;

	// ---------------------------------------------------------------------
	// Stage 4:
	// Operand alignment register
	// ---------------------------------------------------------------------
	logic                    	  fuse_pair_valid_3r          = 1'b0;
	logic [$clog2(IMAGE_DIM)-1:0] fuse_row_idx_3r            = '0;
	logic [$clog2(IMAGE_DIM)-1:0] fuse_column_idx_3r         = '0;
	logic [14:0]             	  conf_h_3r                  = '0;
	logic [14:0]             	  conf_v_3r                  = '0;
	logic signed [23:0]      	  disp_h_3r                  = '0;
	logic signed [23:0]      	  disp_v_3r                  = '0;
	logic                    	  fused_pixel_inside_crop_3r = '0;

	// ---------------------------------------------------------------------
	// Stage 5:
	// Split disparity into halves
	// ---------------------------------------------------------------------
	logic                    	  fuse_pair_valid_4d   = 1'b0;
	logic [$clog2(IMAGE_DIM)-1:0] fuse_row_idx_4d      = '0;
	logic [$clog2(IMAGE_DIM)-1:0] fuse_column_idx_4d   = '0;

	logic [11:0]             disp_h_lo_4d         = '0;
	logic signed [11:0]      disp_h_hi_4d         = '0;
	logic [11:0]             disp_v_lo_4d         = '0;
	logic signed [11:0]      disp_v_hi_4d         = '0;

	logic [14:0]             conf_h_4d            = '0;
	logic [14:0]             conf_v_4d            = '0;
	logic [14:0]             conf_sum_4d          = '0;
	logic [15:0]             weight_sum_4d        = '0;
	logic                    crop_ok_4d           = 1'b0;

	// ---------------------------------------------------------------------
	// Stage 6:
	// 12x15 multipliers
	// ---------------------------------------------------------------------
	logic                    	  fuse_pair_valid_5d    = 1'b0;
	logic [$clog2(IMAGE_DIM)-1:0] fuse_row_idx_5d       = '0;
	logic [$clog2(IMAGE_DIM)-1:0] fuse_column_idx_5d    = '0;
	logic [14:0]             	  conf_sum_5d           = '0;
	logic [15:0]             	  weight_sum_5d         = '0;
	logic                    	  crop_ok_5d            = '0;

	logic [26:0]             weighted_term_h_lo_5d = '0;
	logic signed [27:0]      weighted_term_h_hi_5d = '0;
	logic [26:0]             weighted_term_v_lo_5d = '0;
	logic signed [27:0]      weighted_term_v_hi_5d = '0;

	// ---------------------------------------------------------------------
	// Stage 7:
	// Register cut after multipliers
	// ---------------------------------------------------------------------
	logic                    	  fuse_pair_valid_5r    = 1'b0;
	logic [$clog2(IMAGE_DIM)-1:0] fuse_row_idx_5r       = '0;
	logic [$clog2(IMAGE_DIM)-1:0] fuse_column_idx_5r    = '0;
	logic [14:0]             	  conf_sum_5r           = '0;
	logic [15:0]             	  weight_sum_5r         = '0;
	logic                    	  crop_ok_5r            = '0;

	logic [26:0]             weighted_term_h_lo_5r = '0;
	logic signed [27:0]      weighted_term_h_hi_5r = '0;
	logic [26:0]             weighted_term_v_lo_5r = '0;
	logic signed [27:0]      weighted_term_v_hi_5r = '0;

	// ---------------------------------------------------------------------
	// Stage 8:
	// Pre-align/sign-extend/shift terms before final recombine add
	// ---------------------------------------------------------------------
	logic                    	  fuse_pair_valid_5x       = 1'b0;
	logic [$clog2(IMAGE_DIM)-1:0] fuse_row_idx_5x          = '0;
	logic [$clog2(IMAGE_DIM)-1:0] fuse_column_idx_5x       = '0;
	logic [14:0]             	  conf_sum_5x              = '0;
	logic [15:0]             	  weight_sum_5x            = '0;
	logic                    	  crop_ok_5x               = '0;

	logic signed [38:0]      weighted_term_h_lo_5x    = '0;
	logic signed [38:0]      weighted_term_h_hi_sh_5x = '0;
	logic signed [38:0]      weighted_term_v_lo_5x    = '0;
	logic signed [38:0]      weighted_term_v_hi_sh_5x = '0;

	// ---------------------------------------------------------------------
	// Stage 9:
	// Recombine partial products
	// ---------------------------------------------------------------------
	logic                    	  fuse_pair_valid_6d   = 1'b0;
	logic [$clog2(IMAGE_DIM)-1:0] fuse_row_idx_6d      = '0;
	logic [$clog2(IMAGE_DIM)-1:0] fuse_column_idx_6d   = '0;
	logic [14:0]             	  conf_sum_6d          = '0;
	logic [15:0]             	  weight_sum_6d        = '0;
	logic signed [38:0]      	  weighted_term_h_6d   = '0;
	logic signed [38:0]      	  weighted_term_v_6d   = '0;
	logic                    	  crop_ok_6d           = '0;

	// ---------------------------------------------------------------------
	// Stage 10:
	// Numerator
	// ---------------------------------------------------------------------
	logic                    	  fuse_pair_valid_7d     = 1'b0;
	logic [$clog2(IMAGE_DIM)-1:0] fuse_row_idx_7d        = '0;
	logic [$clog2(IMAGE_DIM)-1:0] fuse_column_idx_7d     = '0;
	logic [14:0]             	  conf_sum_7d            = '0;
	logic [15:0]             	  weight_sum_7d          = '0;
	logic signed [39:0]      	  weighted_numerator_7d  = '0;
	logic                    	  crop_ok_7d             = '0;

	// ---------------------------------------------------------------------
	// Stage 11:
	// NEW register cut before divider load
	// ---------------------------------------------------------------------
	logic                    	  fuse_pair_valid_8d     = 1'b0;
	logic [$clog2(IMAGE_DIM)-1:0] fuse_row_idx_8d        = '0;
	logic [$clog2(IMAGE_DIM)-1:0] fuse_column_idx_8d     = '0;
	logic [14:0]             	  conf_sum_8d            = '0;
	logic [15:0]             	  weight_sum_8d          = '0;
	logic signed [39:0]      	  weighted_numerator_8d  = '0;
	logic                    	  crop_ok_8d             = '0;

	// ---------------------------------------------------------------------
	// Divider pipes
	// ---------------------------------------------------------------------
	logic [DIVIDEND_W-1:0] dividend_pipe     [0:DIV_STAGES];
	logic [DIVISOR_W-1:0]  divisor_pipe      [0:DIV_STAGES];
	logic [DIVISOR_W:0]    remainder_pipe    [0:DIV_STAGES];
	logic [QUOTIENT_W-1:0] quotient_pipe     [0:DIV_STAGES];

	logic                    	  valid_pipe       [0:DIV_STAGES];
	logic                    	  sign_pipe        [0:DIV_STAGES];
	logic                    	  div_zero_pipe    [0:DIV_STAGES];
	logic                    	  crop_ok_pipe     [0:DIV_STAGES];
	logic [$clog2(IMAGE_DIM)-1:0] row_idx_pipe     [0:DIV_STAGES];
	logic [$clog2(IMAGE_DIM)-1:0] column_idx_pipe  [0:DIV_STAGES];
	logic [14:0]             	  conf_sum_pipe    [0:DIV_STAGES];

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
				shared_wr_data[2] <= disparity_q12_12_in[14:0];

				shared_we[3]      <= 1'b1;
				shared_wr_addr[3] <= disp_addr_in;
				shared_wr_data[3] <= {6'd0, disparity_q12_12_in[23:15]};
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
		v_disp_q12_12_d       <= '0;

		if (shared_banks_available &&
		    disparity_valid_in &&
		    (disparity_orientation_in == 1'b1)) begin
			fuse_req_d        <= 1'b1;
			fuse_row_idx_d    <= disparity_row_idx_in;
			fuse_column_idx_d <= disparity_column_idx_in;
			v_disp_q12_12_d   <= disparity_q12_12_in;

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
	// Delay for RAM
	// ---------------------------------------------------------------------
	always_ff @(posedge clk) begin : Fusion_Request_Delay_For_RAM
		fuse_req_2d_pre            <= fuse_req_d;
		fuse_row_idx_2d_pre        <= fuse_row_idx_d;
		fuse_column_idx_2d_pre     <= fuse_column_idx_d;
		v_disp_q12_12_2d_pre       <= v_disp_q12_12_d;
		v_conf_bypass_2d_pre       <= v_conf_bypass_d;
		v_conf_bypass_pixel_2d_pre <= v_conf_bypass_pixel_d;
	end

	// ---------------------------------------------------------------------
	// Stage 3:
	// Gather RAM outputs
	// ---------------------------------------------------------------------
	always_ff @(posedge clk) begin : Gather_Fusion_Operands
		fuse_pair_valid_d          <= 1'b0;
		fused_pixel_inside_crop_2d <= 1'b0;
		fuse_row_idx_2d            <= '0;
		fuse_column_idx_2d         <= '0;
		conf_h_2d                  <= '0;
		conf_v_2d                  <= '0;
		disp_h_2d                  <= '0;
		disp_v_2d                  <= '0;

		if (fuse_req_2d_pre) begin
			fuse_pair_valid_d  <= 1'b1;
			fuse_row_idx_2d    <= fuse_row_idx_2d_pre;
			fuse_column_idx_2d <= fuse_column_idx_2d_pre;

			conf_h_2d <= shared_rd_data[0];

			if (v_conf_bypass_2d_pre) begin
				conf_v_2d <= v_conf_bypass_pixel_2d_pre;
			end
			else begin
				conf_v_2d <= shared_rd_data[1];
			end

			disp_h_2d <= $signed({shared_rd_data[3][8:0], shared_rd_data[2]});
			disp_v_2d <= v_disp_q12_12_2d_pre;

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
	// Split disparity, keep full confidence
	// ---------------------------------------------------------------------
	always_ff @(posedge clk) begin : Register_Split_Multiply_Inputs
		fuse_pair_valid_4d <= 1'b0;
		fuse_row_idx_4d    <= '0;
		fuse_column_idx_4d <= '0;

		disp_h_lo_4d       <= '0;
		disp_h_hi_4d       <= '0;
		disp_v_lo_4d       <= '0;
		disp_v_hi_4d       <= '0;

		conf_h_4d          <= '0;
		conf_v_4d          <= '0;
		conf_sum_4d        <= '0;
		weight_sum_4d      <= '0;
		crop_ok_4d         <= 1'b0;

		if (fuse_pair_valid_3r) begin
			fuse_pair_valid_4d <= 1'b1;
			fuse_row_idx_4d    <= fuse_row_idx_3r;
			fuse_column_idx_4d <= fuse_column_idx_3r;

			disp_h_lo_4d <= disp_h_3r[11:0];
			disp_h_hi_4d <= disp_h_3r[23:12];
			disp_v_lo_4d <= disp_v_3r[11:0];
			disp_v_hi_4d <= disp_v_3r[23:12];

			conf_h_4d     <= conf_h_3r;
			conf_v_4d     <= conf_v_3r;
			conf_sum_4d   <= sat_u15_sum(conf_h_3r, conf_v_3r);
			weight_sum_4d <= {1'b0, conf_h_3r} + {1'b0, conf_v_3r};
			crop_ok_4d    <= fused_pixel_inside_crop_3r;
		end
	end

	// ---------------------------------------------------------------------
	// Stage 6:
	// Smaller 12x15 multipliers
	// ---------------------------------------------------------------------
	always_ff @(posedge clk) begin : Compute_Smaller_Partial_Products
		fuse_pair_valid_5d    <= 1'b0;
		fuse_row_idx_5d       <= '0;
		fuse_column_idx_5d    <= '0;
		conf_sum_5d           <= '0;
		weight_sum_5d         <= '0;
		weighted_term_h_lo_5d <= '0;
		weighted_term_h_hi_5d <= '0;
		weighted_term_v_lo_5d <= '0;
		weighted_term_v_hi_5d <= '0;
		crop_ok_5d            <= '0;

		if (fuse_pair_valid_4d) begin
			fuse_pair_valid_5d    <= 1'b1;
			fuse_row_idx_5d       <= fuse_row_idx_4d;
			fuse_column_idx_5d    <= fuse_column_idx_4d;
			conf_sum_5d           <= conf_sum_4d;
			weight_sum_5d         <= weight_sum_4d;

			weighted_term_h_lo_5d <= disp_h_lo_4d * conf_h_4d;
			weighted_term_h_hi_5d <= $signed(disp_h_hi_4d) * $signed({1'b0, conf_h_4d});

			weighted_term_v_lo_5d <= disp_v_lo_4d * conf_v_4d;
			weighted_term_v_hi_5d <= $signed(disp_v_hi_4d) * $signed({1'b0, conf_v_4d});

			crop_ok_5d            <= crop_ok_4d;
		end
	end

	// ---------------------------------------------------------------------
	// Stage 7:
	// Register cut after multipliers
	// ---------------------------------------------------------------------
	always_ff @(posedge clk) begin : Register_Partial_Product_Outputs
		fuse_pair_valid_5r    <= 1'b0;
		fuse_row_idx_5r       <= '0;
		fuse_column_idx_5r    <= '0;
		conf_sum_5r           <= '0;
		weight_sum_5r         <= '0;
		crop_ok_5r            <= '0;
		weighted_term_h_lo_5r <= '0;
		weighted_term_h_hi_5r <= '0;
		weighted_term_v_lo_5r <= '0;
		weighted_term_v_hi_5r <= '0;

		if (fuse_pair_valid_5d) begin
			fuse_pair_valid_5r    <= 1'b1;
			fuse_row_idx_5r       <= fuse_row_idx_5d;
			fuse_column_idx_5r    <= fuse_column_idx_5d;
			conf_sum_5r           <= conf_sum_5d;
			weight_sum_5r         <= weight_sum_5d;
			crop_ok_5r            <= crop_ok_5d;
			weighted_term_h_lo_5r <= weighted_term_h_lo_5d;
			weighted_term_h_hi_5r <= weighted_term_h_hi_5d;
			weighted_term_v_lo_5r <= weighted_term_v_lo_5d;
			weighted_term_v_hi_5r <= weighted_term_v_hi_5d;
		end
	end

	// ---------------------------------------------------------------------
	// Stage 8:
	// Pre-alignment/shift stage
	// ---------------------------------------------------------------------
	always_ff @(posedge clk) begin : Register_Aligned_Recombine_Terms
		fuse_pair_valid_5x       <= 1'b0;
		fuse_row_idx_5x          <= '0;
		fuse_column_idx_5x       <= '0;
		conf_sum_5x              <= '0;
		weight_sum_5x            <= '0;
		crop_ok_5x               <= '0;
		weighted_term_h_lo_5x    <= '0;
		weighted_term_h_hi_sh_5x <= '0;
		weighted_term_v_lo_5x    <= '0;
		weighted_term_v_hi_sh_5x <= '0;

		if (fuse_pair_valid_5r) begin
			fuse_pair_valid_5x       <= 1'b1;
			fuse_row_idx_5x          <= fuse_row_idx_5r;
			fuse_column_idx_5x       <= fuse_column_idx_5r;
			conf_sum_5x              <= conf_sum_5r;
			weight_sum_5x            <= weight_sum_5r;
			crop_ok_5x               <= crop_ok_5r;

			weighted_term_h_lo_5x    <= $signed({12'd0, weighted_term_h_lo_5r});
			weighted_term_h_hi_sh_5x <= ($signed({{11{weighted_term_h_hi_5r[27]}}, weighted_term_h_hi_5r}) * 4096);

			weighted_term_v_lo_5x    <= $signed({12'd0, weighted_term_v_lo_5r});
			weighted_term_v_hi_sh_5x <= ($signed({{11{weighted_term_v_hi_5r[27]}}, weighted_term_v_hi_5r}) * 4096);
		end
	end

	// ---------------------------------------------------------------------
	// Stage 9:
	// Recombine partial products
	// ---------------------------------------------------------------------
	always_ff @(posedge clk) begin : Recombine_Partial_Products
		fuse_pair_valid_6d <= 1'b0;
		fuse_row_idx_6d    <= '0;
		fuse_column_idx_6d <= '0;
		conf_sum_6d        <= '0;
		weight_sum_6d      <= '0;
		weighted_term_h_6d <= '0;
		weighted_term_v_6d <= '0;
		crop_ok_6d         <= '0;

		if (fuse_pair_valid_5x) begin
			fuse_pair_valid_6d <= 1'b1;
			fuse_row_idx_6d    <= fuse_row_idx_5x;
			fuse_column_idx_6d <= fuse_column_idx_5x;
			conf_sum_6d        <= conf_sum_5x;
			weight_sum_6d      <= weight_sum_5x;

			weighted_term_h_6d <= weighted_term_h_lo_5x + weighted_term_h_hi_sh_5x;
			weighted_term_v_6d <= weighted_term_v_lo_5x + weighted_term_v_hi_sh_5x;

			crop_ok_6d         <= crop_ok_5x;
		end
	end

	// ---------------------------------------------------------------------
	// Stage 10:
	// Numerator
	// ---------------------------------------------------------------------
	always_ff @(posedge clk) begin : Compute_Numerator
		fuse_pair_valid_7d    <= 1'b0;
		fuse_row_idx_7d       <= '0;
		fuse_column_idx_7d    <= '0;
		conf_sum_7d           <= '0;
		weight_sum_7d         <= '0;
		weighted_numerator_7d <= '0;
		crop_ok_7d            <= '0;

		if (fuse_pair_valid_6d) begin
			fuse_pair_valid_7d    <= 1'b1;
			fuse_row_idx_7d       <= fuse_row_idx_6d;
			fuse_column_idx_7d    <= fuse_column_idx_6d;
			conf_sum_7d           <= conf_sum_6d;
			weight_sum_7d         <= weight_sum_6d;
			weighted_numerator_7d <= weighted_term_h_6d + weighted_term_v_6d;
			crop_ok_7d            <= crop_ok_6d;
		end
	end

	// ---------------------------------------------------------------------
	// Stage 11:
	// Register cut before divider load
	// ---------------------------------------------------------------------
	always_ff @(posedge clk) begin : Register_Pre_Divider_Inputs
		fuse_pair_valid_8d    <= 1'b0;
		fuse_row_idx_8d       <= '0;
		fuse_column_idx_8d    <= '0;
		conf_sum_8d           <= '0;
		weight_sum_8d         <= '0;
		weighted_numerator_8d <= '0;
		crop_ok_8d            <= '0;

		if (fuse_pair_valid_7d) begin
			fuse_pair_valid_8d    <= 1'b1;
			fuse_row_idx_8d       <= fuse_row_idx_7d;
			fuse_column_idx_8d    <= fuse_column_idx_7d;
			conf_sum_8d           <= conf_sum_7d;
			weight_sum_8d         <= weight_sum_7d;
			weighted_numerator_8d <= weighted_numerator_7d;
			crop_ok_8d            <= crop_ok_7d;
		end
	end

	// ---------------------------------------------------------------------
	// Divider stage 0
	// ---------------------------------------------------------------------
	always_ff @(posedge clk) begin : Divider_Stage0_Load
		valid_pipe[0]    <= fuse_pair_valid_8d;
		sign_pipe[0]     <= weighted_numerator_8d[39];
		div_zero_pipe[0] <= (weight_sum_8d == 16'd0);
		crop_ok_pipe[0]  <= crop_ok_8d;

		row_idx_pipe[0]    <= fuse_row_idx_8d;
		column_idx_pipe[0] <= fuse_column_idx_8d;
		conf_sum_pipe[0]   <= conf_sum_8d;

		if (fuse_pair_valid_8d && (weight_sum_8d != 16'd0)) begin
			dividend_pipe[0]  <= abs40(weighted_numerator_8d);
			divisor_pipe[0]   <= weight_sum_8d;
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

	// ---------------------------------------------------------------------
	// Final output
	// ---------------------------------------------------------------------
	always_ff @(posedge clk) begin : Final_Output
		solf_out                          <= 1'b0;
		eolf_out                          <= 1'b0;
		pixel_valid_out                   <= 1'b0;
		row_idx_out                       <= '0;
		column_idx_out                    <= '0;
		confidence_pixel_bit_data         <= '0;
		weighted_disparity_pixel_bit_data <= '0;

		if (valid_pipe[DIV_STAGES] && crop_ok_pipe[DIV_STAGES] && !div_zero_pipe[DIV_STAGES]) begin
			pixel_valid_out                   <= 1'b1;
			row_idx_out                       <= row_idx_pipe[DIV_STAGES];
			column_idx_out                    <= column_idx_pipe[DIV_STAGES];
			confidence_pixel_bit_data         <= conf_sum_pipe[DIV_STAGES];
			weighted_disparity_pixel_bit_data <= saturate_q12_12_from_sign_mag(
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