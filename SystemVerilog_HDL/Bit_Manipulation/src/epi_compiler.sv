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
	logic [EPI_FRAME_PTR_W-1:0]             frame_addr       = '0;
	logic [EPI_FRAME_PTR_W-1:0]             rd_addr          = '0;

	// -------------------------------------------------------------------------
	// Read/write phase control
	// -------------------------------------------------------------------------
	logic read_phase;
	logic write_phase;
	logic read_phase_d;
	logic orientation_d;

	assign read_phase  = in_lf_flag && pixel_valid_in &&
	                     ((capture_in_count == H_READ_CAPTURE) || (capture_in_count == V_READ_CAPTURE));

	assign write_phase = in_lf_flag && pixel_valid_in &&
	                     (capture_in_count != H_READ_CAPTURE) &&
	                     (capture_in_count != V_READ_CAPTURE);

	// Delay current streamed pixel + metadata by 1 cycle so it aligns with RAM read data
	logic [14:0]                      pixel_in_d         = '0;
	logic [IMAGE_DIM_BS-1:0]          row_in_count_d     = '0;
	logic [IMAGE_DIM_BS-1:0]          column_in_count_d  = '0;

	// -------------------------------------------------------------------------
	// One write-enable per RAM
	// -------------------------------------------------------------------------
	logic we_0;
	logic we_1;
	logic we_2;
	logic we_3;
	logic we_4;
	logic we_5;
	logic we_6;
	logic we_7;
	logic we_8;
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
	logic [14:0] rd_data_4;
	logic [14:0] rd_data_5;
	logic [14:0] rd_data_6;
	logic [14:0] rd_data_7;
	logic [14:0] rd_data_8;
	logic [14:0] rd_data_9;
	logic [14:0] rd_data_10;
	logic [14:0] rd_data_11;

	// -------------------------------------------------------------------------
	// 12 frame RAMs
	// -------------------------------------------------------------------------
	frame_ram #(
		.DATA_W(15),
		.DEPTH(EPI_FRAME_SIZE),
		.ADDR_W(EPI_FRAME_PTR_W)
	) frame_0_ram (
		.clk(clk),
		.we(we_0),
		.wr_addr(frame_addr),
		.wr_data(pixel_in),
		.rd_addr(rd_addr),
		.rd_data(rd_data_0)
	);

	frame_ram #(
		.DATA_W(15),
		.DEPTH(EPI_FRAME_SIZE),
		.ADDR_W(EPI_FRAME_PTR_W)
	) frame_1_ram (
		.clk(clk),
		.we(we_1),
		.wr_addr(frame_addr),
		.wr_data(pixel_in),
		.rd_addr(rd_addr),
		.rd_data(rd_data_1)
	);

	frame_ram #(
		.DATA_W(15),
		.DEPTH(EPI_FRAME_SIZE),
		.ADDR_W(EPI_FRAME_PTR_W)
	) frame_2_ram (
		.clk(clk),
		.we(we_2),
		.wr_addr(frame_addr),
		.wr_data(pixel_in),
		.rd_addr(rd_addr),
		.rd_data(rd_data_2)
	);

	frame_ram #(
		.DATA_W(15),
		.DEPTH(EPI_FRAME_SIZE),
		.ADDR_W(EPI_FRAME_PTR_W)
	) frame_3_ram (
		.clk(clk),
		.we(we_3),
		.wr_addr(frame_addr),
		.wr_data(pixel_in),
		.rd_addr(rd_addr),
		.rd_data(rd_data_3)
	);

	frame_ram #(
		.DATA_W(15),
		.DEPTH(EPI_FRAME_SIZE),
		.ADDR_W(EPI_FRAME_PTR_W)
	) frame_4_ram (
		.clk(clk),
		.we(we_4),
		.wr_addr(frame_addr),
		.wr_data(pixel_in),
		.rd_addr(rd_addr),
		.rd_data(rd_data_4)
	);

	frame_ram #(
		.DATA_W(15),
		.DEPTH(EPI_FRAME_SIZE),
		.ADDR_W(EPI_FRAME_PTR_W)
	) frame_5_ram (
		.clk(clk),
		.we(we_5),
		.wr_addr(frame_addr),
		.wr_data(pixel_in),
		.rd_addr(rd_addr),
		.rd_data(rd_data_5)
	);

	frame_ram #(
		.DATA_W(15),
		.DEPTH(EPI_FRAME_SIZE),
		.ADDR_W(EPI_FRAME_PTR_W)
	) frame_6_ram (
		.clk(clk),
		.we(we_6),
		.wr_addr(frame_addr),
		.wr_data(pixel_in),
		.rd_addr(rd_addr),
		.rd_data(rd_data_6)
	);

	frame_ram #(
		.DATA_W(15),
		.DEPTH(EPI_FRAME_SIZE),
		.ADDR_W(EPI_FRAME_PTR_W)
	) frame_7_ram (
		.clk(clk),
		.we(we_7),
		.wr_addr(frame_addr),
		.wr_data(pixel_in),
		.rd_addr(rd_addr),
		.rd_data(rd_data_7)
	);

	frame_ram #(
		.DATA_W(15),
		.DEPTH(EPI_FRAME_SIZE),
		.ADDR_W(EPI_FRAME_PTR_W)
	) frame_8_ram (
		.clk(clk),
		.we(we_8),
		.wr_addr(frame_addr),
		.wr_data(pixel_in),
		.rd_addr(rd_addr),
		.rd_data(rd_data_8)
	);

	frame_ram #(
		.DATA_W(15),
		.DEPTH(EPI_FRAME_SIZE),
		.ADDR_W(EPI_FRAME_PTR_W)
	) frame_9_ram (
		.clk(clk),
		.we(we_9),
		.wr_addr(frame_addr),
		.wr_data(pixel_in),
		.rd_addr(rd_addr),
		.rd_data(rd_data_9)
	);

	frame_ram #(
		.DATA_W(15),
		.DEPTH(EPI_FRAME_SIZE),
		.ADDR_W(EPI_FRAME_PTR_W)
	) frame_10_ram (
		.clk(clk),
		.we(we_10),
		.wr_addr(frame_addr),
		.wr_data(pixel_in),
		.rd_addr(rd_addr),
		.rd_data(rd_data_10)
	);

	frame_ram #(
		.DATA_W(15),
		.DEPTH(EPI_FRAME_SIZE),
		.ADDR_W(EPI_FRAME_PTR_W)
	) frame_11_ram (
		.clk(clk),
		.we(we_11),
		.wr_addr(frame_addr),
		.wr_data(pixel_in),
		.rd_addr(rd_addr),
		.rd_data(rd_data_11)
	);

	// -------------------------------------------------------------------------
	// Write-enable decode
	// Only one RAM writes on any valid write cycle.
	// No writes occur during read cycles (capture 12 and 16).
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
		we_9  = 1'b0;
		we_10 = 1'b0;
		we_11 = 1'b0;

		if (write_phase) begin
			case (capture_in_count)
				5'd0  : we_0  = 1'b1;  // v_00
				5'd1  : we_1  = 1'b1;  // v_01
				5'd2  : we_2  = 1'b1;  // v_02
				5'd3  : we_3  = 1'b1;  // v_03
				5'd4  : we_4  = 1'b1;  // h_00
				5'd5  : we_5  = 1'b1;  // h_01
				5'd6  : we_6  = 1'b1;  // h_02
				5'd7  : we_7  = 1'b1;  // h_03
				5'd8  : we_8  = 1'b1;  // h_04 / v_04
				5'd9  : we_9  = 1'b1;  // h_05
				5'd10 : we_10 = 1'b1;  // h_06
				5'd11 : we_11 = 1'b1;  // h_07
				5'd13 : we_9  = 1'b1;  // v_05 overwrites h_05
				5'd14 : we_10 = 1'b1;  // v_06 overwrites h_06
				5'd15 : we_11 = 1'b1;  // v_07 overwrites h_07
				default: begin
				end
			endcase
		end
	end

	// -------------------------------------------------------------------------
	// Light-field / address / counters
	// Same address counter is used:
	// - as write address during write captures
	// - as read address during h_08 / v_08 captures
	// -------------------------------------------------------------------------
	always_ff @(posedge clk) begin : LF_Control_And_Addressing
		if (solf_in) begin
			in_lf_flag       <= 1'b1;
			capture_in_count <= 5'd0;
			frame_addr       <= '0;
			row_in_count     <= '0;
			column_in_count  <= '0;
			rd_addr          <= '0;
		end
		else if (eolf_in) begin
			in_lf_flag       <= 1'b0;
			capture_in_count <= 5'd0;
			frame_addr       <= '0;
			row_in_count     <= '0;
			column_in_count  <= '0;
			rd_addr          <= '0;
		end
		else if (in_lf_flag && pixel_valid_in) begin
			// Present current address to RAM read port only during read captures
			if (read_phase) begin
				if (soc_in) begin
					rd_addr <= '0;
				end
				else begin
					rd_addr <= frame_addr;
				end
			end

			// Delay stream pixel and metadata by one cycle to align with RAM read
			read_phase_d       <= read_phase;
			orientation_d      <= (capture_in_count == V_READ_CAPTURE);
			pixel_in_d         <= pixel_in;
			row_in_count_d     <= row_in_count;
			column_in_count_d  <= column_in_count;

			// Reset address/counters at start of each capture
			if (soc_in) begin
				frame_addr      <= '0;
				row_in_count    <= '0;
				column_in_count <= '0;
			end
			else begin
				frame_addr <= frame_addr + EPI_FRAME_PTR_W'(1);

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
				frame_addr      <= '0;
				row_in_count    <= '0;
				column_in_count <= '0;

				if (!eolf_in && capture_in_count < 5'd16) begin
					capture_in_count <= capture_in_count + 5'd1;
				end
			end
		end
		else begin
			read_phase_d  <= 1'b0;
		end
	end

	// -------------------------------------------------------------------------
	// Output stage
	// rd_data_* is valid one clock after rd_addr is presented.
	// pixel_in_d / *_d are delayed to align with rd_data_*.
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

		if (read_phase_d) begin
			orientation_out    <= orientation_d;
			epi_valid_out      <= 1'b1;
			epi_column_idx_out <= column_in_count_d;
			epi_idx_out        <= row_in_count_d;

			// Horizontal EPI: h_00..h_07 from RAM + current h_08 from stream
			if (!orientation_d) begin
				epi_column_out[0] <= rd_data_4;
				epi_column_out[1] <= rd_data_5;
				epi_column_out[2] <= rd_data_6;
				epi_column_out[3] <= rd_data_7;
				epi_column_out[4] <= rd_data_8;
				epi_column_out[5] <= rd_data_9;
				epi_column_out[6] <= rd_data_10;
				epi_column_out[7] <= rd_data_11;
				epi_column_out[8] <= pixel_in_d;
			end

			// Vertical EPI: v_00..v_07 from RAM + current v_08 from stream
			else begin
				epi_column_out[0] <= rd_data_0;
				epi_column_out[1] <= rd_data_1;
				epi_column_out[2] <= rd_data_2;
				epi_column_out[3] <= rd_data_3;
				epi_column_out[4] <= rd_data_8;
				epi_column_out[5] <= rd_data_9;
				epi_column_out[6] <= rd_data_10;
				epi_column_out[7] <= rd_data_11;
				epi_column_out[8] <= pixel_in_d;
			end
		end
	end

endmodule