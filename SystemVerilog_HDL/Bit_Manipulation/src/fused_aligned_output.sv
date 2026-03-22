module fused_aligned_output #(
	parameter int unsigned IMAGE_DIM    = 128,
	parameter int unsigned IMAGE_DIM_BS = 7
)(
    input  wire                                   clk,

	input  wire                                   confidence_valid_in,
	input  wire [14:0]                            confidence_pixel_in,
	input  wire [IMAGE_DIM_BS-1:0]                confidence_row_idx_in,
	input  wire [IMAGE_DIM_BS-1:0]                confidence_column_idx_in,
	input  wire                                   confidence_orientation_in,

	input  wire                                   disparity_valid_in,
	input  wire [31:0]                            disparity_pixel_in,
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
	output logic [14:0]                           confidence_pixel_bit_data,
	output logic [23:0]                           weighted_disparity_pixel_bit_data
);

	localparam int unsigned ADDR_W = 2 * IMAGE_DIM_BS;
	localparam int unsigned IMAGE_LAST_INT = IMAGE_DIM - 1;
	localparam logic [IMAGE_DIM_BS-1:0] LAST_VALID_PIXEL = IMAGE_LAST_INT[IMAGE_DIM_BS-1:0];

	localparam int unsigned DIVIDEND_W = 40;
	localparam int unsigned DIVISOR_W  = 16;
	localparam int unsigned QUOTIENT_W = 40;
	localparam int unsigned DIV_STAGES = DIVIDEND_W;

	function automatic [ADDR_W-1:0] addr_row_col(
		input logic [IMAGE_DIM_BS-1:0] row_i,
		input logic [IMAGE_DIM_BS-1:0] col_i
	);
		begin
			addr_row_col =
				({{(ADDR_W-IMAGE_DIM_BS){1'b0}}, row_i} << IMAGE_DIM_BS) +
				{{(ADDR_W-IMAGE_DIM_BS){1'b0}}, col_i};
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
		input logic                   sign_bit,
		input logic [QUOTIENT_W-1:0]  magnitude
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

	logic [IMAGE_DIM_BS-1:0] trim_pixels_s0   = '0;
	logic [IMAGE_DIM_BS-1:0] max_valid_idx_s0 = '0;

	integer i;

	logic signed [23:0] disparity_q12_12_tmp;

	always_comb begin
		disparity_q12_12_tmp = q15_16_to_q12_12_sat($signed(disparity_pixel_in));
	end

	logic                    fuse_req_d            = 1'b0;
	logic [IMAGE_DIM_BS-1:0] fuse_row_idx_d        = '0;
	logic [IMAGE_DIM_BS-1:0] fuse_column_idx_d     = '0;
	logic signed [23:0]      v_disp_q12_12_d       = '0;
	logic                    v_conf_bypass_d       = 1'b0;
	logic [14:0]             v_conf_bypass_pixel_d = '0;

	logic                    fuse_pair_valid_d          = 1'b0;
	logic [IMAGE_DIM_BS-1:0] fuse_row_idx_2d            = '0;
	logic [IMAGE_DIM_BS-1:0] fuse_column_idx_2d         = '0;
	logic [14:0]             conf_h_2d                  = '0;
	logic [14:0]             conf_v_2d                  = '0;
	logic signed [23:0]      disp_h_2d                  = '0;
	logic signed [23:0]      disp_v_2d                  = '0;
	logic [IMAGE_DIM_BS-1:0] trim_pixels_2d             = '0;
	logic [IMAGE_DIM_BS-1:0] max_valid_idx_2d           = '0;
	logic                    fused_pixel_inside_crop_2d = 1'b0;

	logic                    fuse_pair_valid_3d   = 1'b0;
	logic [IMAGE_DIM_BS-1:0] fuse_row_idx_3d      = '0;
	logic [IMAGE_DIM_BS-1:0] fuse_column_idx_3d   = '0;
	logic [IMAGE_DIM_BS-1:0] trim_pixels_3d       = '0;
	logic [IMAGE_DIM_BS-1:0] max_valid_idx_3d     = '0;
	logic [14:0]             conf_sum_3d          = '0;
	logic [15:0]             weight_sum_3d        = '0;
	logic signed [38:0]      weighted_term_h_3d   = '0;
	logic signed [38:0]      weighted_term_v_3d   = '0;
	logic                    crop_ok_3d           = 1'b0;

	logic                    fuse_pair_valid_4d     = 1'b0;
	logic [IMAGE_DIM_BS-1:0] fuse_row_idx_4d        = '0;
	logic [IMAGE_DIM_BS-1:0] fuse_column_idx_4d     = '0;
	logic [IMAGE_DIM_BS-1:0] trim_pixels_4d         = '0;
	logic [IMAGE_DIM_BS-1:0] max_valid_idx_4d       = '0;
	logic [14:0]             conf_sum_4d            = '0;
	logic [15:0]             weight_sum_4d          = '0;
	logic signed [39:0]      weighted_numerator_4d  = '0;
	logic                    crop_ok_4d             = 1'b0;

	logic [DIVIDEND_W-1:0] dividend_pipe     [0:DIV_STAGES];
	logic [DIVISOR_W-1:0]  divisor_pipe      [0:DIV_STAGES];
	logic [DIVISOR_W:0]    remainder_pipe    [0:DIV_STAGES];
	logic [QUOTIENT_W-1:0] quotient_pipe     [0:DIV_STAGES];

	logic                  valid_pipe        [0:DIV_STAGES];
	logic                  sign_pipe         [0:DIV_STAGES];
	logic                  div_zero_pipe     [0:DIV_STAGES];
	logic                  crop_ok_pipe      [0:DIV_STAGES];

	logic [IMAGE_DIM_BS-1:0] row_idx_pipe       [0:DIV_STAGES];
	logic [IMAGE_DIM_BS-1:0] column_idx_pipe    [0:DIV_STAGES];
	logic [IMAGE_DIM_BS-1:0] trim_pixels_pipe   [0:DIV_STAGES];
	logic [IMAGE_DIM_BS-1:0] max_valid_idx_pipe [0:DIV_STAGES];
	logic [14:0]             conf_sum_pipe      [0:DIV_STAGES];

	always_ff @(posedge clk) begin : Stage0_Register_Inputs_And_Storage_IO
		trim_pixels_s0   <= {{(IMAGE_DIM_BS-2){1'b0}}, 2'b11} + {{(IMAGE_DIM_BS-1){1'b0}}, 1'b1};
		max_valid_idx_s0 <= LAST_VALID_PIXEL - ({{(IMAGE_DIM_BS-2){1'b0}}, 2'b11} + {{(IMAGE_DIM_BS-1){1'b0}}, 1'b1});

		for (i = 0; i < 4; i = i + 1) begin
			shared_we[i]      <= 1'b0;
			shared_wr_addr[i] <= '0;
			shared_wr_data[i] <= 15'd0;
			shared_rd_addr[i] <= '0;
		end

		if (shared_banks_available) begin
			if (confidence_valid_in && (confidence_orientation_in == 1'b0)) begin
				shared_we[0]      <= 1'b1;
				shared_wr_addr[0] <= addr_row_col(confidence_row_idx_in, confidence_column_idx_in);
				shared_wr_data[0] <= confidence_pixel_in;
			end

			if (confidence_valid_in && (confidence_orientation_in == 1'b1)) begin
				shared_we[1]      <= 1'b1;
				shared_wr_addr[1] <= addr_row_col(confidence_row_idx_in, confidence_column_idx_in);
				shared_wr_data[1] <= confidence_pixel_in;
			end

			if (disparity_valid_in && (disparity_orientation_in == 1'b0)) begin
				shared_we[2]      <= 1'b1;
				shared_wr_addr[2] <= addr_row_col(disparity_row_idx_in, disparity_column_idx_in);
				shared_wr_data[2] <= disparity_q12_12_tmp[14:0];

				shared_we[3]      <= 1'b1;
				shared_wr_addr[3] <= addr_row_col(disparity_row_idx_in, disparity_column_idx_in);
				shared_wr_data[3] <= {6'd0, disparity_q12_12_tmp[23:15]};
			end

			if (disparity_valid_in && (disparity_orientation_in == 1'b1)) begin
				for (i = 0; i < 4; i = i + 1) begin
					shared_rd_addr[i] <= addr_row_col(disparity_row_idx_in, disparity_column_idx_in);
				end
			end
		end
	end

	always_ff @(posedge clk) begin : Fusion_Request_Capture
		fuse_req_d            <= 1'b0;
		v_conf_bypass_d       <= 1'b0;
		v_conf_bypass_pixel_d <= '0;

		if (shared_banks_available &&
		    disparity_valid_in &&
		    (disparity_orientation_in == 1'b1)) begin
			fuse_req_d        <= 1'b1;
			fuse_row_idx_d    <= disparity_row_idx_in;
			fuse_column_idx_d <= disparity_column_idx_in;
			v_disp_q12_12_d   <= q15_16_to_q12_12_sat($signed(disparity_pixel_in));

			if (confidence_valid_in &&
			    (confidence_orientation_in == 1'b1) &&
			    (confidence_row_idx_in == disparity_row_idx_in) &&
			    (confidence_column_idx_in == disparity_column_idx_in)) begin
				v_conf_bypass_d       <= 1'b1;
				v_conf_bypass_pixel_d <= confidence_pixel_in;
			end
		end
	end

	always_ff @(posedge clk) begin : Gather_Fusion_Operands
		fuse_pair_valid_d          <= 1'b0;
		fused_pixel_inside_crop_2d <= 1'b0;

		if (fuse_req_d) begin
			fuse_pair_valid_d  <= 1'b1;
			fuse_row_idx_2d    <= fuse_row_idx_d;
			fuse_column_idx_2d <= fuse_column_idx_d;

			conf_h_2d <= shared_rd_data[0];

			if (v_conf_bypass_d) begin
				conf_v_2d <= v_conf_bypass_pixel_d;
			end
			else begin
				conf_v_2d <= shared_rd_data[1];
			end

			disp_h_2d <= $signed({shared_rd_data[3][8:0], shared_rd_data[2]});
			disp_v_2d <= v_disp_q12_12_d;

			trim_pixels_2d   <= trim_pixels_s0;
			max_valid_idx_2d <= max_valid_idx_s0;

			fused_pixel_inside_crop_2d <=
				(fuse_row_idx_d    >= trim_pixels_s0)   &&
				(fuse_row_idx_d    <= max_valid_idx_s0) &&
				(fuse_column_idx_d >= trim_pixels_s0)   &&
				(fuse_column_idx_d <= max_valid_idx_s0);
		end
	end

	always_ff @(posedge clk) begin : Compute_Products
		fuse_pair_valid_3d <= 1'b0;
		fuse_row_idx_3d    <= '0;
		fuse_column_idx_3d <= '0;
		trim_pixels_3d     <= '0;
		max_valid_idx_3d   <= '0;
		conf_sum_3d        <= '0;
		weight_sum_3d      <= '0;
		weighted_term_h_3d <= '0;
		weighted_term_v_3d <= '0;
		crop_ok_3d         <= 1'b0;

		if (fuse_pair_valid_d) begin
			fuse_pair_valid_3d <= 1'b1;
			fuse_row_idx_3d    <= fuse_row_idx_2d;
			fuse_column_idx_3d <= fuse_column_idx_2d;
			trim_pixels_3d     <= trim_pixels_2d;
			max_valid_idx_3d   <= max_valid_idx_2d;
			crop_ok_3d         <= fused_pixel_inside_crop_2d;

			conf_sum_3d   <= sat_u15_sum(conf_h_2d, conf_v_2d);
			weight_sum_3d <= {1'b0, conf_h_2d} + {1'b0, conf_v_2d};

			weighted_term_h_3d <= disp_h_2d * $signed({1'b0, conf_h_2d});
			weighted_term_v_3d <= disp_v_2d * $signed({1'b0, conf_v_2d});
		end
	end

	always_ff @(posedge clk) begin : Compute_Numerator
		fuse_pair_valid_4d    <= 1'b0;
		fuse_row_idx_4d       <= '0;
		fuse_column_idx_4d    <= '0;
		trim_pixels_4d        <= '0;
		max_valid_idx_4d      <= '0;
		conf_sum_4d           <= '0;
		weight_sum_4d         <= '0;
		weighted_numerator_4d <= '0;
		crop_ok_4d            <= 1'b0;

		if (fuse_pair_valid_3d) begin
			fuse_pair_valid_4d    <= 1'b1;
			fuse_row_idx_4d       <= fuse_row_idx_3d;
			fuse_column_idx_4d    <= fuse_column_idx_3d;
			trim_pixels_4d        <= trim_pixels_3d;
			max_valid_idx_4d      <= max_valid_idx_3d;
			conf_sum_4d           <= conf_sum_3d;
			weight_sum_4d         <= weight_sum_3d;
			crop_ok_4d            <= crop_ok_3d;
			weighted_numerator_4d <= weighted_term_h_3d + weighted_term_v_3d;
		end
	end

	always_ff @(posedge clk) begin : Divider_Stage0_Load
		valid_pipe[0]       <= fuse_pair_valid_4d;
		sign_pipe[0]        <= weighted_numerator_4d[39];
		div_zero_pipe[0]    <= (weight_sum_4d == 16'd0);
		crop_ok_pipe[0]     <= crop_ok_4d;

		row_idx_pipe[0]       <= fuse_row_idx_4d;
		column_idx_pipe[0]    <= fuse_column_idx_4d;
		trim_pixels_pipe[0]   <= trim_pixels_4d;
		max_valid_idx_pipe[0] <= max_valid_idx_4d;
		conf_sum_pipe[0]      <= conf_sum_4d;

		if (fuse_pair_valid_4d && (weight_sum_4d != 16'd0)) begin
			dividend_pipe[0]  <= abs40(weighted_numerator_4d);
			divisor_pipe[0]   <= weight_sum_4d;
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
				valid_pipe[s+1]        <= valid_pipe[s];
				sign_pipe[s+1]         <= sign_pipe[s];
				div_zero_pipe[s+1]     <= div_zero_pipe[s];
				crop_ok_pipe[s+1]      <= crop_ok_pipe[s];

				row_idx_pipe[s+1]       <= row_idx_pipe[s];
				column_idx_pipe[s+1]    <= column_idx_pipe[s];
				trim_pixels_pipe[s+1]   <= trim_pixels_pipe[s];
				max_valid_idx_pipe[s+1] <= max_valid_idx_pipe[s];
				conf_sum_pipe[s+1]      <= conf_sum_pipe[s];

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

			if ((row_idx_pipe[DIV_STAGES] == trim_pixels_pipe[DIV_STAGES]) &&
			    (column_idx_pipe[DIV_STAGES] == trim_pixels_pipe[DIV_STAGES])) begin
				solf_out <= 1'b1;
			end

			if ((row_idx_pipe[DIV_STAGES] == max_valid_idx_pipe[DIV_STAGES]) &&
			    (column_idx_pipe[DIV_STAGES] == max_valid_idx_pipe[DIV_STAGES])) begin
				eolf_out <= 1'b1;
			end
		end
	end

endmodule