module epi_compiler #(
	parameter int unsigned IMAGE_DIM    = 128,
	parameter int unsigned IMAGE_DIM_BS = 7
)(
	input  wire                             clk,
	input  wire                             pixel_valid_in,
	input  wire                             soc_in,
	input  wire                             eoc_in,
	input  wire                             solf_in,
	input  wire                             eolf_in,
	input  wire [14:0]                      pixel_in,
	output logic                            epi_valid_out,
	output logic [14:0]                     epi_column_out [0:8],
	output logic [IMAGE_DIM_BS-1:0]         epi_column_idx_out,
	output logic [IMAGE_DIM_BS-1:0]         epi_idx_out,
	output logic                            orientation_out
);

	localparam int unsigned EPI_FRAME_SIZE  = IMAGE_DIM * IMAGE_DIM;
	localparam int unsigned EPI_FRAME_PTR_W = $clog2(EPI_FRAME_SIZE);

	localparam logic [4:0] H_READ_CAPTURE = 5'd12; // h_08
	localparam logic [4:0] V_READ_CAPTURE = 5'd16; // v_08

	// -------------------------------------------------------------------------
	// State / counters
	// -------------------------------------------------------------------------
	logic                                   in_lf_flag       = 1'b0;
	logic [4:0]                             capture_in_count = 5'd0;
	logic [IMAGE_DIM_BS-1:0]                row_in_count     = '0;
	logic [IMAGE_DIM_BS-1:0]                column_in_count  = '0;

	// -------------------------------------------------------------------------
	// Read/write phase control
	// -------------------------------------------------------------------------
	logic h_read_phase;
	logic h_read_phase_d;
	logic write_phase;
	logic v08_store_phase;

	assign h_read_phase  = (in_lf_flag || solf_in) &&
	                       pixel_valid_in &&
	                       (capture_in_count == H_READ_CAPTURE);

	assign write_phase   = (in_lf_flag || solf_in) &&
	                       pixel_valid_in &&
	                       (capture_in_count != H_READ_CAPTURE) &&
	                       (capture_in_count != V_READ_CAPTURE);

	assign v08_store_phase = (in_lf_flag || solf_in) &&
	                         pixel_valid_in &&
	                         (capture_in_count == V_READ_CAPTURE);

	// Delay current streamed pixel + metadata by 1 cycle so it aligns with RAM read data
	logic [14:0]                      pixel_in_d         = '0;
	logic [IMAGE_DIM_BS-1:0]          row_in_count_d     = '0;
	logic [IMAGE_DIM_BS-1:0]          column_in_count_d  = '0;

	// -------------------------------------------------------------------------
	// Address helpers
	// -------------------------------------------------------------------------
	function automatic [EPI_FRAME_PTR_W-1:0] addr_row_major(
		input logic [IMAGE_DIM_BS-1:0] row_i,
		input logic [IMAGE_DIM_BS-1:0] col_i
	);
		begin
			addr_row_major =
				({{(EPI_FRAME_PTR_W-IMAGE_DIM_BS){1'b0}}, row_i} << IMAGE_DIM_BS) +
				{{(EPI_FRAME_PTR_W-IMAGE_DIM_BS){1'b0}}, col_i};
		end
	endfunction

	function automatic [EPI_FRAME_PTR_W-1:0] addr_transposed(
		input logic [IMAGE_DIM_BS-1:0] row_i,
		input logic [IMAGE_DIM_BS-1:0] col_i
	);
		begin
			addr_transposed =
				({{(EPI_FRAME_PTR_W-IMAGE_DIM_BS){1'b0}}, col_i} << IMAGE_DIM_BS) +
				{{(EPI_FRAME_PTR_W-IMAGE_DIM_BS){1'b0}}, row_i};
		end
	endfunction

	function automatic logic is_vertical_store_capture(
		input logic [4:0] cap_i
	);
		begin
			case (cap_i)
				5'd0,
				5'd1,
				5'd2,
				5'd3,
				5'd13,
				5'd14,
				5'd15: is_vertical_store_capture = 1'b1;
				default: is_vertical_store_capture = 1'b0;
			endcase
		end
	endfunction

	logic [EPI_FRAME_PTR_W-1:0] wr_addr_row_major;
	logic [EPI_FRAME_PTR_W-1:0] wr_addr_transposed;
	logic [EPI_FRAME_PTR_W-1:0] wr_addr_calc;

	assign wr_addr_row_major  = addr_row_major(row_in_count, column_in_count);
	assign wr_addr_transposed = addr_transposed(row_in_count, column_in_count);

	// All non-shared vertical captures write transposed.
	assign wr_addr_calc = is_vertical_store_capture(capture_in_count) ? wr_addr_transposed
	                                                                  : wr_addr_row_major;

	// frame_4_ram is reused:
	//   capture 4  -> stores h_00 row-major
	//   capture 16 -> overwritten with v_08 transposed
	logic [EPI_FRAME_PTR_W-1:0] wr_addr_frame4;
	assign wr_addr_frame4 = v08_store_phase ? wr_addr_transposed
	                                        : wr_addr_calc;

	// -------------------------------------------------------------------------
	// Vertical post-frame output control
	// -------------------------------------------------------------------------
	logic vertical_output_pending = 1'b0;
	logic vertical_output_active  = 1'b0;

	logic [IMAGE_DIM_BS-1:0] v_epi_idx     = '0;
	logic [IMAGE_DIM_BS-1:0] v_spatial_idx = '0;

	logic                    v_read_issue_d    = 1'b0;
	logic [IMAGE_DIM_BS-1:0] v_epi_idx_d       = '0;
	logic [IMAGE_DIM_BS-1:0] v_spatial_idx_d   = '0;

	// -------------------------------------------------------------------------
	// Read-address mux
	// -------------------------------------------------------------------------
	logic [EPI_FRAME_PTR_W-1:0] rd_addr_h_live;
	logic [EPI_FRAME_PTR_W-1:0] rd_addr_v_post;
	logic [EPI_FRAME_PTR_W-1:0] rd_addr_mux;

	assign rd_addr_h_live = wr_addr_row_major;

	// Vertical frames are stored transposed.
	// To output "epi fixed, spatial changes", read row-major from those memories.
	assign rd_addr_v_post = addr_row_major(v_epi_idx, v_spatial_idx);

	assign rd_addr_mux = vertical_output_active ? rd_addr_v_post
	                                            : rd_addr_h_live;

	// -------------------------------------------------------------------------
	// One write-enable per RAM
	// -------------------------------------------------------------------------
	logic we_0;
	logic we_1;
	logic we_2;
	logic we_3;
	logic we_4;   // h_00, later reused for v_08
	logic we_5;
	logic we_6;
	logic we_7;
	logic we_8;
	logic we_8v;  // extra transposed copy for v_04
	logic we_9;
	logic we_10;
	logic we_11;

	// -------------------------------------------------------------------------
	// Read data from RAMs
	// -------------------------------------------------------------------------
	logic [14:0] rd_data_0;
	logic [14:0] rd_data_1;
	logic [14:0] rd_data_2;
	logic [14:0] rd_data_3;
	logic [14:0] rd_data_4;   // h_00 during horizontal, v_08 during vertical post-read
	logic [14:0] rd_data_5;
	logic [14:0] rd_data_6;
	logic [14:0] rd_data_7;
	logic [14:0] rd_data_8;
	logic [14:0] rd_data_8v;
	logic [14:0] rd_data_9;
	logic [14:0] rd_data_10;
	logic [14:0] rd_data_11;

	// -------------------------------------------------------------------------
	// 12 frame RAMs + 1 extra RAM for transposed v_04
	// frame_4_ram is reused for v_08 after horizontal output is finished
	// -------------------------------------------------------------------------
	frame_ram #(
		.DATA_W(15),
		.DEPTH(EPI_FRAME_SIZE),
		.ADDR_W(EPI_FRAME_PTR_W)
	) frame_0_ram (
		.clk(clk),
		.we(we_0),
		.wr_addr(wr_addr_calc),
		.wr_data(pixel_in),
		.rd_addr(rd_addr_mux),
		.rd_data(rd_data_0)
	);

	frame_ram #(
		.DATA_W(15),
		.DEPTH(EPI_FRAME_SIZE),
		.ADDR_W(EPI_FRAME_PTR_W)
	) frame_1_ram (
		.clk(clk),
		.we(we_1),
		.wr_addr(wr_addr_calc),
		.wr_data(pixel_in),
		.rd_addr(rd_addr_mux),
		.rd_data(rd_data_1)
	);

	frame_ram #(
		.DATA_W(15),
		.DEPTH(EPI_FRAME_SIZE),
		.ADDR_W(EPI_FRAME_PTR_W)
	) frame_2_ram (
		.clk(clk),
		.we(we_2),
		.wr_addr(wr_addr_calc),
		.wr_data(pixel_in),
		.rd_addr(rd_addr_mux),
		.rd_data(rd_data_2)
	);

	frame_ram #(
		.DATA_W(15),
		.DEPTH(EPI_FRAME_SIZE),
		.ADDR_W(EPI_FRAME_PTR_W)
	) frame_3_ram (
		.clk(clk),
		.we(we_3),
		.wr_addr(wr_addr_calc),
		.wr_data(pixel_in),
		.rd_addr(rd_addr_mux),
		.rd_data(rd_data_3)
	);

	frame_ram #(
		.DATA_W(15),
		.DEPTH(EPI_FRAME_SIZE),
		.ADDR_W(EPI_FRAME_PTR_W)
	) frame_4_ram (
		.clk(clk),
		.we(we_4),
		.wr_addr(wr_addr_frame4),
		.wr_data(pixel_in),
		.rd_addr(rd_addr_mux),
		.rd_data(rd_data_4)
	);

	frame_ram #(
		.DATA_W(15),
		.DEPTH(EPI_FRAME_SIZE),
		.ADDR_W(EPI_FRAME_PTR_W)
	) frame_5_ram (
		.clk(clk),
		.we(we_5),
		.wr_addr(wr_addr_calc),
		.wr_data(pixel_in),
		.rd_addr(rd_addr_mux),
		.rd_data(rd_data_5)
	);

	frame_ram #(
		.DATA_W(15),
		.DEPTH(EPI_FRAME_SIZE),
		.ADDR_W(EPI_FRAME_PTR_W)
	) frame_6_ram (
		.clk(clk),
		.we(we_6),
		.wr_addr(wr_addr_calc),
		.wr_data(pixel_in),
		.rd_addr(rd_addr_mux),
		.rd_data(rd_data_6)
	);

	frame_ram #(
		.DATA_W(15),
		.DEPTH(EPI_FRAME_SIZE),
		.ADDR_W(EPI_FRAME_PTR_W)
	) frame_7_ram (
		.clk(clk),
		.we(we_7),
		.wr_addr(wr_addr_calc),
		.wr_data(pixel_in),
		.rd_addr(rd_addr_mux),
		.rd_data(rd_data_7)
	);

	// h_04 row-major copy
	frame_ram #(
		.DATA_W(15),
		.DEPTH(EPI_FRAME_SIZE),
		.ADDR_W(EPI_FRAME_PTR_W)
	) frame_8_ram (
		.clk(clk),
		.we(we_8),
		.wr_addr(wr_addr_row_major),
		.wr_data(pixel_in),
		.rd_addr(rd_addr_mux),
		.rd_data(rd_data_8)
	);

	// v_04 transposed copy
	frame_ram #(
		.DATA_W(15),
		.DEPTH(EPI_FRAME_SIZE),
		.ADDR_W(EPI_FRAME_PTR_W)
	) frame_8v_ram (
		.clk(clk),
		.we(we_8v),
		.wr_addr(wr_addr_transposed),
		.wr_data(pixel_in),
		.rd_addr(rd_addr_mux),
		.rd_data(rd_data_8v)
	);

	frame_ram #(
		.DATA_W(15),
		.DEPTH(EPI_FRAME_SIZE),
		.ADDR_W(EPI_FRAME_PTR_W)
	) frame_9_ram (
		.clk(clk),
		.we(we_9),
		.wr_addr(wr_addr_calc),
		.wr_data(pixel_in),
		.rd_addr(rd_addr_mux),
		.rd_data(rd_data_9)
	);

	frame_ram #(
		.DATA_W(15),
		.DEPTH(EPI_FRAME_SIZE),
		.ADDR_W(EPI_FRAME_PTR_W)
	) frame_10_ram (
		.clk(clk),
		.we(we_10),
		.wr_addr(wr_addr_calc),
		.wr_data(pixel_in),
		.rd_addr(rd_addr_mux),
		.rd_data(rd_data_10)
	);

	frame_ram #(
		.DATA_W(15),
		.DEPTH(EPI_FRAME_SIZE),
		.ADDR_W(EPI_FRAME_PTR_W)
	) frame_11_ram (
		.clk(clk),
		.we(we_11),
		.wr_addr(wr_addr_calc),
		.wr_data(pixel_in),
		.rd_addr(rd_addr_mux),
		.rd_data(rd_data_11)
	);

	// -------------------------------------------------------------------------
	// Write-enable decode
	// -------------------------------------------------------------------------
	always_comb begin
		we_0  = 1'b0;
		we_1  = 1'b0;
		we_2  = 1'b0;
		we_3  = 1'b0;
		we_4  = 1'b0;
		we_5  = 1'b0;
		we_6  = 1'b0;
		we_7  = 1'b0;
		we_8  = 1'b0;
		we_8v = 1'b0;
		we_9  = 1'b0;
		we_10 = 1'b0;
		we_11 = 1'b0;

		if (write_phase) begin
			case (capture_in_count)
				5'd0  : we_0  = 1'b1;   // v_00 (transposed)
				5'd1  : we_1  = 1'b1;   // v_01 (transposed)
				5'd2  : we_2  = 1'b1;   // v_02 (transposed)
				5'd3  : we_3  = 1'b1;   // v_03 (transposed)
				5'd4  : we_4  = 1'b1;   // h_00
				5'd5  : we_5  = 1'b1;   // h_01
				5'd6  : we_6  = 1'b1;   // h_02
				5'd7  : we_7  = 1'b1;   // h_03
				5'd8  : begin            // h_04 and v_04
					we_8  = 1'b1;       // row-major copy
					we_8v = 1'b1;       // transposed copy
				end
				5'd9  : we_9  = 1'b1;   // h_05
				5'd10 : we_10 = 1'b1;   // h_06
				5'd11 : we_11 = 1'b1;   // h_07
				5'd13 : we_9  = 1'b1;   // v_05 overwrites h_05 (transposed)
				5'd14 : we_10 = 1'b1;   // v_06 overwrites h_06 (transposed)
				5'd15 : we_11 = 1'b1;   // v_07 overwrites h_07 (transposed)
				default: begin
				end
			endcase
		end

		// Reuse frame_4 (former h_00 RAM) for v_08 transposed.
		// This is safe because horizontal output has already completed before capture 16.
		if (v08_store_phase) begin
			we_4 = 1'b1;
		end
	end

	// -------------------------------------------------------------------------
	// Light-field / counters
	// -------------------------------------------------------------------------
	always_ff @(posedge clk) begin : LF_Control_And_Addressing
		if (solf_in) begin
			in_lf_flag       <= 1'b1;
			capture_in_count <= 5'd0;
			row_in_count     <= '0;
			column_in_count  <= '0;
		end
		else if (eolf_in) begin
			in_lf_flag        <= 1'b0;
			capture_in_count  <= 5'd0;
			row_in_count      <= '0;
			column_in_count_d <= column_in_count;
			column_in_count   <= '0;
		end

		if ((in_lf_flag || solf_in) && pixel_valid_in) begin
			// Delay stream pixel and metadata by 1 cycle to align with RAM read
			h_read_phase_d    <= h_read_phase;
			pixel_in_d        <= pixel_in;
			row_in_count_d    <= row_in_count;
			column_in_count_d <= column_in_count;

			// Reset address/counters at start of each capture
			if (soc_in) begin
				row_in_count    <= '0;
				column_in_count <= {{(IMAGE_DIM_BS-1){1'b0}}, 1'b1};
			end
			else begin
				if (column_in_count == IMAGE_DIM-1) begin
					column_in_count <= '0;
					row_in_count    <= row_in_count + {{(IMAGE_DIM_BS-1){1'b0}}, 1'b1};
				end
				else begin
					column_in_count <= column_in_count + {{(IMAGE_DIM_BS-1){1'b0}}, 1'b1};
				end
			end

			// End of capture
			if (eoc_in) begin
				row_in_count    <= '0;
				column_in_count <= '0;

				if (!eolf_in && capture_in_count < 5'd16) begin
					capture_in_count <= capture_in_count + 5'd1;
				end
			end
		end
		else begin
			h_read_phase_d <= 1'b0;
		end
	end

	// -------------------------------------------------------------------------
	// Vertical post-frame readout
	// -------------------------------------------------------------------------
	always_ff @(posedge clk) begin : Vertical_Post_Frame_Output
		v_read_issue_d <= 1'b0;

		if (solf_in) begin
			vertical_output_pending <= 1'b0;
			vertical_output_active  <= 1'b0;
			v_epi_idx               <= '0;
			v_spatial_idx           <= '0;
			v_epi_idx_d             <= '0;
			v_spatial_idx_d         <= '0;
		end
		else if (eolf_in) begin
			// arm vertical post-frame output after LF finishes
			vertical_output_pending <= 1'b1;
		end
		else begin
			if (vertical_output_pending) begin
				vertical_output_pending <= 1'b0;
				vertical_output_active  <= 1'b1;
				v_epi_idx               <= '0;
				v_spatial_idx           <= '0;
			end
			else if (vertical_output_active) begin
				// issue one RAM read this cycle
				v_read_issue_d  <= 1'b1;
				v_epi_idx_d     <= v_epi_idx;
				v_spatial_idx_d <= v_spatial_idx;

				if (v_spatial_idx == IMAGE_DIM-1) begin
					v_spatial_idx <= '0;

					if (v_epi_idx == IMAGE_DIM-1) begin
						v_epi_idx              <= '0;
						vertical_output_active <= 1'b0;
					end
					else begin
						v_epi_idx <= v_epi_idx + {{(IMAGE_DIM_BS-1){1'b0}}, 1'b1};
					end
				end
				else begin
					v_spatial_idx <= v_spatial_idx + {{(IMAGE_DIM_BS-1){1'b0}}, 1'b1};
				end
			end
		end
	end

	// -------------------------------------------------------------------------
	// Output stage
	// -------------------------------------------------------------------------
	always_ff @(posedge clk) begin : EPI_Output
		epi_valid_out      <= 1'b0;
		epi_column_idx_out <= '0;
		epi_idx_out        <= '0;
		orientation_out    <= 1'b0;

		epi_column_out[0]  <= 15'd0;
		epi_column_out[1]  <= 15'd0;
		epi_column_out[2]  <= 15'd0;
		epi_column_out[3]  <= 15'd0;
		epi_column_out[4]  <= 15'd0;
		epi_column_out[5]  <= 15'd0;
		epi_column_out[6]  <= 15'd0;
		epi_column_out[7]  <= 15'd0;
		epi_column_out[8]  <= 15'd0;

		// Horizontal: live output, epi fixed and spatial changes
		if (h_read_phase_d) begin
			orientation_out    <= 1'b0;
			epi_valid_out      <= 1'b1;
			epi_idx_out        <= row_in_count_d;
			epi_column_idx_out <= column_in_count_d;

			epi_column_out[0] <= rd_data_4;   // h_00
			epi_column_out[1] <= rd_data_5;   // h_01
			epi_column_out[2] <= rd_data_6;   // h_02
			epi_column_out[3] <= rd_data_7;   // h_03
			epi_column_out[4] <= rd_data_8;   // h_04
			epi_column_out[5] <= rd_data_9;   // h_05
			epi_column_out[6] <= rd_data_10;  // h_06
			epi_column_out[7] <= rd_data_11;  // h_07
			epi_column_out[8] <= pixel_in_d;  // live h_08
		end

		// Vertical: post-frame buffered output, epi fixed and spatial changes
		else if (v_read_issue_d) begin
			orientation_out    <= 1'b1;
			epi_valid_out      <= 1'b1;
			epi_idx_out        <= v_epi_idx_d;
			epi_column_idx_out <= v_spatial_idx_d;

			epi_column_out[0] <= rd_data_0;   // v_00
			epi_column_out[1] <= rd_data_1;   // v_01
			epi_column_out[2] <= rd_data_2;   // v_02
			epi_column_out[3] <= rd_data_3;   // v_03
			epi_column_out[4] <= rd_data_8v;  // v_04
			epi_column_out[5] <= rd_data_9;   // v_05
			epi_column_out[6] <= rd_data_10;  // v_06
			epi_column_out[7] <= rd_data_11;  // v_07
			epi_column_out[8] <= rd_data_4;   // v_08 reusing former h_00 RAM
		end
	end

endmodule