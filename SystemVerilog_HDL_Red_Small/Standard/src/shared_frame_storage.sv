module shared_frame_storage #(
	parameter int unsigned IMAGE_DIM    = 64
)(
	input  wire                                   clk,

	// When 0: banks 5..8 writes are owned by epi_compiler
	// When 1: banks 5..8 writes are owned by fused_aligned_output
	input  wire                                   takeover_banks_5_to_8,

	// During the horizontal read frame, EPI compiler must still own the READ
	// addresses for banks 5..8 even after FAO has taken over the WRITE ports.
	input  wire                                   epi_read_banks_5_to_8_active,

	// ---------------------------------------------------------------------
	// EPI compiler side
	// ---------------------------------------------------------------------
	input  wire                                   epi_we [0:11],
	input  wire                                   epi_we_8v,
	input  wire [((2*$clog2(IMAGE_DIM))-1):0]     epi_wr_addr [0:11],
	input  wire [((2*$clog2(IMAGE_DIM))-1):0]     epi_wr_addr_8v,
	input  wire [14:0]                            epi_wr_data,
	input  wire [((2*$clog2(IMAGE_DIM))-1):0]     epi_rd_addr,
	output logic [14:0]                           epi_rd_data [0:11],
	output logic [14:0]                           epi_rd_data_8v,

	// ---------------------------------------------------------------------
	// FAO side, mapped onto shared banks 5..8
	// fao bank 0 -> shared bank 5
	// fao bank 1 -> shared bank 6
	// fao bank 2 -> shared bank 7
	// fao bank 3 -> shared bank 8
	// ---------------------------------------------------------------------
	input  wire                                   fao_we [0:3],
	input  wire [((2*$clog2(IMAGE_DIM))-1):0]     fao_wr_addr [0:3],
	input  wire [14:0]                            fao_wr_data [0:3],
	input  wire [((2*$clog2(IMAGE_DIM))-1):0]     fao_rd_addr [0:3],
	output logic [14:0]                           fao_rd_data [0:3]
);

	localparam int unsigned FRAME_SIZE = IMAGE_DIM * IMAGE_DIM;
	localparam int unsigned ADDR_W     = 2 * $clog2(IMAGE_DIM);

	// ---------------------------------------------------------------------
	// Local per-bank registered read addresses
	// These reduce fanout/routing from epi_rd_addr into many RAM blocks.
	// ---------------------------------------------------------------------
	(* preserve, maxfan = 4 *) logic [ADDR_W-1:0] bank0_rd_addr_q;
	(* preserve, maxfan = 4 *) logic [ADDR_W-1:0] bank1_rd_addr_q;
	(* preserve, maxfan = 4 *) logic [ADDR_W-1:0] bank2_rd_addr_q;
	(* preserve, maxfan = 4 *) logic [ADDR_W-1:0] bank3_rd_addr_q;
	(* preserve, maxfan = 4 *) logic [ADDR_W-1:0] bank4_rd_addr_q;
	(* preserve, maxfan = 4 *) logic [ADDR_W-1:0] bank8v_rd_addr_q;
	(* preserve, maxfan = 4 *) logic [ADDR_W-1:0] bank9_rd_addr_q;
	(* preserve, maxfan = 4 *) logic [ADDR_W-1:0] bank10_rd_addr_q;
	(* preserve, maxfan = 2 *) logic [ADDR_W-1:0] bank11_rd_addr_q;

	(* preserve, maxfan = 4 *) logic [ADDR_W-1:0] bank5_rd_addr_q;
	(* preserve, maxfan = 4 *) logic [ADDR_W-1:0] bank6_rd_addr_q;
	(* preserve, maxfan = 4 *) logic [ADDR_W-1:0] bank7_rd_addr_q;
	(* preserve, maxfan = 4 *) logic [ADDR_W-1:0] bank8_rd_addr_q;

	// ---------------------------------------------------------------------
	// New: local registered write commands/data per RAM bank
	// This breaks the long EPIC->shared->RAM write path.
	// ---------------------------------------------------------------------
	(* preserve *) logic              bank0_we_q;
	(* preserve *) logic [ADDR_W-1:0] bank0_wr_addr_q;
	(* preserve *) logic [14:0]       bank0_wr_data_q;

	(* preserve *) logic              bank1_we_q;
	(* preserve *) logic [ADDR_W-1:0] bank1_wr_addr_q;
	(* preserve *) logic [14:0]       bank1_wr_data_q;

	(* preserve *) logic              bank2_we_q;
	(* preserve *) logic [ADDR_W-1:0] bank2_wr_addr_q;
	(* preserve *) logic [14:0]       bank2_wr_data_q;

	(* preserve *) logic              bank3_we_q;
	(* preserve *) logic [ADDR_W-1:0] bank3_wr_addr_q;
	(* preserve *) logic [14:0]       bank3_wr_data_q;

	(* preserve *) logic              bank4_we_q;
	(* preserve *) logic [ADDR_W-1:0] bank4_wr_addr_q;
	(* preserve *) logic [14:0]       bank4_wr_data_q;

	(* preserve *) logic              bank8v_we_q;
	(* preserve *) logic [ADDR_W-1:0] bank8v_wr_addr_q;
	(* preserve *) logic [14:0]       bank8v_wr_data_q;

	(* preserve *) logic              bank9_we_q;
	(* preserve *) logic [ADDR_W-1:0] bank9_wr_addr_q;
	(* preserve *) logic [14:0]       bank9_wr_data_q;

	(* preserve *) logic              bank10_we_q;
	(* preserve *) logic [ADDR_W-1:0] bank10_wr_addr_q;
	(* preserve *) logic [14:0]       bank10_wr_data_q;

	(* preserve *) logic              bank11_we_q;
	(* preserve *) logic [ADDR_W-1:0] bank11_wr_addr_q;
	(* preserve *) logic [14:0]       bank11_wr_data_q;

	(* preserve *) logic              bank5_we_q;
	(* preserve *) logic [ADDR_W-1:0] bank5_wr_addr_q;
	(* preserve, maxfan = 1 *) logic [14:0]       bank5_wr_data_q;

	(* preserve *) logic              bank6_we_q;
	(* preserve *) logic [ADDR_W-1:0] bank6_wr_addr_q;
	(* preserve, maxfan = 1 *) logic [14:0]       bank6_wr_data_q;

	(* preserve *) logic              bank7_we_q;
	(* preserve *) logic [ADDR_W-1:0] bank7_wr_addr_q;
	(* preserve, maxfan = 1 *) logic [14:0]       bank7_wr_data_q;

	(* preserve *) logic              bank8_we_q;
	(* preserve *) logic [ADDR_W-1:0] bank8_wr_addr_q;
	(* preserve, maxfan = 1 *) logic [14:0]       bank8_wr_data_q;

	always_ff @(posedge clk) begin
		// Dedicated EPIC banks
		bank0_rd_addr_q  <= epi_rd_addr;
		bank1_rd_addr_q  <= epi_rd_addr;
		bank2_rd_addr_q  <= epi_rd_addr;
		bank3_rd_addr_q  <= epi_rd_addr;
		bank4_rd_addr_q  <= epi_rd_addr;
		bank8v_rd_addr_q <= epi_rd_addr;
		bank9_rd_addr_q  <= epi_rd_addr;
		bank10_rd_addr_q <= epi_rd_addr;
		bank11_rd_addr_q <= epi_rd_addr;

		// Shared banks 5..8 read ownership
		if (!takeover_banks_5_to_8 || epi_read_banks_5_to_8_active) begin
			bank5_rd_addr_q <= epi_rd_addr;
			bank6_rd_addr_q <= epi_rd_addr;
			bank7_rd_addr_q <= epi_rd_addr;
			bank8_rd_addr_q <= epi_rd_addr;
		end
		else begin
			bank5_rd_addr_q <= fao_rd_addr[0];
			bank6_rd_addr_q <= fao_rd_addr[1];
			bank7_rd_addr_q <= fao_rd_addr[2];
			bank8_rd_addr_q <= fao_rd_addr[3];
		end

		// -----------------------------------------------------------------
		// Register dedicated-bank writes locally
		// -----------------------------------------------------------------
		bank0_we_q      <= epi_we[0];
		bank0_wr_addr_q <= epi_wr_addr[0];
		bank0_wr_data_q <= epi_wr_data;

		bank1_we_q      <= epi_we[1];
		bank1_wr_addr_q <= epi_wr_addr[1];
		bank1_wr_data_q <= epi_wr_data;

		bank2_we_q      <= epi_we[2];
		bank2_wr_addr_q <= epi_wr_addr[2];
		bank2_wr_data_q <= epi_wr_data;

		bank3_we_q      <= epi_we[3];
		bank3_wr_addr_q <= epi_wr_addr[3];
		bank3_wr_data_q <= epi_wr_data;

		bank4_we_q      <= epi_we[4];
		bank4_wr_addr_q <= epi_wr_addr[4];
		bank4_wr_data_q <= epi_wr_data;

		bank8v_we_q      <= epi_we_8v;
		bank8v_wr_addr_q <= epi_wr_addr_8v;
		bank8v_wr_data_q <= epi_wr_data;

		bank9_we_q      <= epi_we[9];
		bank9_wr_addr_q <= epi_wr_addr[9];
		bank9_wr_data_q <= epi_wr_data;

		bank10_we_q      <= epi_we[10];
		bank10_wr_addr_q <= epi_wr_addr[10];
		bank10_wr_data_q <= epi_wr_data;

		bank11_we_q      <= epi_we[11];
		bank11_wr_addr_q <= epi_wr_addr[11];
		bank11_wr_data_q <= epi_wr_data;

		// -----------------------------------------------------------------
		// Register shared-bank writes locally after ownership muxing
		// -----------------------------------------------------------------
		if (!takeover_banks_5_to_8) begin
			bank5_we_q      <= epi_we[5];
			bank5_wr_addr_q <= epi_wr_addr[5];
			bank5_wr_data_q <= epi_wr_data;

			bank6_we_q      <= epi_we[6];
			bank6_wr_addr_q <= epi_wr_addr[6];
			bank6_wr_data_q <= epi_wr_data;

			bank7_we_q      <= epi_we[7];
			bank7_wr_addr_q <= epi_wr_addr[7];
			bank7_wr_data_q <= epi_wr_data;

			bank8_we_q      <= epi_we[8];
			bank8_wr_addr_q <= epi_wr_addr[8];
			bank8_wr_data_q <= epi_wr_data;
		end
		else begin
			bank5_we_q      <= fao_we[0];
			bank5_wr_addr_q <= fao_wr_addr[0];
			bank5_wr_data_q <= fao_wr_data[0];

			bank6_we_q      <= fao_we[1];
			bank6_wr_addr_q <= fao_wr_addr[1];
			bank6_wr_data_q <= fao_wr_data[1];

			bank7_we_q      <= fao_we[2];
			bank7_wr_addr_q <= fao_wr_addr[2];
			bank7_wr_data_q <= fao_wr_data[2];

			bank8_we_q      <= fao_we[3];
			bank8_wr_addr_q <= fao_wr_addr[3];
			bank8_wr_data_q <= fao_wr_data[3];
		end
	end

	// ---------------------------------------------------------------------
	// Dedicated banks always owned by EPI compiler
	// ---------------------------------------------------------------------
	frame_ram #(
		.DATA_W(15),
		.DEPTH(FRAME_SIZE),
		.ADDR_W(ADDR_W)
	) bank_0 (
		.clk(clk),
		.we(bank0_we_q),
		.wr_addr(bank0_wr_addr_q),
		.wr_data(bank0_wr_data_q),
		.rd_addr(bank0_rd_addr_q),
		.rd_data(epi_rd_data[0])
	);

	frame_ram #(
		.DATA_W(15),
		.DEPTH(FRAME_SIZE),
		.ADDR_W(ADDR_W)
	) bank_1 (
		.clk(clk),
		.we(bank1_we_q),
		.wr_addr(bank1_wr_addr_q),
		.wr_data(bank1_wr_data_q),
		.rd_addr(bank1_rd_addr_q),
		.rd_data(epi_rd_data[1])
	);

	frame_ram #(
		.DATA_W(15),
		.DEPTH(FRAME_SIZE),
		.ADDR_W(ADDR_W)
	) bank_2 (
		.clk(clk),
		.we(bank2_we_q),
		.wr_addr(bank2_wr_addr_q),
		.wr_data(bank2_wr_data_q),
		.rd_addr(bank2_rd_addr_q),
		.rd_data(epi_rd_data[2])
	);

	frame_ram #(
		.DATA_W(15),
		.DEPTH(FRAME_SIZE),
		.ADDR_W(ADDR_W)
	) bank_3 (
		.clk(clk),
		.we(bank3_we_q),
		.wr_addr(bank3_wr_addr_q),
		.wr_data(bank3_wr_data_q),
		.rd_addr(bank3_rd_addr_q),
		.rd_data(epi_rd_data[3])
	);

	frame_ram #(
		.DATA_W(15),
		.DEPTH(FRAME_SIZE),
		.ADDR_W(ADDR_W)
	) bank_4 (
		.clk(clk),
		.we(bank4_we_q),
		.wr_addr(bank4_wr_addr_q),
		.wr_data(bank4_wr_data_q),
		.rd_addr(bank4_rd_addr_q),
		.rd_data(epi_rd_data[4])
	);

	frame_ram #(
		.DATA_W(15),
		.DEPTH(FRAME_SIZE),
		.ADDR_W(ADDR_W)
	) bank_8v (
		.clk(clk),
		.we(bank8v_we_q),
		.wr_addr(bank8v_wr_addr_q),
		.wr_data(bank8v_wr_data_q),
		.rd_addr(bank8v_rd_addr_q),
		.rd_data(epi_rd_data_8v)
	);

	frame_ram #(
		.DATA_W(15),
		.DEPTH(FRAME_SIZE),
		.ADDR_W(ADDR_W)
	) bank_9 (
		.clk(clk),
		.we(bank9_we_q),
		.wr_addr(bank9_wr_addr_q),
		.wr_data(bank9_wr_data_q),
		.rd_addr(bank9_rd_addr_q),
		.rd_data(epi_rd_data[9])
	);

	frame_ram #(
		.DATA_W(15),
		.DEPTH(FRAME_SIZE),
		.ADDR_W(ADDR_W)
	) bank_10 (
		.clk(clk),
		.we(bank10_we_q),
		.wr_addr(bank10_wr_addr_q),
		.wr_data(bank10_wr_data_q),
		.rd_addr(bank10_rd_addr_q),
		.rd_data(epi_rd_data[10])
	);

	frame_ram #(
		.DATA_W(15),
		.DEPTH(FRAME_SIZE),
		.ADDR_W(ADDR_W)
	) bank_11 (
		.clk(clk),
		.we(bank11_we_q),
		.wr_addr(bank11_wr_addr_q),
		.wr_data(bank11_wr_data_q),
		.rd_addr(bank11_rd_addr_q),
		.rd_data(epi_rd_data[11])
	);

	// ---------------------------------------------------------------------
	// Shared banks 5..8
	// ---------------------------------------------------------------------
	logic [14:0] bank5_rd_data;
	logic [14:0] bank6_rd_data;
	logic [14:0] bank7_rd_data;
	logic [14:0] bank8_rd_data;

	frame_ram #(
		.DATA_W(15),
		.DEPTH(FRAME_SIZE),
		.ADDR_W(ADDR_W)
	) bank_5 (
		.clk(clk),
		.we(bank5_we_q),
		.wr_addr(bank5_wr_addr_q),
		.wr_data(bank5_wr_data_q),
		.rd_addr(bank5_rd_addr_q),
		.rd_data(bank5_rd_data)
	);

	frame_ram #(
		.DATA_W(15),
		.DEPTH(FRAME_SIZE),
		.ADDR_W(ADDR_W)
	) bank_6 (
		.clk(clk),
		.we(bank6_we_q),
		.wr_addr(bank6_wr_addr_q),
		.wr_data(bank6_wr_data_q),
		.rd_addr(bank6_rd_addr_q),
		.rd_data(bank6_rd_data)
	);

	frame_ram #(
		.DATA_W(15),
		.DEPTH(FRAME_SIZE),
		.ADDR_W(ADDR_W)
	) bank_7 (
		.clk(clk),
		.we(bank7_we_q),
		.wr_addr(bank7_wr_addr_q),
		.wr_data(bank7_wr_data_q),
		.rd_addr(bank7_rd_addr_q),
		.rd_data(bank7_rd_data)
	);

	frame_ram #(
		.DATA_W(15),
		.DEPTH(FRAME_SIZE),
		.ADDR_W(ADDR_W)
	) bank_8 (
		.clk(clk),
		.we(bank8_we_q),
		.wr_addr(bank8_wr_addr_q),
		.wr_data(bank8_wr_data_q),
		.rd_addr(bank8_rd_addr_q),
		.rd_data(bank8_rd_data)
	);

	always_comb begin
		epi_rd_data[5] = bank5_rd_data;
		epi_rd_data[6] = bank6_rd_data;
		epi_rd_data[7] = bank7_rd_data;
		epi_rd_data[8] = bank8_rd_data;

		fao_rd_data[0] = bank5_rd_data;
		fao_rd_data[1] = bank6_rd_data;
		fao_rd_data[2] = bank7_rd_data;
		fao_rd_data[3] = bank8_rd_data;
	end

endmodule