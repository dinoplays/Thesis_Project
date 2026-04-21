module fused_aligned_output #(
	parameter int unsigned IMAGE_DIM    = 64,
	parameter int unsigned IMAGE_DIM_BS = 6
)(
    input  wire                                   clk,

	input  wire                                   confidence_valid_in,
	input  wire [14:0]                            confidence_pixel_in_red,
	input  wire [14:0]                            confidence_pixel_in_green,
	input  wire [14:0]                            confidence_pixel_in_blue,
	input  wire [IMAGE_DIM_BS-1:0]                confidence_row_idx_in,
	input  wire [IMAGE_DIM_BS-1:0]                confidence_column_idx_in,
	input  wire                                   confidence_orientation_in,

	input  wire                                   disparity_valid_in,
	input  wire [31:0]                            disparity_pixel_in_red,
	input  wire [31:0]                            disparity_pixel_in_green,
	input  wire [31:0]                            disparity_pixel_in_blue,
	input  wire [IMAGE_DIM_BS-1:0]                disparity_row_idx_in,
	input  wire [IMAGE_DIM_BS-1:0]                disparity_column_idx_in,
	input  wire                                   disparity_orientation_in,

	input  wire                                   shared_banks_available,

	output logic                                  shared_we [0:11],
	output logic [((2*IMAGE_DIM_BS)-1):0]         shared_wr_addr [0:11],
	output logic [14:0]                           shared_wr_data [0:11],
	output logic [((2*IMAGE_DIM_BS)-1):0]         shared_rd_addr [0:11],
	input  wire [14:0]                            shared_rd_data [0:11],

	output logic                                  solf_out,
	output logic                                  eolf_out,
	output logic                                  pixel_valid_out,
	output logic [IMAGE_DIM_BS-1:0]               row_idx_out,
	output logic [IMAGE_DIM_BS-1:0]               column_idx_out,
	output logic [14:0]                           confidence_pixel_bit_data,
	output logic [23:0]                           weighted_disparity_pixel_bit_data
);

	localparam int unsigned NUM_COLOURS = 3;
	localparam int unsigned BANKS_PER_COLOUR = 4;
	localparam int unsigned ADDR_W = 2 * IMAGE_DIM_BS;
	localparam int unsigned IMAGE_LAST_INT = IMAGE_DIM - 1;
	localparam logic [IMAGE_DIM_BS-1:0] LAST_VALID_PIXEL = IMAGE_LAST_INT[IMAGE_DIM_BS-1:0];

	localparam logic [IMAGE_DIM_BS-1:0] TRIM_PIXELS   = 4;
	localparam logic [IMAGE_DIM_BS-1:0] MAX_VALID_IDX = LAST_VALID_PIXEL - TRIM_PIXELS;

	localparam int unsigned NUMERATOR_W = 42;
	localparam int unsigned DIVIDEND_W  = NUMERATOR_W;
	localparam int unsigned DIVISOR_W   = 18;
	localparam int unsigned QUOTIENT_W  = NUMERATOR_W;
	localparam int unsigned DIV_STAGES  = DIVIDEND_W;

	function automatic int unsigned bank_base(
		input int unsigned colour_idx
	);
		begin
			bank_base = colour_idx * BANKS_PER_COLOUR;
		end
	endfunction

	function automatic [ADDR_W-1:0] addr_row_col(
		input logic [IMAGE_DIM_BS-1:0] row_i,
		input logic [IMAGE_DIM_BS-1:0] col_i
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

	function automatic [14:0] sat_u15_sum6(
		input logic [14:0] a0,
		input logic [14:0] a1,
		input logic [14:0] a2,
		input logic [14:0] a3,
		input logic [14:0] a4,
		input logic [14:0] a5
	);
		logic [14:0] s01;
		logic [14:0] s23;
		logic [14:0] s45;
		logic [14:0] s0123;
		begin
			s01 = sat_u15_sum(a0, a1);
			s23 = sat_u15_sum(a2, a3);
			s45 = sat_u15_sum(a4, a5);
			s0123 = sat_u15_sum(s01, s23);
			sat_u15_sum6 = sat_u15_sum(s0123, s45);
		end
	endfunction

	function automatic logic signed [23:0] q15_16_to_q12_12_sat(
		input logic signed [31:0] x
	);
		logic signed [31:0] shifted;
		begin
			shifted = x >>> 4;
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

	function automatic logic [DIVIDEND_W-1:0] abs_num(
		input logic signed [NUMERATOR_W-1:0] x
	);
		begin
			if (x < 0) begin
				abs_num = $unsigned(-x);
			end
			else begin
				abs_num = $unsigned(x);
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
				if (magnitude > QUOTIENT_W'(8388607)) begin
					saturate_q12_12_from_sign_mag = 24'sh7F_FFFF;
				end
				else begin
					saturate_q12_12_from_sign_mag = $signed(magnitude[23:0]);
				end
			end
			else begin
				if (magnitude >= QUOTIENT_W'(8388608)) begin
					saturate_q12_12_from_sign_mag = 24'sh80_0000;
				end
				else begin
					tmp24 = $signed(magnitude[23:0]);
					saturate_q12_12_from_sign_mag = -tmp24;
				end
			end
		end
	endfunction

	logic signed [23:0] disparity_q12_12_in_red;
	logic signed [23:0] disparity_q12_12_in_green;
	logic signed [23:0] disparity_q12_12_in_blue;

	assign disparity_q12_12_in_red   = q15_16_to_q12_12_sat($signed(disparity_pixel_in_red));
	assign disparity_q12_12_in_green = q15_16_to_q12_12_sat($signed(disparity_pixel_in_green));
	assign disparity_q12_12_in_blue  = q15_16_to_q12_12_sat($signed(disparity_pixel_in_blue));

	logic [ADDR_W-1:0] conf_addr_in;
	logic [ADDR_W-1:0] disp_addr_in;

	assign conf_addr_in = addr_row_col(confidence_row_idx_in, confidence_column_idx_in);
	assign disp_addr_in = addr_row_col(disparity_row_idx_in, disparity_column_idx_in);

	logic                    fuse_req_d            = 1'b0;
	logic [IMAGE_DIM_BS-1:0] fuse_row_idx_d        = '0;
	logic [IMAGE_DIM_BS-1:0] fuse_column_idx_d     = '0;

	logic signed [23:0]      v_disp_q12_12_d_red   = '0;
	logic signed [23:0]      v_disp_q12_12_d_green = '0;
	logic signed [23:0]      v_disp_q12_12_d_blue  = '0;

	logic                    v_conf_bypass_d_red   = 1'b0;
	logic                    v_conf_bypass_d_green = 1'b0;
	logic                    v_conf_bypass_d_blue  = 1'b0;

	logic [14:0]             v_conf_bypass_pixel_d_red   = '0;
	logic [14:0]             v_conf_bypass_pixel_d_green = '0;
	logic [14:0]             v_conf_bypass_pixel_d_blue  = '0;

	logic                    fuse_req_2d_pre            = 1'b0;
	logic [IMAGE_DIM_BS-1:0] fuse_row_idx_2d_pre        = '0;
	logic [IMAGE_DIM_BS-1:0] fuse_column_idx_2d_pre     = '0;

	logic signed [23:0]      v_disp_q12_12_2d_pre_red   = '0;
	logic signed [23:0]      v_disp_q12_12_2d_pre_green = '0;
	logic signed [23:0]      v_disp_q12_12_2d_pre_blue  = '0;

	logic                    v_conf_bypass_2d_pre_red   = 1'b0;
	logic                    v_conf_bypass_2d_pre_green = 1'b0;
	logic                    v_conf_bypass_2d_pre_blue  = 1'b0;

	logic [14:0]             v_conf_bypass_pixel_2d_pre_red   = '0;
	logic [14:0]             v_conf_bypass_pixel_2d_pre_green = '0;
	logic [14:0]             v_conf_bypass_pixel_2d_pre_blue  = '0;

	logic                    fuse_pair_valid_d          = 1'b0;
	logic [IMAGE_DIM_BS-1:0] fuse_row_idx_2d            = '0;
	logic [IMAGE_DIM_BS-1:0] fuse_column_idx_2d         = '0;

	logic [14:0]             conf_h_2d_red   = '0;
	logic [14:0]             conf_v_2d_red   = '0;
	logic [14:0]             conf_h_2d_green = '0;
	logic [14:0]             conf_v_2d_green = '0;
	logic [14:0]             conf_h_2d_blue  = '0;
	logic [14:0]             conf_v_2d_blue  = '0;

	logic signed [23:0]      disp_h_2d_red   = '0;
	logic signed [23:0]      disp_v_2d_red   = '0;
	logic signed [23:0]      disp_h_2d_green = '0;
	logic signed [23:0]      disp_v_2d_green = '0;
	logic signed [23:0]      disp_h_2d_blue  = '0;
	logic signed [23:0]      disp_v_2d_blue  = '0;

	logic                    fused_pixel_inside_crop_2d = 1'b0;

	logic                    fuse_pair_valid_3r          = 1'b0;
	logic [IMAGE_DIM_BS-1:0] fuse_row_idx_3r            = '0;
	logic [IMAGE_DIM_BS-1:0] fuse_column_idx_3r         = '0;

	logic [14:0]             conf_h_3r_red   = '0;
	logic [14:0]             conf_v_3r_red   = '0;
	logic [14:0]             conf_h_3r_green = '0;
	logic [14:0]             conf_v_3r_green = '0;
	logic [14:0]             conf_h_3r_blue  = '0;
	logic [14:0]             conf_v_3r_blue  = '0;

	logic signed [23:0]      disp_h_3r_red   = '0;
	logic signed [23:0]      disp_v_3r_red   = '0;
	logic signed [23:0]      disp_h_3r_green = '0;
	logic signed [23:0]      disp_v_3r_green = '0;
	logic signed [23:0]      disp_h_3r_blue  = '0;
	logic signed [23:0]      disp_v_3r_blue  = '0;

	logic                    fused_pixel_inside_crop_3r = 1'b0;

	logic                    fuse_pair_valid_4d   = 1'b0;
	logic [IMAGE_DIM_BS-1:0] fuse_row_idx_4d      = '0;
	logic [IMAGE_DIM_BS-1:0] fuse_column_idx_4d   = '0;

	logic [11:0]             disp_h_lo_4d_red   = '0;
	logic signed [11:0]      disp_h_hi_4d_red   = '0;
	logic [11:0]             disp_v_lo_4d_red   = '0;
	logic signed [11:0]      disp_v_hi_4d_red   = '0;

	logic [11:0]             disp_h_lo_4d_green = '0;
	logic signed [11:0]      disp_h_hi_4d_green = '0;
	logic [11:0]             disp_v_lo_4d_green = '0;
	logic signed [11:0]      disp_v_hi_4d_green = '0;

	logic [11:0]             disp_h_lo_4d_blue  = '0;
	logic signed [11:0]      disp_h_hi_4d_blue  = '0;
	logic [11:0]             disp_v_lo_4d_blue  = '0;
	logic signed [11:0]      disp_v_hi_4d_blue  = '0;

	logic [14:0]             conf_h_4d_red   = '0;
	logic [14:0]             conf_v_4d_red   = '0;
	logic [14:0]             conf_h_4d_green = '0;
	logic [14:0]             conf_v_4d_green = '0;
	logic [14:0]             conf_h_4d_blue  = '0;
	logic [14:0]             conf_v_4d_blue  = '0;

	logic [14:0]             conf_sum_4d    = '0;
	logic [DIVISOR_W-1:0]    weight_sum_4d  = '0;
	logic                    crop_ok_4d     = 1'b0;

	logic                    fuse_pair_valid_5d   = 1'b0;
	logic [IMAGE_DIM_BS-1:0] fuse_row_idx_5d      = '0;
	logic [IMAGE_DIM_BS-1:0] fuse_column_idx_5d   = '0;
	logic [14:0]             conf_sum_5d          = '0;
	logic [DIVISOR_W-1:0]    weight_sum_5d        = '0;
	logic                    crop_ok_5d           = 1'b0;

	logic [26:0]             weighted_term_h_lo_5d_red   = '0;
	logic signed [27:0]      weighted_term_h_hi_5d_red   = '0;
	logic [26:0]             weighted_term_v_lo_5d_red   = '0;
	logic signed [27:0]      weighted_term_v_hi_5d_red   = '0;

	logic [26:0]             weighted_term_h_lo_5d_green = '0;
	logic signed [27:0]      weighted_term_h_hi_5d_green = '0;
	logic [26:0]             weighted_term_v_lo_5d_green = '0;
	logic signed [27:0]      weighted_term_v_hi_5d_green = '0;

	logic [26:0]             weighted_term_h_lo_5d_blue  = '0;
	logic signed [27:0]      weighted_term_h_hi_5d_blue  = '0;
	logic [26:0]             weighted_term_v_lo_5d_blue  = '0;
	logic signed [27:0]      weighted_term_v_hi_5d_blue  = '0;

	logic                    fuse_pair_valid_5r   = 1'b0;
	logic [IMAGE_DIM_BS-1:0] fuse_row_idx_5r      = '0;
	logic [IMAGE_DIM_BS-1:0] fuse_column_idx_5r   = '0;
	logic [14:0]             conf_sum_5r          = '0;
	logic [DIVISOR_W-1:0]    weight_sum_5r        = '0;
	logic                    crop_ok_5r           = '0;

	logic [26:0]             weighted_term_h_lo_5r_red   = '0;
	logic signed [27:0]      weighted_term_h_hi_5r_red   = '0;
	logic [26:0]             weighted_term_v_lo_5r_red   = '0;
	logic signed [27:0]      weighted_term_v_hi_5r_red   = '0;

	logic [26:0]             weighted_term_h_lo_5r_green = '0;
	logic signed [27:0]      weighted_term_h_hi_5r_green = '0;
	logic [26:0]             weighted_term_v_lo_5r_green = '0;
	logic signed [27:0]      weighted_term_v_hi_5r_green = '0;

	logic [26:0]             weighted_term_h_lo_5r_blue  = '0;
	logic signed [27:0]      weighted_term_h_hi_5r_blue  = '0;
	logic [26:0]             weighted_term_v_lo_5r_blue  = '0;
	logic signed [27:0]      weighted_term_v_hi_5r_blue  = '0;

	logic                    fuse_pair_valid_5x   = 1'b0;
	logic [IMAGE_DIM_BS-1:0] fuse_row_idx_5x      = '0;
	logic [IMAGE_DIM_BS-1:0] fuse_column_idx_5x   = '0;
	logic [14:0]             conf_sum_5x          = '0;
	logic [DIVISOR_W-1:0]    weight_sum_5x        = '0;
	logic                    crop_ok_5x           = '0;

	logic signed [38:0]      weighted_term_h_lo_5x_red    = '0;
	logic signed [38:0]      weighted_term_h_hi_sh_5x_red = '0;
	logic signed [38:0]      weighted_term_v_lo_5x_red    = '0;
	logic signed [38:0]      weighted_term_v_hi_sh_5x_red = '0;

	logic signed [38:0]      weighted_term_h_lo_5x_green    = '0;
	logic signed [38:0]      weighted_term_h_hi_sh_5x_green = '0;
	logic signed [38:0]      weighted_term_v_lo_5x_green    = '0;
	logic signed [38:0]      weighted_term_v_hi_sh_5x_green = '0;

	logic signed [38:0]      weighted_term_h_lo_5x_blue    = '0;
	logic signed [38:0]      weighted_term_h_hi_sh_5x_blue = '0;
	logic signed [38:0]      weighted_term_v_lo_5x_blue    = '0;
	logic signed [38:0]      weighted_term_v_hi_sh_5x_blue = '0;

	logic                    fuse_pair_valid_6d   = 1'b0;
	logic [IMAGE_DIM_BS-1:0] fuse_row_idx_6d      = '0;
	logic [IMAGE_DIM_BS-1:0] fuse_column_idx_6d   = '0;
	logic [14:0]             conf_sum_6d          = '0;
	logic [DIVISOR_W-1:0]    weight_sum_6d        = '0;

	logic signed [38:0]      weighted_term_h_6d_red   = '0;
	logic signed [38:0]      weighted_term_v_6d_red   = '0;
	logic signed [38:0]      weighted_term_h_6d_green = '0;
	logic signed [38:0]      weighted_term_v_6d_green = '0;
	logic signed [38:0]      weighted_term_h_6d_blue  = '0;
	logic signed [38:0]      weighted_term_v_6d_blue  = '0;

	logic                    crop_ok_6d           = '0;

	logic                    fuse_pair_valid_7d     = 1'b0;
	logic [IMAGE_DIM_BS-1:0] fuse_row_idx_7d        = '0;
	logic [IMAGE_DIM_BS-1:0] fuse_column_idx_7d     = '0;
	logic [14:0]             conf_sum_7d            = '0;
	logic [DIVISOR_W-1:0]    weight_sum_7d          = '0;
	logic signed [NUMERATOR_W-1:0] weighted_numerator_7d = '0;
	logic                    crop_ok_7d             = '0;

	logic                    fuse_pair_valid_8d     = 1'b0;
	logic [IMAGE_DIM_BS-1:0] fuse_row_idx_8d        = '0;
	logic [IMAGE_DIM_BS-1:0] fuse_column_idx_8d     = '0;
	logic [14:0]             conf_sum_8d            = '0;
	logic [DIVISOR_W-1:0]    weight_sum_8d          = '0;
	logic signed [NUMERATOR_W-1:0] weighted_numerator_8d = '0;
	logic                    crop_ok_8d             = '0;

	logic [DIVIDEND_W-1:0] dividend_pipe     [0:DIV_STAGES];
	logic [DIVISOR_W-1:0]  divisor_pipe      [0:DIV_STAGES];
	logic [DIVISOR_W:0]    remainder_pipe    [0:DIV_STAGES];
	logic [QUOTIENT_W-1:0] quotient_pipe     [0:DIV_STAGES];

	logic                    valid_pipe      [0:DIV_STAGES];
	logic                    sign_pipe       [0:DIV_STAGES];
	logic                    div_zero_pipe   [0:DIV_STAGES];
	logic                    crop_ok_pipe    [0:DIV_STAGES];
	logic [IMAGE_DIM_BS-1:0] row_idx_pipe    [0:DIV_STAGES];
	logic [IMAGE_DIM_BS-1:0] column_idx_pipe [0:DIV_STAGES];
	logic [14:0]             conf_sum_pipe   [0:DIV_STAGES];

	always_ff @(posedge clk) begin : Stage0_Register_Inputs_And_Storage_IO
		integer i;
		integer b;

		for (i = 0; i < 12; i = i + 1) begin
			shared_we[i]      <= 1'b0;
			shared_wr_addr[i] <= '0;
			shared_wr_data[i] <= 15'd0;
			shared_rd_addr[i] <= '0;
		end

		if (shared_banks_available) begin
			b = bank_base(0);
			if (confidence_valid_in && (confidence_orientation_in == 1'b0)) begin
				shared_we[b+0]      <= 1'b1;
				shared_wr_addr[b+0] <= conf_addr_in;
				shared_wr_data[b+0] <= confidence_pixel_in_red;
			end
			if (confidence_valid_in && (confidence_orientation_in == 1'b1)) begin
				shared_we[b+1]      <= 1'b1;
				shared_wr_addr[b+1] <= conf_addr_in;
				shared_wr_data[b+1] <= confidence_pixel_in_red;
			end
			if (disparity_valid_in && (disparity_orientation_in == 1'b0)) begin
				shared_we[b+2]      <= 1'b1;
				shared_wr_addr[b+2] <= disp_addr_in;
				shared_wr_data[b+2] <= disparity_q12_12_in_red[14:0];
				shared_we[b+3]      <= 1'b1;
				shared_wr_addr[b+3] <= disp_addr_in;
				shared_wr_data[b+3] <= {6'd0, disparity_q12_12_in_red[23:15]};
			end
			if (disparity_valid_in && (disparity_orientation_in == 1'b1)) begin
				shared_rd_addr[b+0] <= disp_addr_in;
				shared_rd_addr[b+1] <= disp_addr_in;
				shared_rd_addr[b+2] <= disp_addr_in;
				shared_rd_addr[b+3] <= disp_addr_in;
			end

			b = bank_base(1);
			if (confidence_valid_in && (confidence_orientation_in == 1'b0)) begin
				shared_we[b+0]      <= 1'b1;
				shared_wr_addr[b+0] <= conf_addr_in;
				shared_wr_data[b+0] <= confidence_pixel_in_green;
			end
			if (confidence_valid_in && (confidence_orientation_in == 1'b1)) begin
				shared_we[b+1]      <= 1'b1;
				shared_wr_addr[b+1] <= conf_addr_in;
				shared_wr_data[b+1] <= confidence_pixel_in_green;
			end
			if (disparity_valid_in && (disparity_orientation_in == 1'b0)) begin
				shared_we[b+2]      <= 1'b1;
				shared_wr_addr[b+2] <= disp_addr_in;
				shared_wr_data[b+2] <= disparity_q12_12_in_green[14:0];
				shared_we[b+3]      <= 1'b1;
				shared_wr_addr[b+3] <= disp_addr_in;
				shared_wr_data[b+3] <= {6'd0, disparity_q12_12_in_green[23:15]};
			end
			if (disparity_valid_in && (disparity_orientation_in == 1'b1)) begin
				shared_rd_addr[b+0] <= disp_addr_in;
				shared_rd_addr[b+1] <= disp_addr_in;
				shared_rd_addr[b+2] <= disp_addr_in;
				shared_rd_addr[b+3] <= disp_addr_in;
			end

			b = bank_base(2);
			if (confidence_valid_in && (confidence_orientation_in == 1'b0)) begin
				shared_we[b+0]      <= 1'b1;
				shared_wr_addr[b+0] <= conf_addr_in;
				shared_wr_data[b+0] <= confidence_pixel_in_blue;
			end
			if (confidence_valid_in && (confidence_orientation_in == 1'b1)) begin
				shared_we[b+1]      <= 1'b1;
				shared_wr_addr[b+1] <= conf_addr_in;
				shared_wr_data[b+1] <= confidence_pixel_in_blue;
			end
			if (disparity_valid_in && (disparity_orientation_in == 1'b0)) begin
				shared_we[b+2]      <= 1'b1;
				shared_wr_addr[b+2] <= disp_addr_in;
				shared_wr_data[b+2] <= disparity_q12_12_in_blue[14:0];
				shared_we[b+3]      <= 1'b1;
				shared_wr_addr[b+3] <= disp_addr_in;
				shared_wr_data[b+3] <= {6'd0, disparity_q12_12_in_blue[23:15]};
			end
			if (disparity_valid_in && (disparity_orientation_in == 1'b1)) begin
				shared_rd_addr[b+0] <= disp_addr_in;
				shared_rd_addr[b+1] <= disp_addr_in;
				shared_rd_addr[b+2] <= disp_addr_in;
				shared_rd_addr[b+3] <= disp_addr_in;
			end
		end
	end

	always_ff @(posedge clk) begin : Fusion_Request_Capture
		fuse_req_d                    <= 1'b0;
		v_conf_bypass_d_red          <= 1'b0;
		v_conf_bypass_d_green        <= 1'b0;
		v_conf_bypass_d_blue         <= 1'b0;
		v_conf_bypass_pixel_d_red    <= '0;
		v_conf_bypass_pixel_d_green  <= '0;
		v_conf_bypass_pixel_d_blue   <= '0;
		fuse_row_idx_d               <= '0;
		fuse_column_idx_d            <= '0;
		v_disp_q12_12_d_red          <= '0;
		v_disp_q12_12_d_green        <= '0;
		v_disp_q12_12_d_blue         <= '0;

		if (shared_banks_available &&
		    disparity_valid_in &&
		    (disparity_orientation_in == 1'b1)) begin
			fuse_req_d <= 1'b1;
			fuse_row_idx_d <= disparity_row_idx_in;
			fuse_column_idx_d <= disparity_column_idx_in;
			v_disp_q12_12_d_red   <= disparity_q12_12_in_red;
			v_disp_q12_12_d_green <= disparity_q12_12_in_green;
			v_disp_q12_12_d_blue  <= disparity_q12_12_in_blue;

			if (confidence_valid_in &&
			    (confidence_orientation_in == 1'b1) &&
			    (confidence_row_idx_in == disparity_row_idx_in) &&
			    (confidence_column_idx_in == disparity_column_idx_in)) begin
				v_conf_bypass_d_red         <= 1'b1;
				v_conf_bypass_d_green       <= 1'b1;
				v_conf_bypass_d_blue        <= 1'b1;
				v_conf_bypass_pixel_d_red   <= confidence_pixel_in_red;
				v_conf_bypass_pixel_d_green <= confidence_pixel_in_green;
				v_conf_bypass_pixel_d_blue  <= confidence_pixel_in_blue;
			end
		end
	end

	always_ff @(posedge clk) begin : Fusion_Request_Delay_For_RAM
		fuse_req_2d_pre               <= fuse_req_d;
		fuse_row_idx_2d_pre           <= fuse_row_idx_d;
		fuse_column_idx_2d_pre        <= fuse_column_idx_d;

		v_disp_q12_12_2d_pre_red      <= v_disp_q12_12_d_red;
		v_disp_q12_12_2d_pre_green    <= v_disp_q12_12_d_green;
		v_disp_q12_12_2d_pre_blue     <= v_disp_q12_12_d_blue;

		v_conf_bypass_2d_pre_red      <= v_conf_bypass_d_red;
		v_conf_bypass_2d_pre_green    <= v_conf_bypass_d_green;
		v_conf_bypass_2d_pre_blue     <= v_conf_bypass_d_blue;

		v_conf_bypass_pixel_2d_pre_red   <= v_conf_bypass_pixel_d_red;
		v_conf_bypass_pixel_2d_pre_green <= v_conf_bypass_pixel_d_green;
		v_conf_bypass_pixel_2d_pre_blue  <= v_conf_bypass_pixel_d_blue;
	end

	always_ff @(posedge clk) begin : Gather_Fusion_Operands
		fuse_pair_valid_d          <= 1'b0;
		fused_pixel_inside_crop_2d <= 1'b0;
		fuse_row_idx_2d            <= '0;
		fuse_column_idx_2d         <= '0;

		conf_h_2d_red   <= '0;
		conf_v_2d_red   <= '0;
		conf_h_2d_green <= '0;
		conf_v_2d_green <= '0;
		conf_h_2d_blue  <= '0;
		conf_v_2d_blue  <= '0;

		disp_h_2d_red   <= '0;
		disp_v_2d_red   <= '0;
		disp_h_2d_green <= '0;
		disp_v_2d_green <= '0;
		disp_h_2d_blue  <= '0;
		disp_v_2d_blue  <= '0;

		if (fuse_req_2d_pre) begin
			fuse_pair_valid_d  <= 1'b1;
			fuse_row_idx_2d    <= fuse_row_idx_2d_pre;
			fuse_column_idx_2d <= fuse_column_idx_2d_pre;

			conf_h_2d_red <= shared_rd_data[0];
			conf_v_2d_red <= v_conf_bypass_2d_pre_red ? v_conf_bypass_pixel_2d_pre_red : shared_rd_data[1];
			disp_h_2d_red <= $signed({shared_rd_data[3][8:0], shared_rd_data[2]});
			disp_v_2d_red <= v_disp_q12_12_2d_pre_red;

			conf_h_2d_green <= shared_rd_data[4];
			conf_v_2d_green <= v_conf_bypass_2d_pre_green ? v_conf_bypass_pixel_2d_pre_green : shared_rd_data[5];
			disp_h_2d_green <= $signed({shared_rd_data[7][8:0], shared_rd_data[6]});
			disp_v_2d_green <= v_disp_q12_12_2d_pre_green;

			conf_h_2d_blue <= shared_rd_data[8];
			conf_v_2d_blue <= v_conf_bypass_2d_pre_blue ? v_conf_bypass_pixel_2d_pre_blue : shared_rd_data[9];
			disp_h_2d_blue <= $signed({shared_rd_data[11][8:0], shared_rd_data[10]});
			disp_v_2d_blue <= v_disp_q12_12_2d_pre_blue;

			fused_pixel_inside_crop_2d <=
				(fuse_row_idx_2d_pre    >= TRIM_PIXELS)   &&
				(fuse_row_idx_2d_pre    <= MAX_VALID_IDX) &&
				(fuse_column_idx_2d_pre >= TRIM_PIXELS)   &&
				(fuse_column_idx_2d_pre <= MAX_VALID_IDX);
		end
	end

	always_ff @(posedge clk) begin : Register_Gathered_Fusion_Operands
		fuse_pair_valid_3r         <= 1'b0;
		fuse_row_idx_3r            <= '0;
		fuse_column_idx_3r         <= '0;
		conf_h_3r_red              <= '0;
		conf_v_3r_red              <= '0;
		conf_h_3r_green            <= '0;
		conf_v_3r_green            <= '0;
		conf_h_3r_blue             <= '0;
		conf_v_3r_blue             <= '0;
		disp_h_3r_red              <= '0;
		disp_v_3r_red              <= '0;
		disp_h_3r_green            <= '0;
		disp_v_3r_green            <= '0;
		disp_h_3r_blue             <= '0;
		disp_v_3r_blue             <= '0;
		fused_pixel_inside_crop_3r <= 1'b0;

		if (fuse_pair_valid_d) begin
			fuse_pair_valid_3r         <= 1'b1;
			fuse_row_idx_3r            <= fuse_row_idx_2d;
			fuse_column_idx_3r         <= fuse_column_idx_2d;
			conf_h_3r_red              <= conf_h_2d_red;
			conf_v_3r_red              <= conf_v_2d_red;
			conf_h_3r_green            <= conf_h_2d_green;
			conf_v_3r_green            <= conf_v_2d_green;
			conf_h_3r_blue             <= conf_h_2d_blue;
			conf_v_3r_blue             <= conf_v_2d_blue;
			disp_h_3r_red              <= disp_h_2d_red;
			disp_v_3r_red              <= disp_v_2d_red;
			disp_h_3r_green            <= disp_h_2d_green;
			disp_v_3r_green            <= disp_v_2d_green;
			disp_h_3r_blue             <= disp_h_2d_blue;
			disp_v_3r_blue             <= disp_v_2d_blue;
			fused_pixel_inside_crop_3r <= fused_pixel_inside_crop_2d;
		end
	end

	always_ff @(posedge clk) begin : Register_Split_Multiply_Inputs
		fuse_pair_valid_4d <= 1'b0;
		fuse_row_idx_4d    <= '0;
		fuse_column_idx_4d <= '0;

		disp_h_lo_4d_red   <= '0; disp_h_hi_4d_red   <= '0; disp_v_lo_4d_red   <= '0; disp_v_hi_4d_red   <= '0;
		disp_h_lo_4d_green <= '0; disp_h_hi_4d_green <= '0; disp_v_lo_4d_green <= '0; disp_v_hi_4d_green <= '0;
		disp_h_lo_4d_blue  <= '0; disp_h_hi_4d_blue  <= '0; disp_v_lo_4d_blue  <= '0; disp_v_hi_4d_blue  <= '0;

		conf_h_4d_red   <= '0; conf_v_4d_red   <= '0;
		conf_h_4d_green <= '0; conf_v_4d_green <= '0;
		conf_h_4d_blue  <= '0; conf_v_4d_blue  <= '0;

		conf_sum_4d   <= '0;
		weight_sum_4d <= '0;
		crop_ok_4d    <= 1'b0;

		if (fuse_pair_valid_3r) begin
			fuse_pair_valid_4d <= 1'b1;
			fuse_row_idx_4d    <= fuse_row_idx_3r;
			fuse_column_idx_4d <= fuse_column_idx_3r;

			disp_h_lo_4d_red   <= disp_h_3r_red[11:0];
			disp_h_hi_4d_red   <= disp_h_3r_red[23:12];
			disp_v_lo_4d_red   <= disp_v_3r_red[11:0];
			disp_v_hi_4d_red   <= disp_v_3r_red[23:12];

			disp_h_lo_4d_green <= disp_h_3r_green[11:0];
			disp_h_hi_4d_green <= disp_h_3r_green[23:12];
			disp_v_lo_4d_green <= disp_v_3r_green[11:0];
			disp_v_hi_4d_green <= disp_v_3r_green[23:12];

			disp_h_lo_4d_blue  <= disp_h_3r_blue[11:0];
			disp_h_hi_4d_blue  <= disp_h_3r_blue[23:12];
			disp_v_lo_4d_blue  <= disp_v_3r_blue[11:0];
			disp_v_hi_4d_blue  <= disp_v_3r_blue[23:12];

			conf_h_4d_red   <= conf_h_3r_red;   conf_v_4d_red   <= conf_v_3r_red;
			conf_h_4d_green <= conf_h_3r_green; conf_v_4d_green <= conf_v_3r_green;
			conf_h_4d_blue  <= conf_h_3r_blue;  conf_v_4d_blue  <= conf_v_3r_blue;

			conf_sum_4d <= sat_u15_sum6(
				conf_h_3r_red, conf_v_3r_red,
				conf_h_3r_green, conf_v_3r_green,
				conf_h_3r_blue, conf_v_3r_blue
			);

			weight_sum_4d <=
				{{(DIVISOR_W-15){1'b0}}, conf_h_3r_red}   +
				{{(DIVISOR_W-15){1'b0}}, conf_v_3r_red}   +
				{{(DIVISOR_W-15){1'b0}}, conf_h_3r_green} +
				{{(DIVISOR_W-15){1'b0}}, conf_v_3r_green} +
				{{(DIVISOR_W-15){1'b0}}, conf_h_3r_blue}  +
				{{(DIVISOR_W-15){1'b0}}, conf_v_3r_blue};

			crop_ok_4d <= fused_pixel_inside_crop_3r;
		end
	end

	always_ff @(posedge clk) begin : Compute_Smaller_Partial_Products
		fuse_pair_valid_5d <= 1'b0;
		fuse_row_idx_5d    <= '0;
		fuse_column_idx_5d <= '0;
		conf_sum_5d        <= '0;
		weight_sum_5d      <= '0;
		crop_ok_5d         <= '0;

		weighted_term_h_lo_5d_red   <= '0; weighted_term_h_hi_5d_red   <= '0; weighted_term_v_lo_5d_red   <= '0; weighted_term_v_hi_5d_red   <= '0;
		weighted_term_h_lo_5d_green <= '0; weighted_term_h_hi_5d_green <= '0; weighted_term_v_lo_5d_green <= '0; weighted_term_v_hi_5d_green <= '0;
		weighted_term_h_lo_5d_blue  <= '0; weighted_term_h_hi_5d_blue  <= '0; weighted_term_v_lo_5d_blue  <= '0; weighted_term_v_hi_5d_blue  <= '0;

		if (fuse_pair_valid_4d) begin
			fuse_pair_valid_5d <= 1'b1;
			fuse_row_idx_5d    <= fuse_row_idx_4d;
			fuse_column_idx_5d <= fuse_column_idx_4d;
			conf_sum_5d        <= conf_sum_4d;
			weight_sum_5d      <= weight_sum_4d;
			crop_ok_5d         <= crop_ok_4d;

			weighted_term_h_lo_5d_red <= disp_h_lo_4d_red * conf_h_4d_red;
			weighted_term_h_hi_5d_red <= $signed(disp_h_hi_4d_red) * $signed({1'b0, conf_h_4d_red});
			weighted_term_v_lo_5d_red <= disp_v_lo_4d_red * conf_v_4d_red;
			weighted_term_v_hi_5d_red <= $signed(disp_v_hi_4d_red) * $signed({1'b0, conf_v_4d_red});

			weighted_term_h_lo_5d_green <= disp_h_lo_4d_green * conf_h_4d_green;
			weighted_term_h_hi_5d_green <= $signed(disp_h_hi_4d_green) * $signed({1'b0, conf_h_4d_green});
			weighted_term_v_lo_5d_green <= disp_v_lo_4d_green * conf_v_4d_green;
			weighted_term_v_hi_5d_green <= $signed(disp_v_hi_4d_green) * $signed({1'b0, conf_v_4d_green});

			weighted_term_h_lo_5d_blue <= disp_h_lo_4d_blue * conf_h_4d_blue;
			weighted_term_h_hi_5d_blue <= $signed(disp_h_hi_4d_blue) * $signed({1'b0, conf_h_4d_blue});
			weighted_term_v_lo_5d_blue <= disp_v_lo_4d_blue * conf_v_4d_blue;
			weighted_term_v_hi_5d_blue <= $signed(disp_v_hi_4d_blue) * $signed({1'b0, conf_v_4d_blue});
		end
	end

	always_ff @(posedge clk) begin : Register_Partial_Product_Outputs
		fuse_pair_valid_5r <= 1'b0;
		fuse_row_idx_5r    <= '0;
		fuse_column_idx_5r <= '0;
		conf_sum_5r        <= '0;
		weight_sum_5r      <= '0;
		crop_ok_5r         <= '0;

		weighted_term_h_lo_5r_red   <= '0; weighted_term_h_hi_5r_red   <= '0; weighted_term_v_lo_5r_red   <= '0; weighted_term_v_hi_5r_red   <= '0;
		weighted_term_h_lo_5r_green <= '0; weighted_term_h_hi_5r_green <= '0; weighted_term_v_lo_5r_green <= '0; weighted_term_v_hi_5r_green <= '0;
		weighted_term_h_lo_5r_blue  <= '0; weighted_term_h_hi_5r_blue  <= '0; weighted_term_v_lo_5r_blue  <= '0; weighted_term_v_hi_5r_blue  <= '0;

		if (fuse_pair_valid_5d) begin
			fuse_pair_valid_5r <= 1'b1;
			fuse_row_idx_5r    <= fuse_row_idx_5d;
			fuse_column_idx_5r <= fuse_column_idx_5d;
			conf_sum_5r        <= conf_sum_5d;
			weight_sum_5r      <= weight_sum_5d;
			crop_ok_5r         <= crop_ok_5d;

			weighted_term_h_lo_5r_red   <= weighted_term_h_lo_5d_red;
			weighted_term_h_hi_5r_red   <= weighted_term_h_hi_5d_red;
			weighted_term_v_lo_5r_red   <= weighted_term_v_lo_5d_red;
			weighted_term_v_hi_5r_red   <= weighted_term_v_hi_5d_red;

			weighted_term_h_lo_5r_green <= weighted_term_h_lo_5d_green;
			weighted_term_h_hi_5r_green <= weighted_term_h_hi_5d_green;
			weighted_term_v_lo_5r_green <= weighted_term_v_lo_5d_green;
			weighted_term_v_hi_5r_green <= weighted_term_v_hi_5d_green;

			weighted_term_h_lo_5r_blue  <= weighted_term_h_lo_5d_blue;
			weighted_term_h_hi_5r_blue  <= weighted_term_h_hi_5d_blue;
			weighted_term_v_lo_5r_blue  <= weighted_term_v_lo_5d_blue;
			weighted_term_v_hi_5r_blue  <= weighted_term_v_hi_5d_blue;
		end
	end

	always_ff @(posedge clk) begin : Register_Aligned_Recombine_Terms
		fuse_pair_valid_5x <= 1'b0;
		fuse_row_idx_5x    <= '0;
		fuse_column_idx_5x <= '0;
		conf_sum_5x        <= '0;
		weight_sum_5x      <= '0;
		crop_ok_5x         <= '0;

		weighted_term_h_lo_5x_red    <= '0; weighted_term_h_hi_sh_5x_red <= '0; weighted_term_v_lo_5x_red    <= '0; weighted_term_v_hi_sh_5x_red <= '0;
		weighted_term_h_lo_5x_green  <= '0; weighted_term_h_hi_sh_5x_green <= '0; weighted_term_v_lo_5x_green  <= '0; weighted_term_v_hi_sh_5x_green <= '0;
		weighted_term_h_lo_5x_blue   <= '0; weighted_term_h_hi_sh_5x_blue <= '0; weighted_term_v_lo_5x_blue   <= '0; weighted_term_v_hi_sh_5x_blue <= '0;

		if (fuse_pair_valid_5r) begin
			fuse_pair_valid_5x <= 1'b1;
			fuse_row_idx_5x    <= fuse_row_idx_5r;
			fuse_column_idx_5x <= fuse_column_idx_5r;
			conf_sum_5x        <= conf_sum_5r;
			weight_sum_5x      <= weight_sum_5r;
			crop_ok_5x         <= crop_ok_5r;

			weighted_term_h_lo_5x_red    <= $signed({12'd0, weighted_term_h_lo_5r_red});
			weighted_term_h_hi_sh_5x_red <= ($signed({{11{weighted_term_h_hi_5r_red[27]}}, weighted_term_h_hi_5r_red}) <<< 12);
			weighted_term_v_lo_5x_red    <= $signed({12'd0, weighted_term_v_lo_5r_red});
			weighted_term_v_hi_sh_5x_red <= ($signed({{11{weighted_term_v_hi_5r_red[27]}}, weighted_term_v_hi_5r_red}) <<< 12);

			weighted_term_h_lo_5x_green    <= $signed({12'd0, weighted_term_h_lo_5r_green});
			weighted_term_h_hi_sh_5x_green <= ($signed({{11{weighted_term_h_hi_5r_green[27]}}, weighted_term_h_hi_5r_green}) <<< 12);
			weighted_term_v_lo_5x_green    <= $signed({12'd0, weighted_term_v_lo_5r_green});
			weighted_term_v_hi_sh_5x_green <= ($signed({{11{weighted_term_v_hi_5r_green[27]}}, weighted_term_v_hi_5r_green}) <<< 12);

			weighted_term_h_lo_5x_blue    <= $signed({12'd0, weighted_term_h_lo_5r_blue});
			weighted_term_h_hi_sh_5x_blue <= ($signed({{11{weighted_term_h_hi_5r_blue[27]}}, weighted_term_h_hi_5r_blue}) <<< 12);
			weighted_term_v_lo_5x_blue    <= $signed({12'd0, weighted_term_v_lo_5r_blue});
			weighted_term_v_hi_sh_5x_blue <= ($signed({{11{weighted_term_v_hi_5r_blue[27]}}, weighted_term_v_hi_5r_blue}) <<< 12);
		end
	end

	always_ff @(posedge clk) begin : Recombine_Partial_Products
		fuse_pair_valid_6d <= 1'b0;
		fuse_row_idx_6d    <= '0;
		fuse_column_idx_6d <= '0;
		conf_sum_6d        <= '0;
		weight_sum_6d      <= '0;
		weighted_term_h_6d_red   <= '0; weighted_term_v_6d_red   <= '0;
		weighted_term_h_6d_green <= '0; weighted_term_v_6d_green <= '0;
		weighted_term_h_6d_blue  <= '0; weighted_term_v_6d_blue  <= '0;
		crop_ok_6d <= '0;

		if (fuse_pair_valid_5x) begin
			fuse_pair_valid_6d <= 1'b1;
			fuse_row_idx_6d    <= fuse_row_idx_5x;
			fuse_column_idx_6d <= fuse_column_idx_5x;
			conf_sum_6d        <= conf_sum_5x;
			weight_sum_6d      <= weight_sum_5x;

			weighted_term_h_6d_red   <= weighted_term_h_lo_5x_red   + weighted_term_h_hi_sh_5x_red;
			weighted_term_v_6d_red   <= weighted_term_v_lo_5x_red   + weighted_term_v_hi_sh_5x_red;
			weighted_term_h_6d_green <= weighted_term_h_lo_5x_green + weighted_term_h_hi_sh_5x_green;
			weighted_term_v_6d_green <= weighted_term_v_lo_5x_green + weighted_term_v_hi_sh_5x_green;
			weighted_term_h_6d_blue  <= weighted_term_h_lo_5x_blue  + weighted_term_h_hi_sh_5x_blue;
			weighted_term_v_6d_blue  <= weighted_term_v_lo_5x_blue  + weighted_term_v_hi_sh_5x_blue;

			crop_ok_6d <= crop_ok_5x;
		end
	end

	always_ff @(posedge clk) begin : Compute_Numerator
		fuse_pair_valid_7d    <= 1'b0;
		fuse_row_idx_7d       <= '0;
		fuse_column_idx_7d    <= '0;
		conf_sum_7d           <= '0;
		weight_sum_7d         <= '0;
		weighted_numerator_7d <= '0;
		crop_ok_7d            <= '0;

		if (fuse_pair_valid_6d) begin
			fuse_pair_valid_7d <= 1'b1;
			fuse_row_idx_7d    <= fuse_row_idx_6d;
			fuse_column_idx_7d <= fuse_column_idx_6d;
			conf_sum_7d        <= conf_sum_6d;
			weight_sum_7d      <= weight_sum_6d;

			weighted_numerator_7d <=
				$signed({{3{weighted_term_h_6d_red[38]}},   weighted_term_h_6d_red})   +
				$signed({{3{weighted_term_v_6d_red[38]}},   weighted_term_v_6d_red})   +
				$signed({{3{weighted_term_h_6d_green[38]}}, weighted_term_h_6d_green}) +
				$signed({{3{weighted_term_v_6d_green[38]}}, weighted_term_v_6d_green}) +
				$signed({{3{weighted_term_h_6d_blue[38]}},  weighted_term_h_6d_blue})  +
				$signed({{3{weighted_term_v_6d_blue[38]}},  weighted_term_v_6d_blue});

			crop_ok_7d <= crop_ok_6d;
		end
	end

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

	always_ff @(posedge clk) begin : Divider_Stage0_Load
		valid_pipe[0]    <= fuse_pair_valid_8d;
		sign_pipe[0]     <= weighted_numerator_8d[NUMERATOR_W-1];
		div_zero_pipe[0] <= (weight_sum_8d == '0);
		crop_ok_pipe[0]  <= crop_ok_8d;

		row_idx_pipe[0]    <= fuse_row_idx_8d;
		column_idx_pipe[0] <= fuse_column_idx_8d;
		conf_sum_pipe[0]   <= conf_sum_8d;

		if (fuse_pair_valid_8d && (weight_sum_8d != '0)) begin
			dividend_pipe[0]  <= abs_num(weighted_numerator_8d);
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